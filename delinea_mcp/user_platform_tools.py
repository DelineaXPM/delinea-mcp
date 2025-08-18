"""
MCP tools for Platform User API integration.
"""

import json
import logging
import os

import requests

logger = logging.getLogger(__name__)


def _parse_json_data(data: dict | str | None) -> dict | None:
    """Return a dict from ``data`` when given a JSON string."""
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


_headers = None


def _build_headers():
    """Return cached headers or fetch a new OAuth token using ``requests``."""
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
        )
    except Exception as exc:
        logger.error("Failed to get token: %s", exc)
        raise RuntimeError(f"Failed to get token: {exc}")

    if response.status_code >= 400:
        logger.error("Failed to get token: %s", response.text)
        raise RuntimeError(f"Failed to get token: {response.text}")

    token_data = response.json()
    access_token = token_data["access_token"]
    _headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-MT-SecondaryId": f"{platform_tenant_id}",
    }
    return _headers


def search_platform_user(username: str) -> dict:
    """Search for a user in the Platform by username.

    Parameters
    ----------
    username:
        Username to search for.

    Returns
    -------
    dict
        JSON response from the platform user search report.
    """

    if not username:
        return {"error": "username required for search"}

    headers = _build_headers()
    url = f"https://{platform_hostname}/identity/api/Report/RunReport"
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
                    "Value": f"%{username}%",
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
        response = requests.post(url, headers=headers, json=payload)
    except Exception as exc:
        logger.exception("Failed to search platform user")
        return {"error": str(exc)}
    return _json_or_error(response)


def platform_user_management(
    action: str,
    user_id: str | None = None,
    data: dict | str | None = None,
    username: str | None = None,
) -> dict:
    """Manage users on Delinea Platform via a unified helper.

    Parameters
    ----------
    action:
        One of ``"create"``, ``"delete"``, ``"update"``, ``"get"`` or ``"search"``.
    user_id:
        Identifier used with ``"update"``, ``"delete"`` and ``"get"`` actions.
    data:
        JSON body for ``"create"`` and ``"update"``.
    username:
        Username parameter for ``"search"``.

    Returns
    -------
    dict
        Response payload or ``{"result": ..., "verification": ...}`` when a
        verifying lookup is performed.
    """

    logger.debug(
        "platform_user_management(action=%s, user_id=%s, username=%s, data=%s)",
        action,
        user_id,
        username,
        data,
    )

    headers = _build_headers()
    payload = _parse_json_data(data)

    try:
        if action == "get":
            if not user_id:
                raise ValueError("user_id required for get")
            url = f"https://{platform_hostname}/identity/UserMgmt/GetUser"
            response = requests.get(
                url,
                headers=headers,
                params={"userId": user_id},
            )
            return _json_or_error(response)

        if action == "create":
            if payload is None:
                raise ValueError("data required for create")
            url = f"https://{platform_hostname}/identity/CDirectoryService/CreateUser"
            response = requests.post(url, json=payload, headers=headers)
            result = _json_or_error(response)
            verify = search_platform_user(
                payload.get("Name") or payload.get("Username") or ""
            )
            return {"result": result, "verification": verify}

        if action == "delete":
            if not user_id:
                raise ValueError("user_id required for delete")
            url = f"https://{platform_hostname}/identity/UserMgmt/RemoveUsers"
            response = requests.post(url, json={"Users": [user_id]}, headers=headers)
            result = _json_or_error(response)
            verify = search_platform_user(user_id)
            return {"result": result, "verification": verify}

        if action == "update":
            if not user_id or payload is None:
                raise ValueError("user_id and data required for update")
            payload.setdefault("ID", user_id)
            url = f"https://{platform_hostname}/identity/CDirectoryService/ChangeUser"
            response = requests.post(url, json=payload, headers=headers)
            result = _json_or_error(response)
            verify = search_platform_user(
                payload.get("Name") or payload.get("Username") or user_id
            )
            return {"result": result, "verification": verify}

        if action == "search":
            if username is None:
                raise ValueError("username required for search")
            return search_platform_user(username)

        raise ValueError(f"Unknown action: {action}")

    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Platform user management action failed")
        return {"error": str(exc)}


TOOLS = [
    ("platform_user_management", platform_user_management),
]


def register(mcp):
    for name, func in TOOLS:
        mcp.tool()(func)
