# Claude Desktop (Local MCP Server)

Use Claude for Desktop with a local instance of the Delinea MCP server.

## Configuration

The simplest setup runs the published package with `uvx`. Add an entry to
`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "delinea": {
      "command": "uvx",
      "args": ["--no-config", "delinea-mcp==3.0.0"],
      "env": {
        "DELINEA_BASE_URL": "https://example.secretservercloud.com",
        "DELINEA_USERNAME": "<username>",
        "DELINEA_PASSWORD": "<password>",
        "DELINEA_MCP_CONFIG": "/path/to/config.json"
      }
    }
  }
}
```

`DELINEA_MCP_CONFIG` is optional; use it to point at a `config.json` with
non-secret options such as `enabled_tools`. To run from a source checkout
instead, set `command` to the checkout's Python interpreter and `args` to
`["/path/to/delinea-mcp/server.py"]`.

Claude Desktop shows the server's confirmation prompt when
`reveal_secret_field` asks you to approve a plaintext reveal. In Claude
Code, prefer the [plugin](../plugins/delinea/README.md), which stores the
password in your operating system's credential store.

<!-- TODO: Screenshot of Claude Desktop configuration -->
