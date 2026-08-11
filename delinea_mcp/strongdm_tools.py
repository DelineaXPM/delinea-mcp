"""StrongDM (SDM) infrastructure-access tooling.

Delinea completed the StrongDM acquisition in March 2026; this module adds
SDM as a third backend next to Secret Server and the Delinea Platform. It
talks to the SDM admin API through the official ``strongdm`` SDK (gRPC +
HMAC request signing — there is no public REST surface), installed via the
optional extra::

    pip install delinea-mcp[strongdm]

Tools follow the house compound-action contract: they accomplish a whole
admin intention (resolve names -> act -> verify) rather than wrapping
single API calls. Destructive actions require ``confirm=True`` and a
non-empty ``comment``; ``confirm=False`` returns a preview that makes no
mutating API call. Fuzzy name/email resolution that matches more than one
object returns the candidates and performs no mutation.

Credentials come from ``SDM_API_ACCESS_KEY`` / ``SDM_API_SECRET_KEY``
(the SDK-conventional env vars; API keys are created in the SDM Admin UI
under Principals > Tokens with a permission scope chosen at creation).
The non-secret ``strongdm_api_host`` config key selects the control plane
(default ``app.strongdm.com:443``; UK: ``app.uk.strongdm.com:443``,
EU: ``app.eu.strongdm.com:443``).

Known API asymmetry: access requests can be listed but NOT approved or
denied through the admin API — approval happens in the Admin UI or the
Slack/Teams/Jira integrations. ``sdm_access_requests`` documents this and
``sdm_grant_access`` offers the compensating time-boxed grant.
"""

from __future__ import annotations

import datetime
import itertools
import logging
import os
import threading
from typing import Any, Iterable

from delinea_mcp.annotations import TOOL_ANNOTATIONS

logger = logging.getLogger(__name__)

sdm_api_host = os.getenv("SDM_API_HOST", "app.strongdm.com:443")
sdm_access_key = os.getenv("SDM_API_ACCESS_KEY")
sdm_secret_key = os.getenv("SDM_API_SECRET_KEY")

# Hard ceiling applied to every SDK list() call: they return generators
# that transparently paginate through the entire org.
_LIST_CAP = 500

_SDK_NOT_INSTALLED_ERROR = (
    "The strongdm SDK is not installed. StrongDM tools require the optional "
    "extra: pip install delinea-mcp[strongdm] (or: uv sync --extra strongdm)."
)

_NOT_CONFIGURED_ERROR = (
    "StrongDM is not configured. Set SDM_API_ACCESS_KEY and "
    "SDM_API_SECRET_KEY (create an API key in the SDM Admin UI under "
    "Principals > Tokens), and optionally strongdm_api_host in config.json "
    "for non-US control planes."
)

_client: Any = None
# Tools run on parallel worker threads; serialise client construction.
_client_lock = threading.Lock()


def configure(
    api_host: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
) -> None:
    """Override StrongDM connection settings."""
    global sdm_api_host, sdm_access_key, sdm_secret_key, _client
    if api_host is not None:
        sdm_api_host = api_host
    if access_key is not None:
        sdm_access_key = access_key
    if secret_key is not None:
        sdm_secret_key = secret_key
    _client = None


def _sdm_configured() -> bool:
    return bool(sdm_access_key and sdm_secret_key)


def _get_client() -> Any:
    """Return the cached SDM client, building it on first use."""
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None:
            return _client
        try:
            import strongdm  # noqa: PLC0415 - optional dependency
        except ImportError:
            raise RuntimeError(_SDK_NOT_INSTALLED_ERROR) from None
        if not _sdm_configured():
            raise RuntimeError(_NOT_CONFIGURED_ERROR)
        _client = strongdm.Client(sdm_access_key, sdm_secret_key, host=sdm_api_host)
        return _client


