# Remote Claude Connector (SSE + OAuth)

This document describes how to expose the Delinea MCP server over HTTPS/SSE and connect from a remote Claude client using OAuth authentication.

## Server Configuration

Enable OAuth with SSE transport in `config.json`.
Two common configurations are shown below.

### Reporting Only

Expose only the reporting tools for read‑only access.

```json
{
  "auth_mode": "oauth",
  "transport_mode": "sse",
  "external_hostname": "example.com",
  "registration_psk": "<shared secret>",
  "enabled_tools": [
    "run_report",
    "ai_generate_and_run_report",
    "list_example_reports"
  ]
}
```

### Administration

Allow all tools except `get_secret_environment_variable`.

```json
{
  "auth_mode": "oauth",
  "transport_mode": "sse",
  "external_hostname": "example.com",
  "registration_psk": "<shared secret>",
  "enabled_tools": [
    "search",
    "fetch",
    "run_report",
    "ai_generate_and_run_report",
    "list_example_reports",
    "get_secret",
    "get_folder",
    "get_platform_user",
    "create_or_update_platform_user",
    "get_secretserver_local_user",
    "get_roles",
    "create_or_update_role",
    "get_user_roles",
    "add_user_roles",
    "get_groups",
    "create_group",
    "get_user_groups",
    "add_user_to_groups",
    "get_group_roles",
    "create_or_update_folder",
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
> `get_secretserver_local_user`. The list above leaves out the delete and
> remove tools; add them (`delete_group`, `remove_user_roles`, ...) to allow
> those. Pre-3.0 names such as `role_management` still work and enable
> every replacement tool, including the destructive ones.

## Connecting from Claude

Add a custom connector pointing to the server's `/mcp` endpoint (streamable
HTTP, the current MCP transport) and provide the OAuth client credentials.
Older clients that only speak HTTP+SSE can use the legacy `/mcp/sse`
endpoint instead.

<!-- TODO: Screenshot of Claude remote connector configuration -->
