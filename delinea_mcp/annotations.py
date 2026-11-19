"""Behaviour hints (ToolAnnotations) for every registered tool.

Clients use these to decide when to ask the human for confirmation, so
honesty beats optimism: for verb-dispatch tools whose ``action`` parameter
reaches several operations, the hints describe the *worst reachable*
action — ``user_management`` can delete, therefore it is destructive even
though it can also merely list.

All backends talk to remote Delinea/StrongDM services, so
``open_world_hint`` stays at the default (None) rather than claiming a
closed world.
"""

from __future__ import annotations

from typing import Any

from mcp.types import ToolAnnotations

# Pure reads: no state change on the backend.
_RO = ToolAnnotations(read_only_hint=True)

# Writes that only add new state (re-running creates another object).
_ADD = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False
)

# Writes that overwrite nothing irrecoverable and can be safely repeated.
_IDEM = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True
)

# Verb-dispatch tools where some reachable action deletes, disables or
# irreversibly overwrites.
_DESTR = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=False
)

TOOL_ANNOTATIONS: dict[str, ToolAnnotations] = {
    # ---- Secret Server reads
    "search": _RO,
    "fetch": _RO,
    "get_secret": _RO,
    # Reveals a plaintext password/key: never auto-approved by clients, and
    # the server additionally asks the human through MCP elicitation.
    "reveal_secret_field": ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True
    ),
    "get_folder": _RO,
    "search_secrets": _RO,
    "search_folders": _RO,
    "health_check": _RO,
    "list_example_reports": _RO,
    "check_secret_template": _RO,
    "check_secret_template_field": _RO,
    "get_secret_template_field": _RO,
    "get_pending_access_requests": _RO,
    "get_inbox_messages": _RO,
    # ---- Secret Server writes
    "run_report": _ADD,
    "create_secret_with_generated_password": _ADD,
    "handle_access_request": _ADD,  # approve/deny: state change, not data loss
    "mark_inbox_messages_read": _IDEM,
    "get_secret_environment_variable": _IDEM,  # emits a local shell script
    "set_secret_field_environment_variable": _IDEM,
    "role_management": _DESTR,
    "user_role_management": _DESTR,
    "group_management": _DESTR,
    "user_group_management": _DESTR,
    "group_role_management": _DESTR,
    "folder_management": _DESTR,
    "update_secret_fields": _DESTR,
    "update_secret_generated_password": _DESTR,  # rotates irreversibly
    "bulk_user_response": _DESTR,
    # ---- Secret Server local users (legacy)
    "search_secretserver_local_users": _RO,
    "secretserver_local_user_management": _DESTR,
    # ---- Delinea Platform
    "user_management": _DESTR,
    "search_users": _RO,
    "platform_user_management": _DESTR,  # deprecated alias of user_management
    "platform_role_management": _DESTR,
    "platform_user_role_management": _DESTR,
    "platform_reports": _RO,  # run only adds a "View" audit entry
    # ---- StrongDM. Grant/revoke change security posture, so they carry the
    # destructive hint even though granting is technically additive.
    "sdm_search": _RO,
    "sdm_audit_access": _RO,
    "sdm_grant_access": _DESTR,
    "sdm_revoke_access": _DESTR,
    "sdm_user_management": _DESTR,
    "sdm_role_management": _DESTR,
    "sdm_resource_health": _IDEM,  # triggers a healthcheck, no state destroyed
    "sdm_access_requests": _RO,
    "sdm_activity_report": _RO,
    "sdm_network_status": _RO,
}

# Human-readable display names. The Claude connector directory requires a
# ``title`` on every tool; keep this map in sync with TOOL_ANNOTATIONS.
TOOL_TITLES: dict[str, str] = {
    # ---- Secret Server reads
    "search": "Search Secret Server",
    "fetch": "Fetch Secret Server Record",
    "get_secret": "Get Secret (Passwords Masked)",
    "reveal_secret_field": "Reveal Secret Field (Requires Approval)",
    "get_folder": "Get Folder",
    "search_secrets": "Search Secrets",
    "search_folders": "Search Folders",
    "health_check": "Secret Server Health Check",
    "list_example_reports": "List Report Examples and Schema",
    "check_secret_template": "Get Secret Template",
    "check_secret_template_field": "Check Secret Template Field",
    "get_secret_template_field": "Get Secret Template Field",
    "get_pending_access_requests": "List Pending Access Requests",
    "get_inbox_messages": "List Inbox Messages",
    # ---- Secret Server writes
    "run_report": "Run SQL Report",
    "create_secret_with_generated_password": "Create Secret with Generated Password",
    "handle_access_request": "Approve or Deny Access Request",
    "mark_inbox_messages_read": "Mark Inbox Messages Read",
    "get_secret_environment_variable": "Export Secret to Environment Variables",
    "set_secret_field_environment_variable": "Set Secret Field from Local Value",
    "role_management": "Manage Roles",
    "user_role_management": "Manage User Roles",
    "group_management": "Manage Groups",
    "user_group_management": "Manage Group Membership",
    "group_role_management": "Manage Group Roles",
    "folder_management": "Manage Folders",
    "update_secret_fields": "Update Secret Fields",
    "update_secret_generated_password": "Rotate Secret Password",
    "bulk_user_response": "Bulk User Incident Response",
    # ---- Secret Server local users (legacy)
    "search_secretserver_local_users": "Search Secret Server Local Users",
    "secretserver_local_user_management": "Manage Secret Server Local Users",
    # ---- Delinea Platform
    "user_management": "Manage Platform Users",
    "search_users": "Search Platform Users",
    "platform_reports": "Browse and Run Platform Reports",
    "platform_user_management": "Manage Platform Users (Deprecated Alias)",
    "platform_role_management": "Manage Platform Roles",
    "platform_user_role_management": "Manage Platform User Roles",
    # ---- StrongDM
    "sdm_search": "Search StrongDM",
    "sdm_audit_access": "Audit StrongDM Access",
    "sdm_grant_access": "Grant StrongDM Access",
    "sdm_revoke_access": "Revoke StrongDM Access",
    "sdm_user_management": "Manage StrongDM Users",
    "sdm_role_management": "Manage StrongDM Roles",
    "sdm_resource_health": "Check StrongDM Resource Health",
    "sdm_access_requests": "List StrongDM Access Requests",
    "sdm_activity_report": "StrongDM Activity Report",
    "sdm_network_status": "StrongDM Network Status",
}


def tool_metadata(name: str) -> dict[str, Any]:
    """Return the ``mcp.tool(...)`` keyword arguments for tool *name*.

    The title is set both on the tool and inside its annotations, since
    clients read it from either place.
    """
    title = TOOL_TITLES.get(name)
    annotations = TOOL_ANNOTATIONS.get(name)
    if annotations is not None and title:
        annotations = annotations.model_copy(update={"title": title})
    return {"title": title, "annotations": annotations}
