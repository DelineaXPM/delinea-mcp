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
    "role_management",
    "user_role_management",
    "group_management",
    "user_group_management",
    "group_role_management",
    "folder_management",
    "health_check",
    "search_users",
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

## Connecting from Claude

Add a custom connector pointing to the server's `/sse` endpoint and provide the OAuth client credentials.
Claude will stream tool calls and responses over SSE.

<!-- TODO: Screenshot of Claude remote connector configuration -->
