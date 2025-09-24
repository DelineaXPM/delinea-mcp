# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DelineaMCP is an MCP (Model Context Protocol) server for integrating with Delinea Secret Server and Platform APIs. It provides AI assistants with secure access to secret management, user administration, and reporting capabilities through a standardized protocol.

## Development Commands

### Setup and Installation
```bash
# Install dependencies using uv (preferred)
uv pip sync requirements.txt

# Alternative with pip
pip install -r requirements.txt
```

### Running the Server
```bash
# Development mode (STDIO transport)
python server.py

# With custom config
python server.py --config config.json

# Using uv
uv run server.py --config config.json
```

### Testing
```bash
# Run all unit tests with coverage
coverage run -m pytest -q
coverage report --omit "tests/*"

# Run specific test file
pytest tests/test_tools.py

# Live integration tests (requires environment variables)
export DELINEA_PASSWORD=<password>
export LIVE_SECRET_ID=<id>
pytest tests/test_live.py
```

### Docker Development
```bash
# Build image
docker build -t dev.local/delinea-mcp:latest .

# Run server container
docker run --rm -p 8000:8000 \
  -e DELINEA_PASSWORD=<password> \
  -v $(pwd)/config.json:/app/config.json:ro \
  dev.local/delinea-mcp:latest
```

## Architecture

### Core Components

**Entry Point**: `server.py` - Thin wrapper that initializes FastMCP server and registers all tools

**Main Package**: `delinea_mcp/` contains:
- `tools.py` - Core MCP tools for Secret Server API interaction
- `user_platform_tools.py` - Delinea Platform user management tools
- `config.py` - Configuration loading utilities
- `constants.py` - Shared constants and defaults

**Authentication Module**: `delinea_mcp/auth/`
- `routes.py` - OAuth 2.0 endpoints for MCP client authentication
- `as_config.py` - Authorization server configuration and JWT handling
- `validators.py` - Token and request validation

**Transport Layer**: `delinea_mcp/transports/`
- `sse.py` - Server-Sent Events transport for HTTP-based clients

### Configuration System

Configuration is loaded from `config.json` in the project root. The `config.py` module provides a centralized loader that falls back to environment variables for sensitive data.

Key configuration patterns:
- Non-secret values in `config.json` (usernames, URLs, feature flags)
- Sensitive data via environment variables (`DELINEA_PASSWORD`, `AZURE_OPENAI_KEY`)
- Transport mode selection (`stdio` vs `sse`)
- Authentication mode (`none` vs `oauth`)

### Transport Modes

**STDIO Mode**: Direct process communication for CLI tools like Claude Desktop
**SSE Mode**: HTTP Server-Sent Events for web-based integrations like ChatGPT

The server auto-detects transport mode from configuration and initializes the appropriate handler.

### Tool Registration

Tools are dynamically registered based on:
1. Available configuration (Azure OpenAI tools only register if API keys present)
2. `enabled_tools` configuration (empty list = all tools enabled)
3. Platform tools require platform-specific configuration

## Key Integration Points

### Secret Server API
Uses the `delinea_api.DelineaSession` class for authenticated API requests. The session handles bearer token management and automatic re-authentication.

### MCP Protocol
Built on `fastmcp.FastMCP` which provides the MCP server implementation. Tools are registered as async functions with type hints for automatic schema generation.

### OAuth Flow
Implements RFC 6749 OAuth 2.0 with dynamic client registration per MCP specification. JWT tokens are signed with RSA keys generated at startup.

## Testing Strategy

- Unit tests mock API responses and focus on tool logic
- Integration tests in `tests/integration/` require live credentials
- Live tests use `LIVE_SECRET_ID` environment variable for real API calls
- All tests should maintain 100% coverage on non-test files

## Security Considerations

- OAuth redirect URI validation is minimal - production deployments must implement proper validation
- Sensitive configuration via environment variables only
- JWT keys are generated per deployment and stored in `.cache/`
- OAuth database stores client registrations in SQLite

## Dependencies

- `mcp` - Model Context Protocol implementation
- `fastapi` - HTTP server for SSE transport
- `delinea_api` - Secret Server API client (external dependency)
- `authlib` - OAuth 2.0 and JWT handling
- `httpx` - HTTP client for API requests
- `uvicorn` - ASGI server for production deployment