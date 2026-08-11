"""Legacy Secret Server local user/search tooling.

Modern Delinea cloud deployments authenticate users through the Delinea
Platform identity provider. The tools in this module talk directly to
Secret Server's own ``/v1/users`` endpoints, which only manage the
*local* user records inside Secret Server.

For Platform-integrated tenants, use :mod:`delinea_mcp.user_platform_tools`
(registered as ``user_management`` and ``search_users``) instead.

These functions are preserved under the ``secretserver_local_*`` names for
SS-only on-prem deployments and as a fallback during migration.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from delinea_mcp.annotations import TOOL_ANNOTATIONS

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

    Calls ``GET /v1/users?filter.searchText=<query>``.  In Platform-integrated
    tenants, prefer :func:`delinea_mcp.user_platform_tools.search_users`,
    which queries Platform's identity directory and is the authoritative
    user store.

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
    Platform identity directory; use the canonical ``user_management``
    tool (provided by :mod:`delinea_mcp.user_platform_tools`) instead.

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
        data,
    )
    session = SessionManager.get()

    data = _parse_json_data(data)

    try:
        if action == "get":
            if user_id is None:
                raise ValueError("user_id required for get")
            return session.request("GET", f"/v1/users/{user_id}").json()
        if action == "create":
            result = session.request("POST", "/v1/users", json=data or {}).json()
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
            result = session.request("PUT", f"/v1/users/{user_id}", json=data).json()
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
                "POST", f"/v1/users/{user_id}/password-reset", json=data
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


TOOLS = [
    ("search_secretserver_local_users", search_secretserver_local_users),
    ("secretserver_local_user_management", secretserver_local_user_management),
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
            mcp.tool(annotations=TOOL_ANNOTATIONS.get(name))(func)