def _to_dict(obj: Any) -> Any:
    """JSON-safe view of an SDK model (they all expose ``to_dict``)."""
    if hasattr(obj, "to_dict"):
        obj = obj.to_dict()
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_dict(v) for v in obj]
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    return obj


def _bounded(iterable: Iterable[Any], limit: int) -> list[Any]:
    return list(itertools.islice(iterable, min(int(limit), _LIST_CAP)))


def _error_text(exc: Exception) -> str:
    msg = getattr(exc, "msg", None) or str(exc)
    return f"{type(exc).__name__}: {msg}"


def _resolve(kind: str, lister: Any, field: str, value: str) -> tuple[Any, dict | None]:
    """Resolve *value* to exactly one object via exact-then-fuzzy filters.

    Returns ``(object, None)`` on a unique match, else ``(None, result)``
    where *result* is an error or a candidates dict — in both cases the
    caller must return it without mutating anything.
    """
    matches = _bounded(lister.list(f"{field}:?", value), 25)
    if not matches:
        matches = _bounded(lister.list(f"{field}:?", f"*{value}*"), 25)
    if not matches:
        return None, {"error": f"No {kind} found matching {field} '{value}'"}
    if len(matches) > 1:
        return None, {
            "error": f"Multiple {kind}s match {field} '{value}'; be more specific",
            "candidates": [
                {
                    "id": getattr(m, "id", None),
                    field: getattr(m, field, None),
                    "name": getattr(m, "name", None),
                    "type": type(m).__name__,
                }
                for m in matches
            ],
        }
    return matches[0], None


def _resolve_account(client: Any, email: str) -> tuple[Any, dict | None]:
    return _resolve("account", client.accounts, "email", email)


def _resolve_resource(client: Any, name: str) -> tuple[Any, dict | None]:
    return _resolve("resource", client.resources, "name", name)


def _resolve_role(client: Any, name: str) -> tuple[Any, dict | None]:
    return _resolve("role", client.roles, "name", name)


def _require_confirmation(confirm: bool, comment: str, preview: dict) -> dict | None:
    """House gate for destructive/mutating actions.

    Returns the preview payload when unconfirmed, an error when confirmed
    without an audit comment, or None when the action may proceed.
    """
    if not confirm:
        return {
            "preview": preview,
            "note": "No API mutation performed. Re-run with confirm=True and "
            "a non-empty comment to execute.",
        }
    if not comment:
        return {"error": "A non-empty comment is required when confirm=True"}
    return None


# --------------------------------------------------------------------------- #
# Search / audit (read-only)                                                  #
# --------------------------------------------------------------------------- #


def sdm_search(kind: str, query: str = "", limit: int = 50) -> dict:
    """Search StrongDM resources, accounts, or roles.

    Parameters
    ----------
    kind: one of ``resources``, ``accounts``, ``roles``.
    query: SDM filter expression (e.g. ``name:*prod*``, ``email:*@corp.com``,
        ``type:postgres``) or plain text, which is matched as a wildcard
        against resource/role names or account emails. Empty lists all
        (bounded by ``limit``).
    limit: maximum results (capped at 500).
    """
    logger.debug("sdm_search kind=%s query=%r", kind, query)
    try:
        client = _get_client()
        listers = {
            "resources": client.resources,
            "accounts": client.accounts,
            "roles": client.roles,
        }
        lister = listers.get(kind)
        if lister is None:
            raise ValueError(f"Unknown kind: {kind}; use one of {sorted(listers)}")
        if not query:
            flt, args = "", ()
        elif ":" in query:
            flt, args = query, ()
        elif kind == "accounts":
            flt, args = "email:?", (f"*{query}*",)
        else:
            flt, args = "name:?", (f"*{query}*",)
        items = _bounded(lister.list(flt, *args), limit)
        return {"results": [_to_dict(i) for i in items], "count": len(items)}
    except Exception as exc:
        logger.error("sdm_search failed: %s", exc)
        return {"error": _error_text(exc)}


