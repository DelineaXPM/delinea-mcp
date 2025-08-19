# Claude Desktop (Local MCP Server)

Use Claude for Desktop with a local instance of the Delinea MCP server.

## Configuration

Add an entry to `claude_desktop_config.json` pointing to the `server.py` script and your configuration file:

```json
{
  "DelineaMCP": {
    "command": "/path/to/venv/bin/python",
    "args": ["/path/to/DelineaMCP/server.py"],
    "env": {
      "DELINEA_PASSWORD": "<password>",
      "PLATFORM_SERVICE_PASSWORD": "<password>",
      "DELINEA_DEBUG": "1"
    },
    "configPath": "/path/to/config.json"
  }
}
```

Store non‑secret options in `config.json` and point `configPath` at that file.
`DELINEA_DEBUG` is optional and enables verbose logging.
Set the Azure OpenAI key only if you plan to use the AI‑powered reporting helper.

<!-- TODO: Screenshot of Claude Desktop configuration -->
