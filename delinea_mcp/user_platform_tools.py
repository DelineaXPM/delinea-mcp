"""Delinea Platform identity-API tooling.

Modern Delinea cloud deployments authenticate users via the Delinea
Platform identity provider.  This module exposes the canonical user,
role, and search tools that operate against the Platform's identity
endpoints (``/identity/...``).

The Secret-Server-local user tools live in
:mod:`delinea_mcp.secretserver_users` as ``*secretserver_local_*`` for
SS-only on-prem deployments.

Endpoint references
-------------------

* ``POST /identity/CDirectoryService/CreateUser`` — create user
* ``POST /identity/CDirectoryService/ChangeUser`` — update user
* ``POST /identity/UserMgmt/GetUserAttributes`` — get user
* ``POST /identity/UserMgmt/RemoveUsers`` body ``{"Users":[id]}`` — delete
* ``POST /identity/api/Report/RunReport`` — search via canned reports
* ``/permission/api/roles`` and ``/permission/api/role-memberships`` —
  Platform roles and role assignments (the Permission service; the
  Platform's identity API has no Roles or SaasManage controller)
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

from delinea_mcp.annotations import tool_metadata
from delinea_mcp.api import (
    mask_fields,
    platform_host,
    raise_for_status,
    redact,
    redact_values,
    sensitive_values,
)
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


def _json_or_error(response: requests.Response, sensitive: Iterable[str] = ()) -> dict:
    """Decode a Platform response, turning HTTP failures into actionable errors.

    *sensitive* values (a password the request sent) are masked in the error
    and in the body, since the Platform also reports failures with HTTP 200.
    """
    status = getattr(response, "status_code", 200)
    if isinstance(status, int) and status >= 400:
        try:
            raise_for_status(response, "Delinea Platform request", sensitive=sensitive)
        # requests.HTTPError, not DelineaAPIError: the base class stays the
        # same object even if a test reloads delinea_mcp.api.
        except requests.HTTPError as exc:
            return {"error": str(exc)}
    return redact_values(_raw_json(response), sensitive)


def _raw_json(response: requests.Response) -> dict:
    """Return the decoded body, or ``{"error": <text>}`` when it isn't JSON."""
    try:
        return response.json()
    except Exception:
        return {"error": response.text}


# Bare host; a pasted URL (https://tenant.delinea.app/) is accepted.
platform_hostname = platform_host(os.getenv("PLATFORM_HOSTNAME")) or None
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
        platform_hostname = platform_host(hostname)
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
    "For SS-only deployments, use search_secretserver_local_users / "
    "get_secretserver_local_user instead."
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
        # Mask the client secret before shortening, in case it's echoed.
        detail = redact(response.text or "", platform_service_password)[:500]
        logger.error("Failed to get token: %s", detail)
        raise RuntimeError(f"Failed to get token: {detail}")

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

    Secret Server deployments without the Platform keep users in Secret
    Server; ``search_secretserver_local_users`` searches those.

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

    Not registered as a tool (it mixes reads and writes); the
    ``*_platform_user`` tools call it. It talks to the Platform identity
    API, the authoritative user store in Platform-integrated tenants.

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
        mask_fields(data),  # a new user's data can carry a password
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
            result = _json_or_error(response, sensitive_values(payload))
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
            result = _json_or_error(response, sensitive_values(payload))
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
    # Keep the Platform's own error body as ``detail``; the status line and
    # hint below already explain the failure.
    body = _raw_json(response)
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


# user_management is not registered: it mixes reads and writes, which the
# Claude directory rejects. These tools split it.


def get_platform_user(user_id: str) -> dict:
    """Get one Delinea Platform user's attributes by user UUID.

    Calls ``POST /identity/api/UserMgmt/GetUserAttributes``; find the UUID
    with ``search_users``. API reference:
    https://developer.delinea.com/reference/post_usermgmt-getuserattributes
    """
    return user_management("get", user_id=user_id)


