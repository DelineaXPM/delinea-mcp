# MCP Implementation Plan

This document outlines the steps required to implement a Model Context Protocol (MCP) server for Delinea Secret Server API. It is based on the [python-sdk quickstart](https://github.com/modelcontextprotocol/python-sdk#quickstart).

## 1. Install MCP Python SDK

Use `pip` or `uv` to install the SDK:

```bash
pip install mcp
# or
uv pip install mcp
```

## 2. Create the server

Create a `server.py` file that sets up a `FastMCP` server. Example from the quickstart:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("DelineaMCP")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b

@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Return a greeting"""
    return f"Hello, {name}!"
```

This skeleton will be extended with tools that interface with the Secret Server API.

## 3. Expose Secret Server functionality

1. **Authentication**: Implement OAuth 2.0 or token-based auth for secure access.
2. **Resources**: Map Secret Server data (e.g., secrets, folders) to MCP resources.
3. **Tools**: Create tools for creating, updating, and deleting secrets.

## 4. Testing

Use `python server.py` to run the server locally. Integrate unit tests to ensure API endpoints behave correctly.

## 5. Deployment

Package dependencies and provide installation instructions using `mcp install` so that clients can interact with the server via MCP.

## 6. Future work

Based on the project TODO list in the README:

1. Document a workflow that injects secrets at runtime when used with agentic
   coding tools like GitHub Copilot or Cursor. Ideally record a demo of the
   process.
2. Extend support beyond Secret Server and expose relevant Delinea platform
   APIs.
3. Increase Secret Server coverage by adding more API endpoints.
4. Thoroughly test the AI report generation helper.
5. Improve MCP text responses to act as helpful prompts for clients.
6. Split the report examples tool into smaller pieces so that it does not fill
   the context window.
7. Add the ability to build different MCP versions using copies of the server
   code.
8. Document usage with other tools besides Claude Desktop, both for local
   execution and via Docker.
