# openwebui Integration for MCP Administration

openwebui can act as a front end for administrative tasks by connecting to the Delinea MCP server through mcpo.

## Server Configuration

Use the `stdio` transport mode. Most administration tasks require every tool except `get_secret_environment_variable`.

```json
{
"auth_mode": "none",
"transport_mode": "stdio",
"enabled_tools": [
  "search", "fetch", "run_report", "ai_generate_and_run_report",
  "list_example_reports", "get_secret", "get_folder",
  "user_management", "role_management", "user_role_management",
  "group_management", "user_group_management", "group_role_management",
  "folder_management", "health_check", "search_users", "search_secrets",
  "search_folders", "check_secret_template", "check_secret_template_field",
  "handle_access_request", "get_pending_access_requests",
  "get_inbox_messages", "mark_inbox_messages_read",
  "get_secret_template_field"
]
}
```

## Adding to openwebui

1. Install mcpo and ensure the MCP server is reachable.
2. In openwebui, create a new connection that runs mcpo with your configuration file.

## Controller Model Prompt Example

<!-- TODO: example controller model prompt -->

<!-- TODO: Screenshot of openwebui configuration -->