def create_platform_user(data: dict | str) -> dict:
    """Create a Delinea Platform cloud user.

    Calls ``POST /identity/api/CDirectoryService/CreateUser``; *data* needs
    ``Name`` (the login name, e.g. ``alice@tenant``) and usually ``Mail``,
    ``DisplayName`` and ``Password``. Passwords are masked in errors and
    logs. Returns ``{"result": ..., "verification": ...}``. API reference:
    https://developer.delinea.com/reference/post_cdirectoryservice-createuser
    """
    return user_management("create", data=data)


def update_platform_user(user_id: str, data: dict | str) -> dict:
    """Update a Delinea Platform cloud user.

    Calls ``POST /identity/api/CDirectoryService/ChangeUser`` with only the
    fields in *data*; it can replace the password or disable the user.
    Passwords are masked in errors and logs. Returns ``{"result": ...,
    "verification": ...}``. API reference:
    https://developer.delinea.com/reference/post_cdirectoryservice-changeuser
    """
    return user_management("update", user_id=user_id, data=data)


def delete_platform_user(user_id: str) -> dict:
    """Delete a Delinea Platform user by UUID.

    Calls ``POST /identity/api/UserMgmt/RemoveUsers``. Cloud directory users
    are deleted; users from other directories are only removed from the
    Platform. API reference:
    https://developer.delinea.com/reference/post_usermgmt-removeusers
    """
    return user_management("delete", user_id=user_id)


def _permission_url(path: str) -> str:
    """Build a Platform *Permission service* URL (``/permission/api/...``).

    Platform roles and role assignments live in this service, not in the
    identity API behind :func:`_platform_url` (which has no Roles or
    SaasManage controller on the Platform). It publishes its OpenAPI document
    at ``https://<tenant>/permission/swagger/v1/swagger.json`` and accepts the
    same bearer token.
    """
    return f"https://{platform_hostname}/permission/api{path}"


def _permission_request(method: str, path: str, **kwargs: Any) -> dict:
    """Call the Permission service; non-2xx responses become ``{"error": ...}``."""
    try:
        headers = _build_headers()
    except RuntimeError as exc:
        return {"error": str(exc)}
    response = requests.request(
        method,
        _permission_url(path),
        headers=headers,
        timeout=_DEFAULT_TIMEOUT,
        **kwargs,
    )
    if response.status_code == 204:
        return {"success": True}
    body = _raw_json(response)
    if response.status_code < 400:
        return body
    return {
        "error": f"Platform permission API returned HTTP {response.status_code}",
        "detail": body,
    }


def _role_path(role_name: str) -> str:
    return f"/roles/{quote(role_name, safe='')}"


_MAX_ROLE_PAGE_SIZE = 500


def get_platform_roles(
    role_name: str | None = None,
    query: str = "",
    page_size: int = 100,
    page: int = 1,
) -> dict:
    """List Delinea Platform roles, or get one role (with its permissions) by name.

    Calls ``GET /permission/api/roles`` (roles whose name contains *query*;
    all roles when empty), one page at a time: *page* starts at 1 and
    *page_size* is capped at 500, and ``pager.total`` in the response is the
    number of matching roles. With *role_name*, calls ``GET
    /permission/api/roles/{name}`` instead. Platform Permission API
    reference: https://<tenant>/permission/swagger/v1/swagger.json
    """
    if role_name:
        return _permission_request("GET", _role_path(role_name))
    try:
        page = max(int(page), 1)
        page_size = min(max(int(page_size), 1), _MAX_ROLE_PAGE_SIZE)
    except (TypeError, ValueError):
        return {"error": "page and page_size must be positive integers"}
    params: dict[str, Any] = {"RecordsPerPage": page_size, "PageNumber": page}
    if query:
        params["Name.Contains"] = query
    return _permission_request("GET", "/roles", params=params)


def create_platform_role(
    role_name: str, description: str = "", enabled: bool = True
) -> dict:
    """Create a Delinea Platform role.

    Calls ``POST /permission/api/roles``; fails if the role exists. A new
    role has no permissions and grants nothing until it is given some in the
    Platform. Platform Permission API reference:
    https://<tenant>/permission/swagger/v1/swagger.json
    """
    body = {"roleName": role_name, "enabled": enabled, "description": description}
    return _permission_request("POST", "/roles", json=body)


