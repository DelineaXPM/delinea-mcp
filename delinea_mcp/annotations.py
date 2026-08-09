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
    "ai_generate_and_run_report": _ADD,
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