def sdm_audit_access(subject: str, name: str, limit: int = 100) -> dict:
    """Report who can access what, from a user, resource, or role viewpoint.

    Compound entitlement audit:

    - ``subject='user'`` (*name* is an email): current resource access
      (direct grants and role/group-derived, with expiry), requestable
      entitlements, and role memberships.
    - ``subject='resource'`` (*name* is a resource name): everyone who can
      access it and everyone who could request it.
    - ``subject='role'`` (*name* is a role name): what the role grants.

    Read-only; safe to run freely.
    """
    logger.debug("sdm_audit_access subject=%s name=%r", subject, name)
    try:
        client = _get_client()
        if subject == "user":
            account, err = _resolve_account(client, name)
            if err:
                return err
            granted = _bounded(
                client.granted_account_entitlements.list(account.id, ""), limit
            )
            requestable = _bounded(
                client.requestable_account_entitlements.list(account.id, ""), limit
            )
            attachments = _bounded(
                client.account_attachments.list("account_id:?", account.id), limit
            )
            roles = []
            for att in attachments:
                try:
                    roles.append(_to_dict(client.roles.get(att.role_id).role))
                except Exception:
                    roles.append({"id": att.role_id})
            return {
                "account": _to_dict(account),
                "granted_entitlements": [_to_dict(g) for g in granted],
                "requestable_entitlements": [_to_dict(r) for r in requestable],
                "roles": roles,
            }
        if subject == "resource":
            resource, err = _resolve_resource(client, name)
            if err:
                return err
            granted = _bounded(
                client.granted_resource_entitlements.list(resource.id, ""), limit
            )
            requestable = _bounded(
                client.requestable_resource_entitlements.list(resource.id, ""),
                limit,
            )
            return {
                "resource": {
                    "id": resource.id,
                    "name": resource.name,
                    "type": type(resource).__name__,
                },
                "granted_entitlements": [_to_dict(g) for g in granted],
                "requestable_entitlements": [_to_dict(r) for r in requestable],
            }
        if subject == "role":
            role, err = _resolve_role(client, name)
            if err:
                return err
            granted = _bounded(
                client.granted_role_entitlements.list(role.id, ""), limit
            )
            members = _bounded(
                client.account_attachments.list("role_id:?", role.id), limit
            )
            return {
                "role": _to_dict(role),
                "granted_entitlements": [_to_dict(g) for g in granted],
                "member_account_ids": [m.account_id for m in members],
            }
        raise ValueError(f"Unknown subject: {subject}; use user, resource or role")
    except Exception as exc:
        logger.error("sdm_audit_access failed: %s", exc)
        return {"error": _error_text(exc)}


# --------------------------------------------------------------------------- #
# Access grants (the accessbot pattern)                                       #
# --------------------------------------------------------------------------- #