def update_platform_role(role_name: str, description: str, enabled: bool) -> dict:
    """Update a Delinea Platform role's description and enabled state.

    Calls ``PUT /permission/api/roles/{name}``, which replaces both;
    ``enabled=False`` disables the role for every member. Built-in roles
    can't be changed. Platform Permission API reference:
    https://<tenant>/permission/swagger/v1/swagger.json
    """
    body = {"id": role_name, "enabled": enabled, "description": description}
    return _permission_request("PUT", _role_path(role_name), json=body)


def delete_platform_role(role_name: str) -> dict:
    """Delete a Delinea Platform role.

    Calls ``DELETE /permission/api/roles/{name}``, which also succeeds when
    no such role exists; users and groups lose the role's permissions.
    Platform Permission API reference:
    https://<tenant>/permission/swagger/v1/swagger.json
    """
    return _permission_request("DELETE", _role_path(role_name))


def get_platform_role_members(role_name: str) -> dict:
    """List the users and groups assigned to a Delinea Platform role.

    Calls ``GET /permission/api/roles/{name}/members``; members are keyed by
    user or group ID. Platform Permission API reference:
    https://<tenant>/permission/swagger/v1/swagger.json
    """
    return _permission_request("GET", f"{_role_path(role_name)}/members")


def add_platform_role_members(role_name: str, subject_ids: list[str]) -> dict:
    """Assign a Delinea Platform role to users or groups, granting its permissions.

    *subject_ids* are Platform user or group IDs (find users with
    ``search_users``). For each, calls ``PATCH
    /permission/api/role-memberships/{id}/add-role``, or ``POST
    /permission/api/role-memberships`` when the subject has no role
    assignments yet. Returns one result per subject. Platform Permission API
    reference: https://<tenant>/permission/swagger/v1/swagger.json
    """
    results = {}
    for subject_id in subject_ids:
        body = {"subjectId": subject_id, "roleName": role_name}
        path = f"/role-memberships/{quote(subject_id, safe='')}"
        result = _permission_request("PATCH", f"{path}/add-role", json=body)
        if "HTTP 404" in result.get("error", ""):
            result = _permission_request("POST", "/role-memberships", json=body)
        results[subject_id] = result
    return {"results": results}


def remove_platform_role_members(role_name: str, subject_ids: list[str]) -> dict:
    """Remove a Delinea Platform role from users or groups.

    For each of *subject_ids* (Platform user or group IDs), calls ``PATCH
    /permission/api/role-memberships/{id}/remove-role``. Returns one result
    per subject. Platform Permission API reference:
    https://<tenant>/permission/swagger/v1/swagger.json
    """
    results = {}
    for subject_id in subject_ids:
        body = {"subjectId": subject_id, "roleName": role_name}
        path = f"/role-memberships/{quote(subject_id, safe='')}/remove-role"
        results[subject_id] = _permission_request("PATCH", path, json=body)
    return {"results": results}


TOOLS = [
    ("search_users", search_users),
    ("get_platform_user", get_platform_user),
    ("create_platform_user", create_platform_user),
    ("update_platform_user", update_platform_user),
    ("delete_platform_user", delete_platform_user),
    ("get_platform_roles", get_platform_roles),
    ("create_platform_role", create_platform_role),
    ("update_platform_role", update_platform_role),
    ("delete_platform_role", delete_platform_role),
    ("get_platform_role_members", get_platform_role_members),
    ("add_platform_role_members", add_platform_role_members),
    ("remove_platform_role_members", remove_platform_role_members),
    ("platform_reports", platform_reports),
]


def register(mcp: Any, enabled: Iterable[str] | None = None) -> None:
    """Register Platform tools on an MCP server.

    Honours the same ``enabled_tools`` allowlist semantics as
    :func:`delinea_mcp.tools.register`: an empty/missing set registers
    every tool in this module; a non-empty set
    registers only the named tools. When Platform is not configured,
    registered tools still return a helpful error directing the caller
    to configure Platform or use the legacy SS-local tools.
    """
    enabled_set = set(enabled or [])
    if not enabled_set:
        enabled_set = {name for name, _ in TOOLS}
    for name, func in TOOLS:
        if name in enabled_set:
            mcp.tool(**tool_metadata(name))(guard_tool(func))
