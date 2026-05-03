"""Delinea Platform identity-API tooling.

Modern Delinea cloud deployments authenticate users via the Delinea
Platform identity provider.  This module exposes the canonical user,
role, and search tools that operate against the Platform's identity
endpoints (``/identity/...``).

In v1.0.0 the canonical names ``user_management`` and ``search_users``
were promoted from this module.  The previous Secret-Server-local
implementations are preserved under
:mod:`delinea_mcp.secretserver_users` as ``secretserver_local_*`` for
SS-only on-prem deployments.

Endpoint references
-------------------

* ``POST /identity/CDirectoryService/CreateUser`` — create user
* ``POST /identity/CDirectoryService/ChangeUser`` — update user
* ``GET  /identity/UserMgmt/GetUser?userId=<id>`` — get user
* ``POST /identity/UserMgmt/RemoveUsers`` body ``{"Users":[id]}`` — delete
* ``POST /identity/api/Report/RunReport`` — search via canned reports
* ``POST /identity/SaasManage/StoreRole`` — create role
  (https://developer.delinea.com/docs/manage-rolesnew)
* ``POST /identity/Roles/UpdateRole`` — update role + add/remove members
* ``POST /identity/Redrock/Query`` — generic SQL-like query for users,
  roles, groups
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)


def _parse_json_data(data: dict | str | None) -> dict | None:
    if isinstance(data, str):
        try:
            return json.loads(data)
        except Exception:
            logger.exception("Failed to parse JSON string")
            raise ValueError("Invalid JSON data")
    return data


def _json_or_error(response: requests.Response) -> dict:
    try:
        return response.json()
    except Exception:
        return {"error": response.text}


platform_hostname = os.getenv("PLATFORM_HOSTNAME")
platform_service_account = os.getenv("PLATFORM_SERVICE_ACCOUNT")
platform_service_password = os.getenv("PLATFORM_SERVICE_PASSWORD")
platform_tenant_id = os.getenv("PLATFORM_TENANT_ID")

# Default request timeout for all Platform API calls.  Override per-process
# with the ``PLATFORM_TIMEOUT`` environment variable.  Without this the
# requests library blocks indefinitely on a hung TCP connection — bad for
# both interactive sessions and CI.
_DEFAULT_TIMEOUT = float(os.getenv("PLATFORM_TIMEOUT", "30"))


def configure(
    hostname: str | None = None,
    service_account: str | None = None,
    service_password: str | None = None,
    tenant_id: str | None = None,
) -> None:
    """Override platform connection settings."""
    global platform_hostname, platform_service_account, platform_service_password, platform_tenant_id
    if hostname is not None:
        platform_hostname = hostname
    if service_account is not None:
        platform_service_account = service_account
    if service_password is not None:
        platform_service_password = service_password
    if tenant_id is not None:
        platform_tenant_id = tenant_id
    # Invalidate cached headers so re-configuration takes effect.
    global _headers
    _headers = None


_headers: dict[str, str] | None = None


def _platform_configured() -> bool:
    return bool(
        platform_hostname and platform_service_account and platform_service_password
    )


_NOT_CONFIGURED_ERROR = (
    "Platform is not configured. This tool requires PLATFORM_HOSTNAME, "
    "PLATFORM_SERVICE_ACCOUNT, PLATFORM_SERVICE_PASSWORD (and typically "
    "PLATFORM_TENANT_ID) to be set, or the equivalent keys in config.json. "
    "For SS-only deployments, use secretserver_local_user_management / "
    "search_secretserver_local_users instead."
)


def _build_headers() -> dict[str, str]:
    """Return cached headers or fetch a new OAuth token using ``requests``."""
    global _headers
    if _headers:
        return _headers

    if not _platform_configured():
        raise RuntimeError(_NOT_CONFIGURED_ERROR)

    url = f"https://{platform_hostname}/identity/api/oauth2/token/xpmplatform"
    data = {
        "grant_type": "client_credentials",
        "scope": "xpmheadless",
        "client_id": platform_service_account,
        "client_secret": platform_service_password,
    }
    try:
        response = requests.post(
            url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=_DEFAULT_TIMEOUT,
        )
    except Exception as exc:
        logger.error("Failed to get token: %s", exc)
        raise RuntimeError(f"Failed to get token: {exc}")

    if response.status_code >= 400:
        logger.error("Failed to get token: %s", response.text)
        raise RuntimeError(f"Failed to get token: {response.text}")

    token_data = response.json()
    access_token = token_data["access_token"]
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    if platform_tenant_id:
        headers["X-MT-SecondaryId"] = f"{platform_tenant_id}"
    _headers = headers
    return _headers


def _platform_url(path: str) -> str:
    return f"https://{platform_hostname}/identity{path}"


# --------------------------------------------------------------------------- #
# Users (canonical user_management / search_users)                            #
# --------------------------------------------------------------------------- #


def search_users(query: str) -> dict:
    """Search the Platform identity directory for users.

    Calls ``POST /identity/api/Report/RunReport`` with the
    ``user_searchbyname`` canned report.  Returns the raw report payload.

    For SS-only deployments without Platform configured, use
    :func:`delinea_mcp.secretserver_users.search_secretserver_local_users`.

    Parameters
    ----------
    query:
        Text to search for in usernames.

    Returns
    -------
    dict
        JSON response from the platform user search report or
        ``{"error": ...}``.
    """

    if not query:
        return {"error": "query required"}
    try:
        headers = _build_headers()
    except RuntimeError as exc:
        return {"error": str(exc)}

    url = _platform_url("/api/Report/RunReport")
    payload = {
        "ID": "user_searchbyname",
        "Args": {
            "PageNumber": 1,
            "PageSize": 60,
            "Limit": 100000,
            "FilterQuery": None,
            "Caching": 0,
            "Ascending": True,
            "SortBy": "Username",
            "Parameters": [
                {
                    "Name": "searchString",
                    "Value": f"%{query}%",
                    "Label": "searchString",
                    "Type": "string",
                    "ColumnType": 12,
                },
                {
                    "Name": "orderby",
                    "Value": "Username",
                    "Label": "orderby",
                    "Type": "string",
                    "ColumnType": 12,
                },
            ],
        },
    }
    try:
        response = requests.post(
            url, headers=headers, json=payload, timeout=_DEFAULT_TIMEOUT
        )
    except Exception as exc:
        logger.exception("Failed to search platform users")
        return {"error": str(exc)}
    return _json_or_error(response)


# Back-compat alias used by tests and older callers.
def search_platform_user(username: str) -> dict:
    """Alias for :func:`search_users`. Retained for back-compat."""
    return search_users(username)


def user_management(
    action: str,
    user_id: str | None = None,
    data: dict | str | None = None,
    username: str | None = None,
) -> dict:
    """Manage users on the Delinea Platform via a unified helper.

    This is the **canonical** ``user_management`` tool (v1.0.0+).  It
    talks to the Platform identity API, which is the authoritative user
    store in cloud-native and Platform-integrated tenants.

    For SS-only deployments without Platform configured, use
    :func:`delinea_mcp.secretserver_users.secretserver_local_user_management`.

    Parameters
    ----------
    action:
        One of ``"create"``, ``"delete"``, ``"update"``, ``"get"`` or
        ``"search"``.
    user_id:
        Identifier used with ``"update"``, ``"delete"`` and ``"get"``.
    data:
        JSON body for ``"create"`` and ``"update"``.
    username:
        Username parameter for ``"search"``.

    Returns
    -------
    dict
        Response payload or ``{"result": ..., "verification": ...}`` when
        a verifying lookup is performed.
    """

    logger.debug(
        "user_management(action=%s, user_id=%s, username=%s, data=%s)",
        action,
        user_id,
        username,
        data,
    )

    try:
        headers = _build_headers()
    except RuntimeError as exc:
        return {"error": str(exc)}

    payload = _parse_json_data(data)

    try:
        if action == "get":
            if not user_id:
                raise ValueError("user_id required for get")
            url = _platform_url("/UserMgmt/GetUser")
            response = requests.get(
                url,
                headers=headers,
                params={"userId": user_id},
                timeout=_DEFAULT_TIMEOUT,
            )
            return _json_or_error(response)

        if action == "create":
            if payload is None:
                raise ValueError("data required for create")
            url = _platform_url("/CDirectoryService/CreateUser")
            response = requests.post(
                url, json=payload, headers=headers, timeout=_DEFAULT_TIMEOUT
            )
            result = _json_or_error(response)
            verify = search_users(payload.get("Name") or payload.get("Username") or "")
            return {"result": result, "verification": verify}

        if action == "delete":
            if not user_id:
                raise ValueError("user_id required for delete")
            url = _platform_url("/UserMgmt/RemoveUsers")
            response = requests.post(
                url,
                json={"Users": [user_id]},
                headers=headers,
                timeout=_DEFAULT_TIMEOUT,
            )
            result = _json_or_error(response)
            verify = search_users(user_id)
            return {"result": result, "verification": verify}

        if action == "update":
            if not user_id or payload is None:
                raise ValueError("user_id and data required for update")
            payload.setdefault("ID", user_id)
            url = _platform_url("/CDirectoryService/ChangeUser")
            response = requests.post(
                url, json=payload, headers=headers, timeout=_DEFAULT_TIMEOUT
            )
            result = _json_or_error(response)
            verify = search_users(
                payload.get("Name") or payload.get("Username") or user_id
            )
            return {"result": result, "verification": verify}

        if action == "search":
            if username is None:
                raise ValueError("username required for search")
            return search_users(username)

        raise ValueError(f"Unknown action: {action}")

    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Platform user_management action failed")
        return {"error": str(exc)}


# Deprecated alias: keeps existing callers working but discouraged in v1+.
def platform_user_management(*args, **kwargs):
    """Deprecated alias for :func:`user_management`. Use ``user_management``.

    Retained for backwards compatibility with v0.x clients.  Will be
    removed in a future major release.
    """
    return user_management(*args, **kwargs)


# --------------------------------------------------------------------------- #
# Roles                                                                       #
# --------------------------------------------------------------------------- #


def platform_role_management(
    action: str,
    role_id: str | None = None,
    data: dict | str | None = None,
    *,
    page_size: int = 100,
) -> dict:
    """Manage roles on the Delinea Platform identity service.

    Endpoint coverage:

    * ``"create"`` -> ``POST /identity/SaasManage/StoreRole`` with body
      ``{"Name": ..., "Description": ...}``.
      Returns the role identifier in ``Result._RowKey``.
    * ``"update"`` -> ``POST /identity/Roles/UpdateRole`` with body
      ``{"Name": <role-id>, "Description": ..., "Users": {"Add": [...], "Delete": [...]}}``.
    * ``"list"`` -> ``POST /identity/Redrock/Query`` with the role-listing
      script.
    * ``"get"`` -> ``POST /identity/Redrock/Query`` filtered to the role id.
    * ``"delete"`` -> ``POST /identity/SaasManage/RemoveRole`` body
      ``{"Name": <role-id>}``.

    Parameters
    ----------
    action:
        ``"list"``, ``"get"``, ``"create"``, ``"update"`` or ``"delete"``.
    role_id:
        Required for ``"get"``, ``"update"`` and ``"delete"``.  This is the
        Platform's role identifier (a string ``_RowKey`` returned by
        ``StoreRole`` — *not* a numeric SS role id).
    data:
        For ``"create"``: ``{"Name": ..., "Description": ...}``.
        For ``"update"``: any subset of ``{"Description", "Name",
        "Users": {"Add": [...], "Delete": [...]}, "Roles": {"Add": [...]}}``.

    Returns
    -------
    dict
        Raw API payload or ``{"result": ..., "verification": ...}`` for
        write actions.
    """

    logger.debug("platform_role_management(action=%s, role_id=%s)", action, role_id)

    try:
        headers = _build_headers()
    except RuntimeError as exc:
        return {"error": str(exc)}

    payload = _parse_json_data(data)

    try:
        if action == "list":
            url = _platform_url("/Redrock/Query")
            body = {
                "Script": (
                    "SELECT ID, Name, Description FROM Role "
                    "ORDER BY Name COLLATE NOCASE"
                ),
                "Args": {"PageNumber": 1, "PageSize": page_size},
            }
            return _json_or_error(
                requests.post(url, json=body, headers=headers, timeout=_DEFAULT_TIMEOUT)
            )

        if action == "get":
            if not role_id:
                raise ValueError("role_id required for get")
            url = _platform_url("/Redrock/Query")
            # Parameterise to avoid script injection.
            body = {
                "Script": ("SELECT ID, Name, Description FROM Role WHERE ID = @rid"),
                "Args": {
                    "PageNumber": 1,
                    "PageSize": 1,
                    "Parameters": [{"Name": "rid", "Value": role_id, "Type": "string"}],
                },
            }
            return _json_or_error(
                requests.post(url, json=body, headers=headers, timeout=_DEFAULT_TIMEOUT)
            )

        if action == "create":
            if payload is None or not payload.get("Name"):
                raise ValueError("data with 'Name' required for create")
            url = _platform_url("/SaasManage/StoreRole")
            resp = requests.post(
                url, json=payload, headers=headers, timeout=_DEFAULT_TIMEOUT
            )
            result = _json_or_error(resp)
            new_id = (
                (result.get("Result") or {}).get("_RowKey")
                if isinstance(result.get("Result"), dict)
                else None
            )
            verify: dict[str, Any] = {}
            if new_id:
                verify = platform_role_management("get", role_id=new_id)
            return {"result": result, "verification": verify}

        if action == "update":
            if not role_id or payload is None:
                raise ValueError("role_id and data required for update")
            url = _platform_url("/Roles/UpdateRole")
            body = {"Name": role_id, **payload}
            resp = requests.post(
                url, json=body, headers=headers, timeout=_DEFAULT_TIMEOUT
            )
            result = _json_or_error(resp)
            verify = platform_role_management("get", role_id=role_id)
            return {"result": result, "verification": verify}

        if action == "delete":
            if not role_id:
                raise ValueError("role_id required for delete")
            url = _platform_url("/SaasManage/RemoveRole")
            resp = requests.post(
                url, json={"Name": role_id}, headers=headers, timeout=_DEFAULT_TIMEOUT
            )
            result = _json_or_error(resp)
            verify = platform_role_management("get", role_id=role_id)
            return {"result": result, "verification": verify}

        raise ValueError(f"Unknown action: {action}")
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("platform_role_management action failed")
        return {"error": str(exc)}


def platform_user_role_management(
    action: str,
    role_id: str,
    user_principals: list[str] | str | None = None,
) -> dict:
    """Add or remove users from a Platform role.

    Implemented via ``POST /identity/Roles/UpdateRole`` with a body of
    ``{"Name": <role_id>, "Users": {"Add": [...], "Delete": [...]}}``.

    Parameters
    ----------
    action:
        ``"add"``, ``"remove"`` or ``"list"`` (lists current role members).
    role_id:
        Platform role identifier (the ``_RowKey`` returned by ``StoreRole``).
    user_principals:
        For ``"add"``/``"remove"``: list of user principal names (e.g.
        ``"alice@tenant"``) or user IDs.  Accepts a JSON-encoded string too.
        Ignored for ``"list"``.

    Returns
    -------
    dict
        For ``"list"``: raw response payload listing role members.
        For ``"add"``/``"remove"``: ``{"result": ..., "verification": ...}``.
    """

    logger.debug(
        "platform_user_role_management(action=%s, role_id=%s)", action, role_id
    )

    try:
        headers = _build_headers()
    except RuntimeError as exc:
        return {"error": str(exc)}

    if isinstance(user_principals, str):
        try:
            user_principals = json.loads(user_principals)
        except Exception:
            return {"error": "user_principals must be a list or a JSON-encoded list"}

    try:
        if action == "list":
            url = _platform_url("/Redrock/Query")
            # Roles → RoleMembers join: ask the Platform for the principals.
            body = {
                "Script": (
                    "SELECT u.Username, u.ID FROM User u "
                    "INNER JOIN RoleMember rm ON rm.UserID = u.ID "
                    "WHERE rm.RoleID = @rid"
                ),
                "Args": {
                    "PageNumber": 1,
                    "PageSize": 200,
                    "Parameters": [{"Name": "rid", "Value": role_id, "Type": "string"}],
                },
            }
            return _json_or_error(
                requests.post(url, json=body, headers=headers, timeout=_DEFAULT_TIMEOUT)
            )

        if action in ("add", "remove"):
            if not user_principals:
                raise ValueError(f"user_principals required for {action}")
            key = "Add" if action == "add" else "Delete"
            url = _platform_url("/Roles/UpdateRole")
            body = {"Name": role_id, "Users": {key: list(user_principals)}}
            resp = requests.post(
                url, json=body, headers=headers, timeout=_DEFAULT_TIMEOUT
            )
            result = _json_or_error(resp)
            verify = platform_user_role_management("list", role_id=role_id)
            return {"result": result, "verification": verify}

        raise ValueError(f"Unknown action: {action}")
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("platform_user_role_management action failed")
        return {"error": str(exc)}


# --------------------------------------------------------------------------- #
# Registration                                                                #
# --------------------------------------------------------------------------- #


# In v1.0.0 the canonical names ``user_management`` and ``search_users`` are
# served from this module.  ``platform_user_management`` is retained as a
# deprecated alias.
TOOLS = [
    ("user_management", user_management),
    ("search_users", search_users),
    ("platform_user_management", platform_user_management),
    ("platform_role_management", platform_role_management),
    ("platform_user_role_management", platform_user_role_management),
]


def register(mcp: Any) -> None:
    """Register Platform tools on a FastMCP server.

    Tools register unconditionally so the LLM always sees the canonical
    ``user_management`` and ``search_users`` names.  When Platform is not
    configured, calls return a helpful error directing the caller to
    either configure Platform or use the legacy SS-local tools.
    """
    for name, func in TOOLS:
        mcp.tool()(func)