def sdm_grant_access(
    user_email: str,
    resource_name: str = "",
    duration_hours: float | None = None,
    role_name: str = "",
    confirm: bool = False,
    comment: str = "",
) -> dict:
    """Grant a user access to a resource (optionally time-boxed) or a role.

    Compound flow: resolve the account by email and the resource (or role)
    by name; ambiguous matches return candidates and change nothing. Then:

    - resource + ``duration_hours`` -> just-in-time ``AccountGrant`` that
      expires automatically (``valid_until``); omit ``duration_hours`` for
      a standing grant.
    - ``role_name`` -> attach the account to the role instead (grants
      everything the role's access rules cover).

    Requires ``confirm=True`` and a non-empty audit ``comment``;
    ``confirm=False`` returns a preview without mutating anything. The
    result includes a ``verification`` read-back of the created object.
    """
    logger.debug(
        "sdm_grant_access user=%r resource=%r role=%r hours=%s",
        user_email,
        resource_name,
        role_name,
        duration_hours,
    )
    try:
        client = _get_client()  # raises the guidance error before the import can
        import strongdm  # noqa: PLC0415 - optional dependency

        if bool(resource_name) == bool(role_name):
            raise ValueError("Provide exactly one of resource_name or role_name")
        account, err = _resolve_account(client, user_email)
        if err:
            return err

        if role_name:
            role, err = _resolve_role(client, role_name)
            if err:
                return err
            gate = _require_confirmation(
                confirm,
                comment,
                {
                    "action": "attach role",
                    "account": account.email,
                    "role": role.name,
                },
            )
            if gate:
                return gate
            attachment = strongdm.AccountAttachment(
                account_id=account.id, role_id=role.id
            )
            created = client.account_attachments.create(attachment)
            verification = client.account_attachments.get(created.account_attachment.id)
            return {
                "result": _to_dict(created.account_attachment),
                "verification": _to_dict(verification.account_attachment),
                "comment": comment,
            }

        resource, err = _resolve_resource(client, resource_name)
        if err:
            return err
        valid_until = None
        if duration_hours is not None:
            valid_until = datetime.datetime.now(
                datetime.timezone.utc
            ) + datetime.timedelta(hours=float(duration_hours))
        gate = _require_confirmation(
            confirm,
            comment,
            {
                "action": "create account grant",
                "account": account.email,
                "resource": resource.name,
                "expires": valid_until.isoformat() if valid_until else "never",
            },
        )
        if gate:
            return gate
        grant = strongdm.AccountGrant(
            account_id=account.id,
            resource_id=resource.id,
            valid_until=valid_until,
        )
        created = client.account_grants.create(grant)
        verification = client.account_grants.get(created.account_grant.id)
        return {
            "result": _to_dict(created.account_grant),
            "verification": _to_dict(verification.account_grant),
            "comment": comment,
        }
    except Exception as exc:
        logger.error("sdm_grant_access failed: %s", exc)
        return {"error": _error_text(exc)}


def sdm_revoke_access(
    user_email: str,
    resource_name: str,
    confirm: bool = False,
    comment: str = "",
) -> dict:
    """Revoke a user's direct grants on a resource, reporting role-derived
    access that a grant deletion cannot remove.

    Compound flow: resolve account and resource, find every direct
    ``AccountGrant`` linking them, delete each. Access that arrives through
    a role attachment is reported (with the role id) instead of silently
    surviving — detach the role via ``sdm_role_management`` if that is the
    actual intent.

    Requires ``confirm=True`` + non-empty ``comment``; ``confirm=False``
    previews what would be deleted.
    """
    logger.debug("sdm_revoke_access user=%r resource=%r", user_email, resource_name)
    try:
        client = _get_client()
        account, err = _resolve_account(client, user_email)
        if err:
            return err
        resource, err = _resolve_resource(client, resource_name)
        if err:
            return err
        grants = [
            g
            for g in _bounded(
                client.account_grants.list("account_id:?", account.id), _LIST_CAP
            )
            if g.resource_id == resource.id
        ]
        role_paths = [
            _to_dict(ar)
            for ar in _bounded(
                client.account_resources.list("account_id:?", account.id), _LIST_CAP
            )
            if ar.resource_id == resource.id and ar.role_id
        ]
        gate = _require_confirmation(
            confirm,
            comment,
            {
                "action": "delete account grants",
                "account": account.email,
                "resource": resource.name,
                "grants_to_delete": [_to_dict(g) for g in grants],
                "role_derived_access": role_paths,
            },
        )
        if gate:
            return gate
        if not grants and not role_paths:
            return {
                "error": f"{account.email} has no access to {resource.name}",
            }
        deleted = []
        for grant in grants:
            client.account_grants.delete(grant.id)
            deleted.append(grant.id)
        remaining = [
            g
            for g in _bounded(
                client.account_grants.list("account_id:?", account.id), _LIST_CAP
            )
            if g.resource_id == resource.id
        ]
        return {
            "result": {"deleted_grant_ids": deleted},
            "verification": {"remaining_direct_grants": len(remaining)},
            "role_derived_access": role_paths,
            "note": (
                "Role-derived access survives grant deletion; detach the role "
                "via sdm_role_management to remove it."
                if role_paths
                else None
            ),
            "comment": comment,
        }
    except Exception as exc:
        logger.error("sdm_revoke_access failed: %s", exc)
        return {"error": _error_text(exc)}


