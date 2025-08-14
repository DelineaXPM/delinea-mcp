# VSCode Copilot with Local MCP

VSCode Copilot can use the Delinea MCP server to inject secrets at runtime. Configure Copilot to launch the local MCP server in the same way as Claude for Desktop.

## Configuration

Add the server to your Copilot configuration file (for example `~/.config/copilot/mcp.json`):

```json
{
  "servers": {
    "delinea": {
      "command": "/path/to/venv/bin/python",
      "args": ["/path/to/DelineaMCP/server.py"],
      "env": {
        "DELINEA_PASSWORD": "<password>"
      },
      "configPath": "/path/to/config.json"
    }
  }
}
```

Limit the server to the tools required for coding agents:
`get_secret_environment_variable`, `search_secrets`, `check_secret_template`,
`check_secret_template_field` and `get_secret_template_field`.

```json
{
  "enabled_tools": [
    "get_secret_environment_variable",
    "search_secrets",
    "check_secret_template",
    "check_secret_template_field",
    "get_secret_template_field"
  ]
}
```

<!-- TODO: Screenshot of Copilot configuration -->

