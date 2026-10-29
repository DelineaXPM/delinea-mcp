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
* ``GET  /report/api/report/report-definitions`` — Platform report
  library (``platform_reports``); ``POST .../{name}/results`` runs one
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Iterable
from urllib.parse import quote

import requests

from delinea_mcp.annotations import TOOL_ANNOTATIONS
from delinea_mcp.tool_guard import guard_tool

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


def _endpoint_not_available(response: requests.Response) -> bool:
    """Return True when *response* looks like 'endpoint not in this scope'.

    On modern Delinea Platform tenants the legacy role-management endpoints
    return a bare 404 with an empty body.  Older Centrify deployments
    return a JSON envelope with ``success=False`` and a descriptive
    message.  We treat any 404 as "not available" — the tools fall back to
    a structured guidance error in that case.
    """
    return response.status_code == 404


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
# Tools run on parallel worker threads; serialise token acquisition so
# concurrent first calls don't race on the cached headers.
_headers_lock = threading.Lock()


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

    with _headers_lock:
        return _fetch_headers()


def _fetch_headers() -> dict[str, str]:
    global _headers
    if _headers:
        return _headers

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
    "Platform role write endpoint returned 404 — this OAuth scope on this "
    "tenant does not expose role mutations (typical on modern Delinea Platform "
    "deployments using the xpmheadless scope). Use the Secret-Server-backed "
    "role_management tool to manage roles in mixed Platform/SS deployments, "
    "or open the tenant's admin UI directly."
)


def platform_role_management(
    action: str,
    role_id: str | None = None,
    data: dict | str | None = None,
    *,
    page_size: int = 100,
    query: str = "%",
) -> dict:
    """Manage roles on the Delinea Platform identity service.

    Endpoint coverage:

    * ``"list"`` -> ``POST /identity/api/Report/RunReport`` ID
      ``role_searchbyname`` with a wildcard match.  Returns all visible roles.
    * ``"get"`` -> same report filtered by an exact / substring role name.
    * ``"create"`` -> ``POST /identity/api/SaasManage/StoreRole`` (body
      ``{"Name": ..., "Description": ...}``).  Returns the role's
      ``_RowKey`` in ``Result``.
    * ``"update"`` -> ``POST /identity/api/Roles/UpdateRole`` (body
      ``{"Name": <role-id>, "Description": ..., "Users": {"Add": [...]}, ...}``).
    * ``"delete"`` -> ``POST /identity/api/SaasManage/RemoveRole``.

    Mutation behaviour is **discovery-driven**: the tool attempts the
    documented endpoint, and only falls back to a structured guidance
    error when the response is HTTP 404 (typical on modern Delinea
    Platform tenants using the ``xpmheadless`` scope, which exposes
    user CRUD but not role CRUD).  Tenants that do expose role
    mutations get the real result.

    Parameters
    ----------
    action:
        ``"list"``, ``"get"``, ``"create"``, ``"update"`` or ``"delete"``.
    role_id:
        Required for ``"get"``, ``"update"`` and ``"delete"``.  For
        modern Platform this is typically a Name; for legacy Centrify
        deployments it's the ``_RowKey`` returned by ``StoreRole``.
    data:
        For ``"create"``: ``{"Name": ..., "Description": ...}``.
        For ``"update"``: any subset of
        ``{"Description", "Name", "Users": {"Add": [...], "Delete": [...]},
        "Roles": {"Add": [...]}}``.
    page_size:
        Maximum rows for ``"list"``.
    query:
        Optional search substring for ``"list"``.  Default ``"%"`` matches all.

    Returns
    -------
    dict
        Raw API payload for reads, ``{"result": ..., "verification": ...}``
        for successful writes, or ``{"error": ...}`` when the endpoint is
        unavailable on this tenant.
    """

    logger.debug("platform_role_management(action=%s, role_id=%s)", action, role_id)

    try:
        headers = _build_headers()
    except RuntimeError as exc:
        return {"error": str(exc)}

    payload = _parse_json_data(data)

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

        if action == "create":
            if payload is None or not payload.get("Name"):
                raise ValueError("data with 'Name' required for create")
            url = _platform_url("/SaasManage/StoreRole")
            resp = requests.post(
                url, json=payload, headers=headers, timeout=_DEFAULT_TIMEOUT
            )
            if _endpoint_not_available(resp):
                return {"error": _ROLE_WRITE_NOT_SUPPORTED}
            result = _json_or_error(resp)
            new_id = None
            if isinstance(result, dict):
                r = result.get("Result")
                if isinstance(r, str):
                    new_id = r
                elif isinstance(r, dict):
                    new_id = r.get("_RowKey") or r.get("ID") or r.get("Name")
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
            if _endpoint_not_available(resp):
                return {"error": _ROLE_WRITE_NOT_SUPPORTED}
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
            if _endpoint_not_available(resp):
                return {"error": _ROLE_WRITE_NOT_SUPPORTED}
            result = _json_or_error(resp)
            verify = platform_role_management("get", role_id=role_id)
            return {"result": result, "verification": verify}

        raise ValueError(f"Unknown action: {action}")
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("platform_role_management action failed")
        return {"error": str(exc)}