# --------------------------------------------------------------------------- #
# Users & roles                                                               #
# --------------------------------------------------------------------------- #


def sdm_user_management(
    action: str,
    email: str = "",
    data: dict | str | None = None,
    roles: list[str] | None = None,
    confirm: bool = False,
    comment: str = "",
    limit: int = 50,
) -> dict:
    """Manage StrongDM user accounts.

    Actions
    -------
    - ``get`` / ``list``: read-only (``list`` honours ``data['filter']``).
    - ``create``: needs ``data`` with ``first_name``, ``last_name`` (and
      optionally ``permission_level``); *email* is the new user's email.
    - ``onboard``: ``create`` plus attach every role named in ``roles`` —
      the whole new-engineer flow in one call.
    - ``suspend`` / ``reactivate``: toggle sign-in.
    - ``offboard``: suspend and enumerate the standing grants and role
      attachments that remain for review.
    - ``delete``: permanent removal.

    ``create``/``onboard``/``suspend``/``reactivate``/``offboard``/``delete``
    require ``confirm=True`` + non-empty ``comment``; previews otherwise.
    """
    logger.debug("sdm_user_management action=%s email=%r", action, email)
    try:
        import json as _json

        client = _get_client()
        if isinstance(data, str):
            data = _json.loads(data) if data else None
        data = data or {}

        if action == "list":
            items = _bounded(client.accounts.list(data.get("filter", "")), limit)
            return {"results": [_to_dict(a) for a in items], "count": len(items)}
        if action == "get":
            account, err = _resolve_account(client, email)
            return err if err else {"result": _to_dict(account)}

        if action in {"create", "onboard"}:
            import strongdm  # noqa: PLC0415 - optional dependency

            gate = _require_confirmation(
                confirm,
                comment,
                {"action": action, "email": email, "data": data, "roles": roles},
            )
            if gate:
                return gate
            user = strongdm.User(
                email=email,
                first_name=data.get("first_name", ""),
                last_name=data.get("last_name", ""),
                permission_level=data.get("permission_level", ""),
            )
            created = client.accounts.create(user).account
            attached = []
            for role_name in roles or []:
                role, err = _resolve_role(client, role_name)
                if err:
                    attached.append({"role": role_name, "error": err["error"]})
                    continue
                att = client.account_attachments.create(
                    strongdm.AccountAttachment(account_id=created.id, role_id=role.id)
                )
                attached.append(_to_dict(att.account_attachment))
            verification = client.accounts.get(created.id)
            return {
                "result": _to_dict(created),
                "attached_roles": attached,
                "verification": _to_dict(verification.account),
                "comment": comment,
            }

        # Remaining actions operate on an existing account.
        account, err = _resolve_account(client, email)
        if err:
            return err

        if action in {"suspend", "reactivate", "offboard"}:
            gate = _require_confirmation(
                confirm, comment, {"action": action, "email": account.email}
            )
            if gate:
                return gate
            account.suspended = action != "reactivate"
            updated = client.accounts.update(account).account
            result: dict[str, Any] = {
                "result": _to_dict(updated),
                "verification": _to_dict(client.accounts.get(account.id).account),
                "comment": comment,
            }
            if action == "offboard":
                result["standing_grants"] = [
                    _to_dict(g)
                    for g in _bounded(
                        client.account_grants.list("account_id:?", account.id),
                        _LIST_CAP,
                    )
                ]
                result["role_attachments"] = [
                    _to_dict(a)
                    for a in _bounded(
                        client.account_attachments.list("account_id:?", account.id),
                        _LIST_CAP,
                    )
                ]
                result["note"] = (
                    "Account suspended. Review standing_grants/role_attachments "
                    "and remove them via sdm_revoke_access/sdm_role_management."
                )
            return result

        if action == "delete":
            gate = _require_confirmation(
                confirm,
                comment,
                {"action": "delete", "email": account.email, "id": account.id},
            )
            if gate:
                return gate
            client.accounts.delete(account.id)
            remaining = _bounded(client.accounts.list("email:?", account.email), 5)
            return {
                "result": {"deleted": account.id},
                "verification": {"still_exists": bool(remaining)},
                "comment": comment,
            }

        raise ValueError(f"Unknown action: {action}")
    except Exception as exc:
        logger.error("sdm_user_management failed: %s", exc)
        return {"error": _error_text(exc)}


