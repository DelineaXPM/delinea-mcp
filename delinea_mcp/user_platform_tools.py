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
    """Build a Platform identity-API URL.

    Modern Delinea Platform tenants serve all identity-API endpoints under
    ``/identity/api/...``.  Accept paths in two forms:

    * ``"/UserMgmt/GetUserAttributes"`` — auto-prefixed with ``/identity/api``.
    * ``"/identity/api/..."`` — used verbatim (compat with older code that
      already hard-coded the prefix).
    """
    if path.startswith("/identity/"):
        return f"https://{platform_hostname}{path}"
    if path.startswith("/api/"):
        # Old code shape: ``/api/Report/RunReport`` → ``/identity/api/...``
        return f"https://{platform_hostname}/identity{path}"
    # New shape: bare endpoint name → ``/identity/api/<endpoint>``
    return f"https://{platform_hostname}/identity/api{path}"


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
            # Modern Delinea Platform exposes /identity/api/UserMgmt/GetUserAttributes
            # (POST, body {"ID": <uuid>}) — the legacy /UserMgmt/GetUser GET endpoint
            # was removed.  GetUserAttributes returns a richer record.
            url = _platform_url("/UserMgmt/GetUserAttributes")
            response = requests.post(
                url,
                json={"ID": user_id},
                headers=headers,
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


_ROLE_SEARCH_REPORT_ID = "role_searchbyname"


def _run_role_search_report(
    headers: dict[str, str], query: str = "%", page_size: int = 100
) -> dict:
    """Run the ``role_searchbyname`` canned report.

    The modern Delinea Platform exposes role data through this report
    rather than via dedicated REST endpoints or Redrock SQL.  The shape
    mirrors :func:`search_users` exactly.
    """
    url = _platform_url("/Report/RunReport")
    payload = {
        "ID": _ROLE_SEARCH_REPORT_ID,
        "Args": {
            "PageNumber": 1,
            "PageSize": page_size,
            "Limit": 100000,
            "FilterQuery": None,
            "Caching": 0,
            "Ascending": True,
            "SortBy": "Name",
            "Parameters": [
                {
                    "Name": "searchString",
                    "Value": query,
                    "Label": "searchString",
                    "Type": "string",
                    "ColumnType": 12,
                },
                {
                    "Name": "orderby",
                    "Value": "Name",
                    "Label": "orderby",
                    "Type": "string",
                    "ColumnType": 12,
                },
            ],
        },
    }
    return _json_or_error(
        requests.post(url, json=payload, headers=headers, timeout=_DEFAULT_TIMEOUT)
    )


_ROLE_WRITE_NOT_SUPPORTED = (
    "Platform role write operations (create/update/delete) are not exposed "
    "through the xpmheadless OAuth scope on modern Delinea Platform tenants — "
    "the legacy SaasManage/StoreRole + Roles/UpdateRole endpoints return 404. "
    "Use the Secret-Server-backed role_management tool to manage roles in "
    "mixed Platform/SS deployments, or open the tenant's admin UI directly."
)


def platform_role_management(
    action: str,
    role_id: str | None = None,
    data: dict | str | None = None,  # noqa: ARG001 — accepted for parity with SS API
    *,
    page_size: int = 100,
    query: str = "%",
) -> dict:
    """Read roles on the Delinea Platform identity service.

    Endpoint coverage on **modern Delinea Platform** tenants:

    * ``"list"`` -> ``POST /identity/api/Report/RunReport`` ID
      ``role_searchbyname`` with a wildcard match.  Returns all visible roles.
    * ``"get"`` -> same report filtered by exact role name (since the modern
      Platform doesn't expose a Redrock SQL endpoint to filter by ID).
    * ``"create"``/``"update"``/``"delete"`` — **not supported** on modern
      tenants via this scope.  Returns a structured error pointing the caller
      at :func:`delinea_mcp.tools.role_management` (which manages roles
      through Secret Server's ``/v1/roles`` API in mixed deployments).

    Parameters
    ----------
    action:
        ``"list"`` or ``"get"`` (read).  ``"create"``/``"update"``/``"delete"``
        return an "unsupported" error on modern Platform tenants.
    role_id:
        For ``"get"``: the role's Name (modern Platform) or ID (legacy).
        The canned report matches against ``Name``.
    page_size:
        Maximum rows for ``"list"``.
    query:
        Optional search substring for ``"list"``.  Default ``"%"`` matches all.

    Returns
    -------
    dict
        Raw report payload for ``"list"``/``"get"``; ``{"error": ...}`` for
        unsupported write actions.
    """

    logger.debug("platform_role_management(action=%s, role_id=%s)", action, role_id)

    try:
        headers = _build_headers()
    except RuntimeError as exc:
        return {"error": str(exc)}

    try:
        if action == "list":
            return _run_role_search_report(headers, query=query, page_size=page_size)

        if action == "get":
            if not role_id:
                raise ValueError("role_id required for get")
            # The canned report filters on Name (case-insensitive substring).
            # For modern tenants role_id is typically a Name; for legacy IDs
            # callers can pass the ID and rely on Name = ID for system roles.
            return _run_role_search_report(headers, query=str(role_id), page_size=10)

        if action in ("create", "update", "delete"):
            return {"error": _ROLE_WRITE_NOT_SUPPORTED}

        raise ValueError(f"Unknown action: {action}")
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("platform_role_management action failed")
        return {"error": str(exc)}


_USER_ROLE_WRITE_NOT_SUPPORTED = (
    "Platform user-role membership mutations (add/remove) are not exposed "
    "through the xpmheadless OAuth scope on modern Delinea Platform tenants — "
    "the legacy Roles/UpdateRole endpoint returns 404. Use the "
    "Secret-Server-backed user_role_management tool, which manages the "
    "SS-side role wiring that Platform tenants typically mirror, or the "
    "Platform admin UI directly."
)


def platform_user_role_management(
    action: str,
    role_id: str,
    user_principals: list[str] | str | None = None,
) -> dict:
    """Read users assigned to a Platform role.

    On **modern Delinea Platform** tenants:

    * ``"list"`` -> ``POST /identity/api/Report/RunReport`` ID
      ``user_searchbyname`` (the canned report doesn't filter by role
      directly; this returns *all* users — callers should use
      :func:`search_users` instead and look at the ``Roles`` column there
      if their tenant exposes it).
    * ``"add"``/``"remove"`` — **not supported** via the xpmheadless scope.
      Returns a structured error pointing at SS-side ``user_role_management``.

    Parameters
    ----------
    action:
        ``"add"``, ``"remove"`` or ``"list"``.
    role_id:
        Platform role name/identifier.
    user_principals:
        Ignored for ``"list"``; required for ``"add"``/``"remove"`` (but
        those return an unsupported-on-this-tenant error).

    Returns
    -------
    dict
        For ``"list"``: passthrough of the report payload.
        For mutations: ``{"error": ...}`` with a clear remediation pointer.
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
            # Look up role-by-name then return any membership info the report
            # exposes.  The canned report returns roletype + description; some
            # tenants augment with a 'members' field.
            return _run_role_search_report(headers, query=str(role_id), page_size=50)

        if action in ("add", "remove"):
            return {"error": _USER_ROLE_WRITE_NOT_SUPPORTED}

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
