# openwebui Integration for MCP Administration

openwebui can act as a front end for administrative tasks by connecting to the Delinea MCP server through mcpo.

## Server Configuration

Use the `stdio` transport mode.
Most administration tasks require every tool except `get_secret_environment_variable`.

```json
{
  "auth_mode": "none",
  "transport_mode": "stdio",
  "enabled_tools": [
    "search",
    "fetch",
    "run_report",
    "ai_generate_and_run_report",
    "list_example_reports",
    "get_secret",
    "get_folder",
    "get_platform_user",
    "create_platform_user",
    "get_secretserver_local_user",
    "get_roles",
    "create_role",
    "get_user_roles",
    "add_user_roles",
    "get_groups",
    "create_group",
    "get_user_groups",
    "add_user_to_groups",
    "get_group_roles",
    "create_folder",
    "health_check",
    "search_users",
    "search_secretserver_local_users",
    "search_secrets",
    "search_folders",
    "check_secret_template",
    "check_secret_template_field",
    "handle_access_request",
    "get_pending_access_requests",
    "get_inbox_messages",
    "mark_inbox_messages_read",
    "get_secret_template_field"
  ]
}
```

> [!NOTE]
> The Platform user tools (`search_users`, `get_platform_user`, ...) target
> the **Delinea Platform** identity directory and need `platform_hostname` +
> `PLATFORM_SERVICE_*` credentials configured. For Secret-Server-only
> deployments, use `search_secretserver_local_users` /
> `get_secretserver_local_user`. The list above leaves out the update,
> delete and remove tools; add them (`update_folder`, `delete_group`,
> `remove_user_roles`, ...) to allow those. Pre-3.0 names such as `role_management` still work and enable
> every replacement tool, including the destructive ones.

## Adding to openwebui

1. Install mcpo and ensure the MCP server is reachable.
2. In openwebui, create a new connection that runs mcpo with your configuration file.

## Controller Model Prompt Example

<!-- TODO: example controller model prompt -->

<!-- TODO: Screenshot of openwebui configuration -->