def sdm_role_management(
    action: str,
    role_name: str = "",
    user_email: str = "",
    confirm: bool = False,
    comment: str = "",
    limit: int = 50,
) -> dict:
    """Manage StrongDM roles and their members.

    Actions
    -------
    - ``list`` / ``get`` / ``list_members``: read-only.
    - ``create`` / ``delete``: role lifecycle.
    - ``add_user`` / ``remove_user``: attach/detach *user_email*.

    Mutating actions require ``confirm=True`` + non-empty ``comment``.
    """
    logger.debug("sdm_role_management action=%s role=%r", action, role_name)
    try:
        client = _get_client()
        if action == "list":
            items = _bounded(client.roles.list(""), limit)
            return {"results": [_to_dict(r) for r in items], "count": len(items)}

        if action == "create":
            import strongdm  # noqa: PLC0415 - optional dependency

            gate = _require_confirmation(
                confirm, comment, {"action": "create role", "name": role_name}
            )
            if gate:
                return gate
            created = client.roles.create(strongdm.Role(name=role_name)).role
            return {
                "result": _to_dict(created),
                "verification": _to_dict(client.roles.get(created.id).role),
                "comment": comment,
            }

        role, err = _resolve_role(client, role_name)
        if err:
            return err

        if action == "get":
            return {"result": _to_dict(role)}
        if action == "list_members":
            attachments = _bounded(
                client.account_attachments.list("role_id:?", role.id), limit
            )
            members = []
            for att in attachments:
                try:
                    members.append(
                        _to_dict(client.accounts.get(att.account_id).account)
                    )
                except Exception:
                    members.append({"id": att.account_id})
            return {"role": role.name, "members": members, "count": len(members)}

        if action == "delete":
            gate = _require_confirmation(
                confirm,
                comment,
                {"action": "delete role", "name": role.name, "id": role.id},
            )
            if gate:
                return gate
            client.roles.delete(role.id)
            remaining = _bounded(client.roles.list("name:?", role.name), 5)
            return {
                "result": {"deleted": role.id},
                "verification": {"still_exists": bool(remaining)},
                "comment": comment,
            }

        if action in {"add_user", "remove_user"}:
            import strongdm  # noqa: PLC0415 - optional dependency

            account, err = _resolve_account(client, user_email)
            if err:
                return err
            gate = _require_confirmation(
                confirm,
                comment,
                {"action": action, "role": role.name, "account": account.email},
            )
            if gate:
                return gate
            if action == "add_user":
                created = client.account_attachments.create(
                    strongdm.AccountAttachment(account_id=account.id, role_id=role.id)
                )
                return {
                    "result": _to_dict(created.account_attachment),
                    "verification": _to_dict(
                        client.account_attachments.get(
                            created.account_attachment.id
                        ).account_attachment
                    ),
                    "comment": comment,
                }
            attachments = [
                a
                for a in _bounded(
                    client.account_attachments.list("role_id:?", role.id),
                    _LIST_CAP,
                )
                if a.account_id == account.id
            ]
            if not attachments:
                return {"error": f"{account.email} is not attached to {role.name}"}
            for att in attachments:
                client.account_attachments.delete(att.id)
            return {
                "result": {"detached": [a.id for a in attachments]},
                "verification": {
                    "still_attached": bool(
                        [
                            a
                            for a in _bounded(
                                client.account_attachments.list("role_id:?", role.id),
                                _LIST_CAP,
                            )
                            if a.account_id == account.id
                        ]
                    )
                },
                "comment": comment,
            }

        raise ValueError(f"Unknown action: {action}")
    except Exception as exc:
        logger.error("sdm_role_management failed: %s", exc)
        return {"error": _error_text(exc)}


