"""Behaviour hints (ToolAnnotations) for every registered tool.

Clients use these to decide when to ask the human for confirmation, so
honesty beats optimism: a tool is only non-destructive when every call
adds state. Creating is additive; updating overwrites, so update tools are
destructive, and a tool whose ``action`` reaches several operations gets
the hints of the *worst reachable* one.

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

# Writes that only add (or flip a flag the same tool can flip back) and can
# be safely repeated.
_IDEM = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True
)

# Writes that delete, disable or overwrite existing data. Per the MCP spec,
# anything that isn't purely additive is destructive, so every update tool
# carries this.
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
    "handle_access_request": _DESTR,  # approve grants access; final either way
    "mark_inbox_messages_read": _IDEM,
    "get_secret_environment_variable": _IDEM,  # emits a local shell script
    "set_secret_field_environment_variable": _DESTR,  # overwrites the field
    "get_roles": _RO,
    "create_role": _ADD,
    "update_role": _DESTR,  # overwrites; can disable the role
    "get_user_roles": _RO,
    "add_user_roles": _IDEM,
    "remove_user_roles": _DESTR,
    "get_groups": _RO,
    "create_group": _ADD,
    "delete_group": _DESTR,
    "get_user_groups": _RO,
    "add_user_to_groups": _IDEM,
    "remove_user_from_groups": _DESTR,
    "get_group_roles": _RO,
    "add_group_roles": _IDEM,
    "remove_group_roles": _DESTR,
    "create_folder": _ADD,
    "update_folder": _DESTR,  # overwrites; can move or re-permission
    "delete_folder": _DESTR,
    "update_secret_fields": _DESTR,
    "update_secret_generated_password": _DESTR,  # rotates irreversibly
    "bulk_user_response": _DESTR,
    # ---- Secret Server local users (legacy)
    "search_secretserver_local_users": _RO,
    "get_secretserver_local_user": _RO,
    "list_secretserver_user_sessions": _RO,
    "create_secretserver_local_user": _ADD,
    "update_secretserver_local_user": _DESTR,  # can disable, lock, re-password
    "delete_secretserver_local_user": _DESTR,
    "secretserver_local_user_security_action": _DESTR,  # resets, lock-out
    # ---- Delinea Platform
    "search_users": _RO,
    "get_platform_user": _RO,
    "create_platform_user": _ADD,
    "update_platform_user": _DESTR,  # can disable or re-password
    "delete_platform_user": _DESTR,
    "get_platform_roles": _RO,
    "create_platform_role": _ADD,  # fails if the role exists
    "update_platform_role": _DESTR,  # can disable the role
    "delete_platform_role": _DESTR,
    "get_platform_role_members": _RO,
    "add_platform_role_members": _IDEM,
    "remove_platform_role_members": _DESTR,
    "platform_reports": _RO,  # run only adds a "View" audit entry
    # ---- StrongDM. Grant/revoke change security posture, so they carry the
    # destructive hint even though granting is technically additive.
    "sdm_search": _RO,
    "sdm_audit_access": _RO,
    "sdm_grant_access": _DESTR,
    "sdm_revoke_access": _DESTR,
    "sdm_get_users": _RO,
    "sdm_create_user": _DESTR,  # onboarding attaches roles, granting access
    "sdm_set_user_status": _DESTR,
    "sdm_delete_user": _DESTR,
    "sdm_get_roles": _RO,
    "sdm_create_role": _ADD,  # an empty role grants nothing
    "sdm_delete_role": _DESTR,
    "sdm_add_role_member": _DESTR,
    "sdm_remove_role_member": _DESTR,
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
    "get_roles": "Get Roles",
    "create_role": "Create Role",
    "update_role": "Update Role",
    "get_user_roles": "Get User Roles",
    "add_user_roles": "Add Roles to User",
    "remove_user_roles": "Remove Roles from User",
    "get_groups": "Get Groups",
    "create_group": "Create Group",
    "delete_group": "Delete Group",
    "get_user_groups": "Get User Groups",
    "add_user_to_groups": "Add User to Groups",
    "remove_user_from_groups": "Remove User from Groups",
    "get_group_roles": "Get Group Roles",
    "add_group_roles": "Add Roles to Group",
    "remove_group_roles": "Remove Roles from Group",
    "create_folder": "Create Folder",
    "update_folder": "Update Folder",
    "delete_folder": "Delete Folder",
    "update_secret_fields": "Update Secret Fields",
    "update_secret_generated_password": "Rotate Secret Password",
    "bulk_user_response": "Bulk User Incident Response",
    # ---- Secret Server local users (legacy)
    "search_secretserver_local_users": "Search Secret Server Local Users",
    "get_secretserver_local_user": "Get Secret Server Local User",
    "list_secretserver_user_sessions": "List Secret Server User Sessions",
    "create_secretserver_local_user": "Create Secret Server Local User",
    "update_secretserver_local_user": "Update Secret Server Local User",
    "delete_secretserver_local_user": "Delete Secret Server Local User",
    "secretserver_local_user_security_action": "Reset or Lock Out Secret Server Local User",
    # ---- Delinea Platform
    "search_users": "Search Platform Users",
    "platform_reports": "Browse and Run Platform Reports",
    "get_platform_user": "Get Platform User",
    "create_platform_user": "Create Platform User",
    "update_platform_user": "Update Platform User",
    "delete_platform_user": "Delete Platform User",
    "get_platform_roles": "Get Platform Roles",
    "create_platform_role": "Create Platform Role",
    "update_platform_role": "Update Platform Role",
    "delete_platform_role": "Delete Platform Role",
    "get_platform_role_members": "Get Platform Role Members",
    "add_platform_role_members": "Add Platform Role Members",
    "remove_platform_role_members": "Remove Platform Role Members",
    # ---- StrongDM
    "sdm_search": "Search StrongDM",
    "sdm_audit_access": "Audit StrongDM Access",
    "sdm_grant_access": "Grant StrongDM Access",
    "sdm_revoke_access": "Revoke StrongDM Access",
    "sdm_get_users": "Get StrongDM Users",
    "sdm_create_user": "Create StrongDM User",
    "sdm_set_user_status": "Suspend, Reactivate or Offboard StrongDM User",
    "sdm_delete_user": "Delete StrongDM User",
    "sdm_get_roles": "Get StrongDM Roles",
    "sdm_create_role": "Create StrongDM Role",
    "sdm_delete_role": "Delete StrongDM Role",
    "sdm_add_role_member": "Add StrongDM Role Member",
    "sdm_remove_role_member": "Remove StrongDM Role Member",
    "sdm_resource_health": "Check StrongDM Resource Health",
    "sdm_access_requests": "List StrongDM Access Requests",
    "sdm_activity_report": "StrongDM Activity Report",
    "sdm_network_status": "StrongDM Network Status",
}


# Pre-3.0 tools that mixed reads and writes behind an ``action`` parameter,
# mapped to the tools that replaced them. An old name in an allowlist
# expands to these so existing configurations keep every capability.
LEGACY_TOOL_NAMES: dict[str, tuple[str, ...]] = {
    "role_management": ("get_roles", "create_role", "update_role"),
    "user_role_management": ("get_user_roles", "add_user_roles", "remove_user_roles"),
    "group_management": ("get_groups", "create_group", "delete_group"),
    "user_group_management": (
        "get_user_groups",
        "add_user_to_groups",
        "remove_user_from_groups",
    ),
    "group_role_management": (
        "get_group_roles",
        "add_group_roles",
        "remove_group_roles",
    ),
    "folder_management": (
        "get_folder",
        "search_folders",
        "create_folder",
        "update_folder",
        "delete_folder",
    ),
    "secretserver_local_user_management": (
        "get_secretserver_local_user",
        "list_secretserver_user_sessions",
        "create_secretserver_local_user",
        "update_secretserver_local_user",
        "delete_secretserver_local_user",
        "secretserver_local_user_security_action",
    ),
    "user_management": (
        "search_users",
        "get_platform_user",
        "create_platform_user",
        "update_platform_user",
        "delete_platform_user",
    ),
    "platform_role_management": (
        "get_platform_roles",
        "create_platform_role",
        "update_platform_role",
        "delete_platform_role",
    ),
    "platform_user_role_management": (
        "get_platform_role_members",
        "add_platform_role_members",
        "remove_platform_role_members",
    ),
    "sdm_user_management": (
        "sdm_get_users",
        "sdm_create_user",
        "sdm_set_user_status",
        "sdm_delete_user",
    ),
    "sdm_role_management": (
        "sdm_get_roles",
        "sdm_create_role",
        "sdm_delete_role",
        "sdm_add_role_member",
        "sdm_remove_role_member",
    ),
}
LEGACY_TOOL_NAMES["platform_user_management"] = LEGACY_TOOL_NAMES["user_management"]


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
