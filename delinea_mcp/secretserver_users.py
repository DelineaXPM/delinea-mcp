"""Legacy Secret Server local user/search tooling.

Modern Delinea cloud deployments authenticate users through the Delinea
Platform identity provider. The tools in this module talk directly to
Secret Server's own ``/v1/users`` endpoints, which only manage the
*local* user records inside Secret Server.

For Platform-integrated tenants, use the Platform user tools in
:mod:`delinea_mcp.user_platform_tools` (``search_users``,
``get_platform_user``, ...) instead.

These functions are preserved under the ``secretserver_local_*`` names for
SS-only on-prem deployments and as a fallback during migration.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from delinea_mcp.annotations import tool_metadata
from delinea_mcp.api import mask_fields, sensitive_values
from delinea_mcp.tool_guard import guard_tool

from .session import SessionManager

logger = logging.getLogger(__name__)


def _parse_json_data(data: dict | str | None) -> dict | None:
    import json as _json

    if isinstance(data, str):
        try:
            return _json.loads(data)
        except Exception as exc:
            logger.exception("Failed to parse JSON string")
            raise ValueError("Invalid JSON data") from exc
    return data


def search_secretserver_local_users(query: str) -> dict:
    """Search local Secret Server users (legacy SS-only deployments).

    Calls ``GET /v1/users?filter.searchText=<query>``. In Platform-integrated
    tenants the Platform identity directory is the authoritative user store;
    ``search_users`` searches it.

    Parameters
    ----------
    query:
        Text to search for in usernames or display names.

    Returns
    -------
    dict
        Raw search results as returned by the API.
    """
    logger.debug("search_secretserver_local_users(%s)", query)
    session = SessionManager.get()
    try:
        return session.request(
            "GET", "/v1/users", params={"filter.searchText": query}
        ).json()
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to search local SS users %s", query)
        return {"error": f"Failed to search users '{query}': {exc}"}


def secretserver_local_user_management(
    action: str,
    user_id: int | None = None,
    data: dict | None = None,
    *,
    skip: int = 0,
    take: int = 20,
    is_exporting: bool = False,
) -> dict:
    """Manage local Secret Server users (legacy SS-only deployments).

    For Platform-integrated tenants the authoritative user store is the
    Platform identity directory; use the Platform user tools in
    :mod:`delinea_mcp.user_platform_tools` instead. Not registered as a tool
    (it mixes reads and writes); the ``*secretserver_local_user*`` tools
    call it.

    This function operates on Secret Server's own ``/v1/users`` records,
    which in Platform tenants are typically read-only mirrors of Platform
    users.  Mutations performed here will not propagate to the Platform.

    Parameters
    ----------
    action:
        Operation to perform: ``"get"``, ``"create"``, ``"update"``,
        ``"delete"``, ``"list_sessions"``, ``"reset_2fa"``,
        ``"reset_password"`` or ``"lock_out"``.
    user_id:
        Target user identifier. Required for all actions except ``"create"``
        and ``"list_sessions"``.
    data:
        JSON body for ``"create"``, ``"update"`` and ``"reset_password"``.
    skip, take:
        Pagination controls for ``"list_sessions"``.
    is_exporting:
        Include the ``isExporting`` flag when listing sessions.

    Returns
    -------
    dict
        Dictionary with ``result`` from the write action and ``verification``
        from the subsequent ``GET``, or the raw API payload for read actions.
    """

    logger.debug(
        "secretserver_local_user_management(action=%s, user_id=%s, data=%s)",
        action,
        user_id,
        mask_fields(data),  # create and reset_password carry passwords
    )
    session = SessionManager.get()

    data = _parse_json_data(data)
    # Passwords in create/update/reset_password data are masked in API errors.
    masked: dict[str, Any] = {}
    if secrets := sensitive_values(data):
        masked["sensitive"] = secrets

    try:
        if action == "get":
            if user_id is None:
                raise ValueError("user_id required for get")
            return session.request("GET", f"/v1/users/{user_id}").json()
        if action == "create":
            result = session.request(
                "POST", "/v1/users", json=data or {}, **masked
            ).json()
            user_id = result.get("id") or result.get("userId")
            verify: dict[str, Any] = {}
            if user_id is not None:
                try:
                    verify = session.request("GET", f"/v1/users/{user_id}").json()
                except Exception as exc:  # pragma: no cover - network failures
                    logger.exception("User verification failed after create")
                    verify = {"error": str(exc)}
            return {"result": result, "verification": verify}
        if action == "update":
            if user_id is None or data is None:
                raise ValueError("user_id and data required for update")
            result = session.request(
                "PUT", f"/v1/users/{user_id}", json=data, **masked
            ).json()
            verify = {}
            try:
                verify = session.request("GET", f"/v1/users/{user_id}").json()
            except Exception as exc:  # pragma: no cover - network failures
                logger.exception("User verification failed after update")
                verify = {"error": str(exc)}
            return {"result": result, "verification": verify}
        if action == "delete":
            if user_id is None:
                raise ValueError("user_id required for delete")
            result = session.request("DELETE", f"/v1/users/{user_id}").json()
            verify = {}
            try:
                verify = session.request("GET", f"/v1/users/{user_id}").json()
            except Exception as exc:  # pragma: no cover - network failures
                verify = {"error": str(exc)}
            return {"result": result, "verification": verify}
        if action == "list_sessions":
            params: dict[str, Any] = {"skip": skip, "take": take}
            if is_exporting:
                params["isExporting"] = True
            return session.request("GET", "/v1/users/sessions", params=params).json()
        if action == "reset_2fa":
            if user_id is None:
                raise ValueError("user_id required for reset_2fa")
            return session.request(
                "POST", f"/v1/users/{user_id}/reset-two-factor", json=data or {}
            ).json()
        if action == "reset_password":
            if user_id is None or data is None:
                raise ValueError("user_id and data required for reset_password")
            return session.request(
                "POST", f"/v1/users/{user_id}/password-reset", json=data, **masked
            ).json()
        if action == "lock_out":
            if user_id is None:
                raise ValueError("user_id required for lock_out")
            return session.request(
                "POST", f"/v1/users/{user_id}/lock-out", json=data or {}
            ).json()
        raise ValueError(f"Unknown action: {action}")
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Local SS user management action failed")
        return {"error": str(exc)}


# secretserver_local_user_management is not registered: it mixes reads and
# writes, which the Claude directory rejects. These tools split it.


def get_secretserver_local_user(user_id: int) -> dict:
    """Get one local Secret Server user by ID (legacy SS-only deployments).

    Calls ``GET /api/v1/users/{id}``. In Platform-integrated tenants use
    ``get_platform_user``. Secret Server REST API reference:
    https://docs.delinea.com/online-help/secret-server/api-scripting/rest-api/rest-api-reference-download/index.htm
    """
    return secretserver_local_user_management("get", user_id)


def list_secretserver_user_sessions(
    skip: int = 0, take: int = 20, is_exporting: bool = False
) -> dict:
    """List active Secret Server user sessions.

    Calls ``GET /api/v1/users/sessions`` paged by *skip* and *take*.
    Secret Server REST API reference:
    https://docs.delinea.com/online-help/secret-server/api-scripting/rest-api/rest-api-reference-download/index.htm
    """
    return secretserver_local_user_management(
        "list_sessions", skip=skip, take=take, is_exporting=is_exporting
    )


def create_or_update_secretserver_local_user(
    data: dict, user_id: int | None = None
) -> dict:
    """Create a local Secret Server user, or update one when *user_id* is given.

    Create calls ``POST /api/v1/users``; update calls ``PUT
    /api/v1/users/{id}`` with the full user (read it first with
    ``get_secretserver_local_user``). Passwords in *data* are masked in
    errors and logs. In Platform tenants these records mirror Platform users
    and changes here don't reach the Platform. Returns ``{"result": ...,
    "verification": ...}``. Secret Server REST API reference:
    https://docs.delinea.com/online-help/secret-server/api-scripting/rest-api/rest-api-reference-download/index.htm
    """
    if user_id is None:
        return secretserver_local_user_management("create", data=data)
    return secretserver_local_user_management("update", user_id, data)


def delete_secretserver_local_user(user_id: int) -> dict:
    """Delete a local Secret Server user.

    Calls ``DELETE /api/v1/users/{id}``, then reads the user back as
    verification. Secret Server REST API reference:
    https://docs.delinea.com/online-help/secret-server/api-scripting/rest-api/rest-api-reference-download/index.htm
    """
    return secretserver_local_user_management("delete", user_id)


_SECURITY_ACTIONS = ("reset_2fa", "reset_password", "lock_out")


def secretserver_local_user_security_action(
    action: str, user_id: int, data: dict | None = None
) -> dict:
    """Reset two-factor, reset the password of, or lock out a local Secret Server user.

    *action* is one of:

    * ``"reset_2fa"``: ``POST /api/v1/users/{id}/reset-two-factor``.
    * ``"reset_password"``: ``POST /api/v1/users/{id}/password-reset``;
      *data* carries the new password (masked in errors and logs).
    * ``"lock_out"``: ``POST /api/v1/users/{id}/lock-out``.

    Secret Server REST API reference:
    https://docs.delinea.com/online-help/secret-server/api-scripting/rest-api/rest-api-reference-download/index.htm
    """
    if action not in _SECURITY_ACTIONS:
        return {
            "error": f"Unknown action {action!r}; use one of {list(_SECURITY_ACTIONS)}"
        }
    return secretserver_local_user_management(action, user_id, data)


TOOLS = [
    ("search_secretserver_local_users", search_secretserver_local_users),
    ("get_secretserver_local_user", get_secretserver_local_user),
    ("list_secretserver_user_sessions", list_secretserver_user_sessions),
    (
        "create_or_update_secretserver_local_user",
        create_or_update_secretserver_local_user,
    ),
    ("delete_secretserver_local_user", delete_secretserver_local_user),
    (
        "secretserver_local_user_security_action",
        secretserver_local_user_security_action,
    ),
]


def register(mcp: Any, enabled: Iterable[str] | None = None) -> None:
    """Register the legacy SS-local user tools on an MCP server.

    Honours the same ``enabled_tools`` allowlist semantics as
    :func:`delinea_mcp.tools.register`: an empty/missing set registers
    every tool in this module; a non-empty set registers only named tools.
    """
    enabled_set = set(enabled or [])
    if not enabled_set:
        enabled_set = {name for name, _ in TOOLS}
    for name, func in TOOLS:
        if name in enabled_set:
            mcp.tool(**tool_metadata(name))(guard_tool(func))