# --------------------------------------------------------------------------- #
# Operations: health, requests, activity                                      #
# --------------------------------------------------------------------------- #


def sdm_resource_health(resource_name: str, limit: int = 50) -> dict:
    """Check a resource's health across every node that serves it.

    Compound flow: resolve the resource, trigger an immediate healthcheck,
    then collect the per-node results and summarise unhealthy paths.
    """
    logger.debug("sdm_resource_health resource=%r", resource_name)
    try:
        client = _get_client()
        resource, err = _resolve_resource(client, resource_name)
        if err:
            return err
        client.resources.healthcheck(resource.id)
        checks = _bounded(client.health_checks.list("resourceid:?", resource.id), limit)
        unhealthy = [c for c in checks if not c.healthy]
        return {
            "resource": {
                "id": resource.id,
                "name": resource.name,
                "type": type(resource).__name__,
            },
            "healthy_nodes": len(checks) - len(unhealthy),
            "unhealthy_nodes": len(unhealthy),
            "checks": [_to_dict(c) for c in checks],
            "note": "Healthcheck triggered; listed results may take a moment "
            "to reflect it. Re-run to see the fresh status.",
        }
    except Exception as exc:
        logger.error("sdm_resource_health failed: %s", exc)
        return {"error": _error_text(exc)}


def sdm_access_requests(
    action: str = "list", request_id: str = "", limit: int = 50
) -> dict:
    """Inspect StrongDM access requests (approval is NOT possible here).

    Actions: ``list`` (pending and recent requests) or ``status`` (one
    request by id).

    The SDM admin API can list access requests but cannot approve, deny,
    or submit them — approvers act in the Admin UI or the Slack/Teams/Jira
    integrations. To unblock someone directly, create a time-boxed grant
    with ``sdm_grant_access`` matching the request's account/resource.
    """
    logger.debug("sdm_access_requests action=%s id=%r", action, request_id)
    try:
        client = _get_client()
        if action == "list":
            items = _bounded(client.access_requests.list(""), limit)
            return {
                "results": [_to_dict(r) for r in items],
                "count": len(items),
                "note": "Approve/deny is not available via the admin API; use "
                "the Admin UI / chat integrations, or grant directly with "
                "sdm_grant_access (time-boxed).",
            }
        if action == "status":
            items = _bounded(client.access_requests.list("id:?", request_id), 5)
            if not items:
                return {"error": f"No access request with id '{request_id}'"}
            return {"result": _to_dict(items[0])}
        raise ValueError(f"Unknown action: {action}")
    except Exception as exc:
        logger.error("sdm_access_requests failed: %s", exc)
        return {"error": _error_text(exc)}


