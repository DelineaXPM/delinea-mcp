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
    "user_management",
    "secretserver_local_user_management",
    "role_management",
    "user_role_management",
    "group_management",
    "user_group_management",
    "group_role_management",
    "folder_management",
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
> Since v1.0.0 `user_management` and `search_users` target the **Delinea
> Platform** identity directory and need `platform_hostname` +
> `PLATFORM_SERVICE_*` credentials configured. For Secret-Server-only
> deployments, the SS-local equivalents in the list above are
> `secretserver_local_user_management` / `search_secretserver_local_users`.

## Connecting from Claude

Add a custom connector pointing to the server's `/mcp` endpoint (streamable
HTTP, the current MCP transport) and provide the OAuth client credentials.
Older clients that only speak HTTP+SSE can use the legacy `/mcp/sse`
endpoint instead.

<!-- TODO: Screenshot of Claude remote connector configuration -->