_USER_ROLE_WRITE_NOT_SUPPORTED = (
    "Platform user-role mutation endpoint returned 404 — this OAuth scope on "
    "this tenant does not expose role-membership writes (typical on modern "
    "Delinea Platform deployments using the xpmheadless scope). Use the "
    "Secret-Server-backed user_role_management tool, which manages the "
    "SS-side role wiring that Platform tenants typically mirror, or the "
    "Platform admin UI directly."
)


def platform_user_role_management(
    action: str,
    role_id: str,
    user_principals: list[str] | str | None = None,
) -> dict:
    """Add, remove, or list users assigned to a Platform role.

    * ``"list"`` -> ``POST /identity/api/Report/RunReport`` ID
      ``role_searchbyname`` (filtered to *role_id*).  Returns the role's
      row; some tenants include a ``members`` column there.  Callers can
      cross-reference with :func:`search_users`.
    * ``"add"``/``"remove"`` -> ``POST /identity/api/Roles/UpdateRole`` with
      body ``{"Name": <role_id>, "Users": {"Add": [...]}}`` or
      ``{"Users": {"Delete": [...]}}``.

    Mutation behaviour is **discovery-driven**: the tool attempts the
    documented endpoint and only falls back to a structured guidance
    error when the response is HTTP 404.

    Parameters
    ----------
    action:
        ``"add"``, ``"remove"`` or ``"list"``.
    role_id:
        Platform role name/identifier.
    user_principals:
        For ``"add"``/``"remove"``: list of user principal names (e.g.
        ``"alice@tenant"``) or UUIDs.  Accepts a JSON-encoded string too.

    Returns
    -------
    dict
        Report payload for ``"list"``; ``{"result": ..., "verification": ...}``
        for successful writes; ``{"error": ...}`` when the endpoint is
        unavailable on this tenant.
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
            if not user_principals:
                raise ValueError(f"user_principals required for {action}")
            key = "Add" if action == "add" else "Delete"
            url = _platform_url("/Roles/UpdateRole")
            body = {"Name": role_id, "Users": {key: list(user_principals)}}
            resp = requests.post(
                url, json=body, headers=headers, timeout=_DEFAULT_TIMEOUT
            )
            if _endpoint_not_available(resp):
                return {"error": _USER_ROLE_WRITE_NOT_SUPPORTED}
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
# --------------------------------------------------------------------------- #
# Platform reports (Insights > Reports)                                       #
# --------------------------------------------------------------------------- #

_REPORT_ACTIONS = ("list", "describe", "run", "snapshots", "snapshot_results")
# Running a report fans out to the Platform services behind it and can take
# well over the 30 s default; override with ``PLATFORM_REPORT_TIMEOUT``.
_REPORT_RUN_TIMEOUT = float(os.getenv("PLATFORM_REPORT_TIMEOUT", "120"))
_REPORT_RUN_HINT = (
    "The report may need required inputs (see action='describe'); date "
    "inputs take ISO-8601 strings via their start/end parameters."
)


def _report_url(path: str) -> str:
    """Build a Platform *report service* URL (``/report/api/...``).

    The reporting backend is a separate Platform service from the identity
    API behind :func:`_platform_url`; it publishes its own OpenAPI document
    at ``https://<tenant>/report/swagger/v1/swagger.json`` and accepts the
    same ``xpmheadless`` bearer token.
    """
    return f"https://{platform_hostname}/report/api{path}"


def _report_response(response: requests.Response, hint: str | None = None) -> dict:
    """Return the JSON body, or ``{"error": ...}`` for non-2xx responses."""
    body = _json_or_error(response)
    if response.status_code < 400:
        return body
    result: dict = {
        "error": f"Platform report API returned HTTP {response.status_code}",
        "detail": body,
    }
    if response.status_code == 404:
        result["hint"] = "Unknown report name or snapshot id; use action='list'."
    elif hint:
        result["hint"] = hint
    return result


def _normalise_report_filters(filters: list | dict | str | None) -> list[dict]:
    """Translate caller-friendly filters into ``FilterRunValueModel`` items.

    Accepted forms (they may be mixed inside one list):

    * ``{"parameter": "UserLoginData.email", "value": "kevin",
      "operator": "Contains"}`` -- ``parameter`` is the string that
      ``describe`` reports for an input (``<callback>.<key>``);
      ``operator``, ``type`` (default ``"Text"``) and ``label`` are optional.
    * A dict shorthand ``{"UserLoginData.email": "kevin"}``.
    * A ready-made ``FilterRunValueModel`` (has a ``filterValue`` key),
      passed through untouched.
    * A JSON string encoding any of the above.

    ``None`` (or an empty list / dict) means "no filters"; any other scalar
    is rejected so a malformed request never runs the report unfiltered.
    """
    if filters is None:
        return []
    filters = _parse_json_data(filters)
    if isinstance(filters, dict):
        if "filterValue" in filters or "parameter" in filters:
            items = [filters]
        else:
            items = [
                {"parameter": key, "value": value} for key, value in filters.items()
            ]
    elif isinstance(filters, list):
        items = filters
    else:
        raise ValueError("filters must be a list, a dict or a JSON string")

    normalised: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each filter must be an object")
        if "filterValue" in item:
            normalised.append(item)
            continue
        parameter = str(item.get("parameter") or "")
        if not parameter:
            raise ValueError("each filter needs a 'parameter' (see action='describe')")
        callback, _, key = parameter.partition(".")
        if not key:
            callback, key = "", parameter
        value = item.get("value")
        entry: dict = {
            "filterValue": {
                "filterType": item.get("type") or "Text",
                "stringValue": "" if value is None else str(value),
                "filterParameterKey": key,
            }
        }
        if callback:
            entry["callbackName"] = callback
        if item.get("operator"):
            entry["operatorValue"] = item["operator"]
        if item.get("label"):
            entry["displayName"] = item["label"]
        normalised.append(entry)
    return normalised


def _compact_report_definition(definition: dict) -> dict:
    """Reduce a ``ReportDefinitionModel`` to what a caller needs to run it.

    Drops the backend ``callbacks`` (internal service URLs, headers and
    paging plumbing) and flattens ``frontEndConfiguration`` into the
    ``inputs`` the report accepts and the ``columns`` it returns.
    """
    front = definition.get("frontEndConfiguration") or {}
    inputs: list[dict] = []
    for item in (front.get("form") or {}).get("inputs") or []:
        conf = item.get("configuration") or {}
        entry: dict = {
            "label": item.get("label"),
            "type": item.get("inputType"),
            "required": bool(conf.get("required")),
        }
        nested = conf.get("configuration") or {}
        if nested.get("startDateFilterParameter") or nested.get(
            "endDateFilterParameter"
        ):
            # Date ranges are two plain parameters that accept ISO-8601
            # strings; the composite ``filterParameter`` itself is not
            # accepted by the run endpoint.
            entry["start_parameter"] = nested.get("startDateFilterParameter")
            entry["end_parameter"] = nested.get("endDateFilterParameter")
            entry["value_format"] = "ISO-8601 date or datetime string"
        else:
            entry["parameter"] = conf.get("filterParameter")
        if conf.get("operatorOptions"):
            entry["operators"] = conf["operatorOptions"]
        if conf.get("defaultValue") not in (None, ""):
            entry["default"] = conf["defaultValue"]
        if conf.get("allowMultiple") is not None:
            entry["allow_multiple"] = bool(conf["allowMultiple"])
        inputs.append(entry)
    columns = [
        {
            "name": column.get("columnName"),
            "type": column.get("columnType"),
            "property": column.get("propertyMap"),
            "sortable": bool(column.get("isSortable")),
        }
        for column in front.get("gridColumnModels") or []
    ]
    return {
        "service": definition.get("service"),
        "name": definition.get("name"),
        "description": definition.get("description"),
        "is_async": definition.get("isAsync"),
        "time_to_live": definition.get("timeToLive"),
        "inputs": inputs,
        "columns": columns,
    }


def platform_reports(
    action: str = "list",
    report: str | None = None,
    filters: list | dict | str | None = None,
    *,
    page: int = 1,
    page_size: int = 50,
    service: str | None = None,
    query: str | None = None,
    snapshot_id: str | None = None,
) -> dict:
    """Browse and run Delinea Platform reports (Insights > Reports), read-only.

    The Platform report library (Fall 2026 release) covers every Platform
    service: Secret Server (e.g. "Top 10 Viewers of Secrets"), Identity
    (MFA login events, failed logins, last / missing logins, password
    resets), Permissions (members of a role, users with a permission),
    Inventory, Entitlement and Identity Lifecycle.  Report *names* are the
    identifiers.  Typical flow: ``list`` -> ``describe`` -> ``run``.

    Endpoint coverage (Platform report service, ``/report/api/...``):

    * ``"list"`` -> ``GET /report/report-definitions`` (optional ``query``
      full-text match and ``service`` exact match, paged).
    * ``"describe"`` -> ``GET /report/report-definitions/{report}``,
      reduced to the report's ``inputs`` (each with the ``parameter`` string
      to use in ``filters``, its ``operators`` and whether it is
      ``required``) and its result ``columns``.
    * ``"run"`` -> ``POST /report/report-definitions/{report}/results``,
      executed synchronously; returns ``{"data": [...], "totalCount": N,
      "reportDefinitionName": ...}`` for the requested page.
    * ``"snapshots"`` -> ``GET /report/report-snapshots`` (saved runs the
      service account owns or was given access to).
    * ``"snapshot_results"`` -> ``GET /report/report-snapshots/{id}/results``.

    Nothing is created, scheduled, shared or deleted; a ``run`` only adds a
    "View" entry to the report's audit history.  Runs wait up to
    ``PLATFORM_REPORT_TIMEOUT`` seconds (default 120) for the backend.

    Parameters
    ----------
    action:
        ``"list"``, ``"describe"``, ``"run"``, ``"snapshots"`` or
        ``"snapshot_results"``.
    report:
        Report name (required for ``describe`` / ``run``).
    filters:
        For ``run``: a list of ``{"parameter": "<callback>.<key>",
        "value": "...", "operator": "Contains"}`` objects using the
        ``parameter`` strings from ``describe`` (``operator`` optional; date
        inputs take ISO-8601 strings on their ``start_parameter`` /
        ``end_parameter``).  A ``{"<parameter>": "<value>"}`` dict or a JSON
        string of either form is also accepted.
    page / page_size:
        Result paging for ``list``, ``run``, ``snapshots`` and
        ``snapshot_results``.
    service:
        For ``list``: exact service name (``"Secret Server"``,
        ``"Identity"``, ``"Permissions"``, ...).
    query:
        For ``list`` / ``snapshots``: free-text match on name/description.
    snapshot_id:
        Required for ``snapshot_results``.

    Returns
    -------
    dict
        The report service payload, or ``{"error": ..., "detail": ...,
        "hint": ...}`` when the service rejects the request.
    """

    logger.debug("platform_reports(action=%s, report=%s)", action, report)

    if action not in _REPORT_ACTIONS:
        return {
            "error": f"Unknown action {action!r}; use one of {list(_REPORT_ACTIONS)}"
        }
    if action in ("describe", "run") and not report:
        return {"error": f"report name required for action={action!r}"}
    if action == "snapshot_results" and not snapshot_id:
        return {"error": "snapshot_id required for action='snapshot_results'"}

    try:
        page = max(int(page), 1)
        page_size = max(int(page_size), 1)
    except (TypeError, ValueError):
        return {"error": "page and page_size must be positive integers"}

    # Normalise filters before touching the network so a malformed request
    # fails fast instead of first fetching (or failing to fetch) a token.
    filter_values: list[dict] = []
    if action == "run":
        try:
            filter_values = _normalise_report_filters(filters)
        except ValueError as exc:
            return {"error": str(exc)}

    try:
        headers = _build_headers()
    except RuntimeError as exc:
        return {"error": str(exc)}

    paging = {"RecordsPerPage": page_size, "PageNumber": page}
    try:
        if action == "list":
            params: dict[str, Any] = dict(paging)
            if query:
                params["SearchText"] = query
            if service:
                params["Service.Eq"] = service
            response = requests.get(
                _report_url("/report/report-definitions"),
                headers=headers,
                params=params,
                timeout=_DEFAULT_TIMEOUT,
            )
            return _report_response(response)

        if action == "describe":
            response = requests.get(
                _report_url(f"/report/report-definitions/{quote(report, safe='')}"),
                headers=headers,
                timeout=_DEFAULT_TIMEOUT,
            )
            result = _report_response(response)
            if "error" in result:
                return result
            return _compact_report_definition(result)

        if action == "run":
            payload = {
                "reportDefinitionName": report,
                "filterValues": filter_values,
                "pagination": {"recordsPerPage": page_size, "pageNumber": page},
            }
            response = requests.post(
                _report_url(
                    f"/report/report-definitions/{quote(report, safe='')}/results"
                ),
                headers=headers,
                json=payload,
                timeout=_REPORT_RUN_TIMEOUT,
            )
            return _report_response(response, hint=_REPORT_RUN_HINT)

        if action == "snapshots":
            params = dict(paging)
            if query:
                params["SearchText"] = query
            response = requests.get(
                _report_url("/report/report-snapshots"),
                headers=headers,
                params=params,
                timeout=_DEFAULT_TIMEOUT,
            )
            return _report_response(response)

        response = requests.get(
            _report_url(
                f"/report/report-snapshots/{quote(snapshot_id, safe='')}/results"
            ),
            headers=headers,
            params=paging,
            timeout=_REPORT_RUN_TIMEOUT,
        )
        return _report_response(response)
    except Exception as exc:
        logger.exception("Platform report request failed")
        return {"error": str(exc)}


TOOLS = [
    ("user_management", user_management),
    ("search_users", search_users),
    ("platform_user_management", platform_user_management),
    ("platform_role_management", platform_role_management),
    ("platform_user_role_management", platform_user_role_management),
    ("platform_reports", platform_reports),
]


def register(mcp: Any, enabled: Iterable[str] | None = None) -> None:
    """Register Platform tools on an MCP server.

    Honours the same ``enabled_tools`` allowlist semantics as
    :func:`delinea_mcp.tools.register`: an empty/missing set registers
    every tool in this module (including the canonical
    ``user_management`` / ``search_users`` names); a non-empty set
    registers only the named tools. When Platform is not configured,
    registered tools still return a helpful error directing the caller
    to configure Platform or use the legacy SS-local tools.
    """
    enabled_set = set(enabled or [])
    if not enabled_set:
        enabled_set = {name for name, _ in TOOLS}
    for name, func in TOOLS:
        if name in enabled_set:
            mcp.tool(annotations=TOOL_ANNOTATIONS.get(name))(guard_tool(func))