def sdm_activity_report(
    user_email: str = "",
    resource_name: str = "",
    since: str = "",
    limit: int = 100,
) -> dict:
    """Audit recent StrongDM activity: client queries and admin actions.

    Compound flow: optionally scope to a user (by email) and/or resource
    (by name), fetch the query log (SQL/command bodies, durations, record
    counts, whether a session replay exists) plus the admin activity log,
    and summarise. ``since`` is an ISO date/datetime lower bound applied
    client-side.

    Read-only. Sessions flagged ``replayable`` can be replayed from the
    Admin UI.
    """
    logger.debug(
        "sdm_activity_report user=%r resource=%r since=%r",
        user_email,
        resource_name,
        since,
    )
    try:
        client = _get_client()
        filters = []
        args: list[str] = []
        if user_email:
            account, err = _resolve_account(client, user_email)
            if err:
                return err
            filters.append("account_id:?")
            args.append(account.id)
        if resource_name:
            resource, err = _resolve_resource(client, resource_name)
            if err:
                return err
            filters.append("resource_id:?")
            args.append(resource.id)
        queries = _bounded(client.queries.list(" ".join(filters), *args), limit)
        cutoff = None
        if since:
            cutoff = datetime.datetime.fromisoformat(since)
            if cutoff.tzinfo is None:
                cutoff = cutoff.replace(tzinfo=datetime.timezone.utc)
            queries = [q for q in queries if q.timestamp and q.timestamp >= cutoff]
        activities = _bounded(client.activities.list(""), limit)
        if cutoff:
            activities = [
                a
                for a in activities
                if getattr(a, "completed_at", None) and a.completed_at >= cutoff
            ]
        return {
            "queries": [_to_dict(q) for q in queries],
            "replayable_sessions": [q.id for q in queries if q.replayable],
            "admin_activities": [_to_dict(a) for a in activities],
            "counts": {"queries": len(queries), "activities": len(activities)},
        }
    except Exception as exc:
        logger.error("sdm_activity_report failed: %s", exc)
        return {"error": _error_text(exc)}


def sdm_network_status(limit: int = 200) -> dict:
    """Summarise the StrongDM node fleet (gateways/relays) by state.

    Read-only: lists nodes and groups them by type and state so dead or
    stopped gateways stand out.
    """
    logger.debug("sdm_network_status")
    try:
        client = _get_client()
        nodes = _bounded(client.nodes.list(""), limit)
        summary: dict[str, dict[str, int]] = {}
        for node in nodes:
            kind = type(node).__name__
            state = getattr(node, "state", "unknown") or "unknown"
            summary.setdefault(kind, {}).setdefault(state, 0)
            summary[kind][state] += 1
        problem_nodes = [
            _to_dict(n) for n in nodes if getattr(n, "state", "") not in ("started", "")
        ]
        return {
            "summary": summary,
            "problem_nodes": problem_nodes,
            "count": len(nodes),
        }
    except Exception as exc:
        logger.error("sdm_network_status failed: %s", exc)
        return {"error": _error_text(exc)}


TOOLS = [
    ("sdm_search", sdm_search),
    ("sdm_audit_access", sdm_audit_access),
    ("sdm_grant_access", sdm_grant_access),
    ("sdm_revoke_access", sdm_revoke_access),
    ("sdm_user_management", sdm_user_management),
    ("sdm_role_management", sdm_role_management),
    ("sdm_resource_health", sdm_resource_health),
    ("sdm_access_requests", sdm_access_requests),
    ("sdm_activity_report", sdm_activity_report),
    ("sdm_network_status", sdm_network_status),
]


def register(mcp: Any, enabled: Iterable[str] | None = None) -> None:
    """Register StrongDM tools on an MCP server.

    Honours the same ``enabled_tools`` allowlist semantics as
    :func:`delinea_mcp.tools.register`: an empty/missing set registers
    every tool in this module; a non-empty set registers only named tools.
    Tools register even when the SDK/credentials are absent — they return
    a guidance error explaining how to enable StrongDM support.
    """
    enabled_set = set(enabled or [])
    if not enabled_set:
        enabled_set = {name for name, _ in TOOLS}
    for name, func in TOOLS:
        if name in enabled_set:
            mcp.tool(annotations=TOOL_ANNOTATIONS.get(name))(func)
