# DelineaMCP Development Guide

This document provides AI coding agents with project-specific guidance for the DelineaMCP (Model Context Protocol) server that integrates with Delinea Secret Server and Platform APIs.

## Project Overview

DelineaMCP is an MCP server built on FastMCP that provides AI assistants with secure access to Delinea Secret Server and Platform APIs.
The system supports both STDIO transport (CLI tools like Claude Desktop) and SSE transport (web-based integrations like ChatGPT) with optional OAuth 2.0 authentication.

## Development Commands

**Package Manager**: Use `uv` as the primary interface for all Python operations.
This project heavily relies on uv for dependency management, virtual environment setup, and command execution.

### Setup and Installation

```bash
# Install dependencies (preferred)
uv sync --frozen

# Alternative dependency installation
uv pip sync requirements.txt
```

### Running the Server

```bash
# Development mode (STDIO transport)
uv run server.py

# With custom configuration
uv run server.py --config config.json

# SSE mode with OAuth (requires config)
uv run server.py --config production-config.json
```

### Testing

```bash
# Run unit tests (excludes integration tests)
uv run pytest -q --ignore=tests/integration/ tests/ -k "not test_live"

# Run with coverage
uv run coverage run -m pytest -q --ignore=tests/integration/ tests/ -k "not test_live"
uv run coverage report --omit="tests/*" --show-missing

# Run specific test file
uv run pytest tests/test_tools.py

# Integration tests (need a live tenant; settings come from a local env file)
set -a; . ./.env.test-tenant.local; set +a
uv run pytest tests/integration/
```

Live test targets, in order of preference. Their env files are gitignored and
never committed:

1. **Plugin test tenant** (`.env.test-tenant.local`). A Delinea Platform tenant
   with its Secret Server vault, and one Platform service account for both.
   `LIVE_SS_VIA_PLATFORM=1` makes the vault sign in through the Platform, the
   way the plugin does. Seed the test folder, secret and role with
   `scripts/seed_test_tenant.py`, which prints the `LIVE_*` IDs.
2. **Secondary:** a separate Platform tenant (`.creds`, `PLATFORM_*`) plus a
   Secret Server that you sign in to directly (`.env.live`, `DELINEA_*` and
   `LIVE_*`). Use it to check sign-in or Platform changes against a second
   tenant.

### Build Commands

```bash
# Compile dependencies (when updating pyproject.toml)
uv pip compile pyproject.toml --universal -o requirements.txt

# Lint check
uv run python -m py_compile server.py
uv run python -m py_compile delinea_api.py
```

### Linting && Formatting

Prior to any completion of work, ensure code linting and formatting is applied with the `trunk` tool.

You can install with: `curl https://get.trunk.io -fsSL | bash -s -- -y`.

For windows usage, this should be run in `git bash` or `wsl2` or it will fail.

```bash
trunk fmt && trunk check --fix
```

### Docker Development

```bash
# Build production image
docker build -t delinea-mcp:latest .

# Run with volume mounts for persistence
docker run --rm -p 8000:8000 \
  -e DELINEA_PASSWORD=<password> \
  -v $(pwd)/config.json:/app/config.json:ro \
  -v mcp-data:/app/data \
  delinea-mcp:latest

# Docker validation
docker build -t delinea-mcp:test .
docker run --rm delinea-mcp:test python server.py --help
```

## Architecture

DelineaMCP is an MCP server built on FastMCP that provides AI assistants with secure access to Delinea Secret Server and Platform APIs.

### Core Components

**Entry Point**: `delinea_mcp/server.py` (`delinea-mcp` console script) -
initializes the MCP server and registers all tools based on configuration. The
root `server.py` and `delinea_api.py` are aliases that register the package
modules under their old names in `sys.modules`, so `import server` and
`monkeypatch.setattr(server, ...)` address the real modules.

**Claude Code plugin**: `plugins/delinea/` - `.claude-plugin/plugin.json`
launches `uvx delinea-mcp==<version>` and maps `userConfig` values to env vars;
`skills/` holds the no-secret-visibility and building-reports skills. Bump the
plugin `version` and the pinned `uvx` version together with `pyproject.toml` on
every release, and run `claude plugin validate ./plugins/delinea` (with Claude
Code 2.1.271 or later: the Tool access picker uses `options`, which older
versions reject). Settings are listed required first, titled `Required: ...`,
then optional ones titled `Optional: ...` (`userConfig` has no sections, so the
order and title prefixes are the grouping; `tests/test_plugin_tool_defaults.py`
checks it). Keep `userConfig` key names stable: renaming one loses users' saved
values. The Platform URL is the primary setting; the Secret Server URL
(`delinea_base_url`) is an override, otherwise found through the Platform's
vault broker (`DelineaSession.discover_vault_url`).
`hooks/check-deps.sh` is a check-only `SessionStart` hook (keep it free of
shell variables and installs so the directory validator doesn't hold it);
`skills/setup/` installs uv only with per-command user approval. Credential
handoff over stdio needs no external tools: `delinea_mcp/field_push.py` runs
under the server's own `sys.executable`.

**Main Package**: `delinea_mcp/` contains:

- `tools.py` - Core MCP tools for Secret Server API interaction (secrets, folders, users, groups, roles)
- `user_platform_tools.py` - Delinea Platform user management tools (optional, requires platform configuration)
- `config.py` - Configuration loading utilities with environment variable fallbacks
- `constants.py` - Large string constants for SQL generation and reporting templates

**Authentication Module**: `delinea_mcp/auth/`

- `routes.py` - OAuth 2.0 endpoints for MCP client authentication
- `as_config.py` - Authorization server configuration and JWT handling
- `validators.py` - Token and request validation

**Transport Layer**: `delinea_mcp/transports/`

- `sse.py` - Server-Sent Events transport for HTTP-based clients

### Configuration System

Configuration is loaded from `config.json` in project root. The `config.py` module provides a centralized loader that falls back to environment variables for sensitive data.

Key configuration patterns:

- Non-secret values in `config.json` (usernames, URLs, feature flags)
- Sensitive data via environment variables (`DELINEA_PASSWORD`, `PLATFORM_SERVICE_PASSWORD`); connection settings fall back to env vars when missing from `config.json` (`_ENV_FALLBACKS` in `delinea_mcp/server.py`)
- Transport mode selection (`stdio` vs `sse`)
- Authentication mode (`none` vs `oauth`)

### Transport Modes

**STDIO Mode**: Direct process communication for CLI tools like Claude Desktop

**SSE Mode**: HTTP Server-Sent Events for web-based integrations like ChatGPT

The server auto-detects transport mode from configuration and initializes the appropriate handler.

### Tool Registration

Tools are dynamically registered based on:

1. Available configuration (StrongDM tools only register with `strongdm_enabled: true`)
2. `enabled_tools` configuration (empty list = all tools enabled), then the
   tool preset (`tool_preset` / `DELINEA_TOOL_PRESET`, the plugin's "Tool
   access" picker: `read-only`, `all`, `custom` with `DELINEA_ENABLED_TOOLS`);
   see `_select_tools` in `delinea_mcp/server.py`
3. Platform tools require platform-specific configuration

## Key Integration Points

### Secret Server API

Uses the `delinea_mcp.api.DelineaSession` class for authenticated API requests.
The session handles bearer token management and automatic re-authentication, and
raises `DelineaAPIError` (a `requests.HTTPError`) whose message carries the
API's error text, `errorCode` and a next-step hint.

### MCP Protocol

Built on `fastmcp.FastMCP` which provides the MCP server implementation. Tools are registered as async functions with type hints for automatic schema generation.

### OAuth Flow

Implements RFC 6749 OAuth 2.0 with dynamic client registration per MCP specification. JWT tokens are signed with RSA keys generated at startup.

## Testing Strategy

**Unit Test Focus**:

- Unit tests mock API responses and focus on tool logic
- Integration tests in `tests/integration/` require live credentials
- Live tests use `LIVE_SECRET_ID` environment variable for real API calls
- All tests should maintain 100% coverage on non-test files

**Testing Architecture**:

- Unit tests mock all external dependencies using `monkeypatch` fixtures
- Integration tests in `tests/integration/` require live credentials and are excluded from CI
- Extensive use of `DummySession`, `DummyResponse`, and `DummyMCP` mock classes
- Tests use `sys.path.insert()` to import modules and `importlib.reload()` for clean state
- All network-dependent code is mocked; tests should run without external connections

**Mock Patterns**:

```python
# Mock DelineaSession for API calls
class DummySession:
    def request(self, method, path, **kwargs):
        return DummyResponse({"result": "mocked"})

monkeypatch.setattr(tools, "delinea", DummySession())

# Mock environment variables
monkeypatch.setenv("DELINEA_PASSWORD", "test")

# Test configuration loading
cfg = tmp_path / "config.json"
cfg.write_text(json.dumps({"auth_mode": "none"}))
```

**Integration Test Requirements**:

- Located in `tests/integration/` directory
- Require `DELINEA_PASSWORD` environment variable
- Use `LIVE_SECRET_ID` and related credentials for real API testing
- Excluded from CI but available for local verification

## Security Considerations

**MCP Security Compliance**: Review and implement security practices from [MCP Security Best Practices](https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices):

## Development Patterns

**MCP Tool Development**:

- Tools registered via `@mcp.tool()` decorator with type hints for automatic schema generation
- Follow naming convention: verb_noun (e.g., `get_secret`, `search_users`, `user_management`)
- Include comprehensive docstrings with Parameters and Returns sections
- Return dictionaries with `error` key on failures, structured data on success
- Use `logger.debug()` for operation logging with descriptive messages

**Configuration Patterns**:

```python
# Load configuration with fallbacks
def _cfg_or_env(key: str) -> str | None:
    return _CFG.get(key) or os.getenv(key)

```

**Directory-readiness rules** (Claude connector/plugin directory review):

- Every tool needs an entry in both `TOOL_ANNOTATIONS` and `TOOL_TITLES`
  (`delinea_mcp/annotations.py`); register tools with
  `mcp.tool(**tool_metadata(name))(guard_tool(func))`.
- Never return plaintext secret values: mask via `_mask_secret`, reveal only
  through `reveal_secret_field` (elicitation-gated via `Resolve`/`Elicit`).
- List/search tools must page (`_paged`) and bound output.

## Dependencies

- `mcp` - Model Context Protocol implementation
- `fastapi` - HTTP server for SSE transport
- `requests` - Secret Server / Platform HTTP client (`delinea_mcp/api.py`)
- `joserfc` - JWT signing and verification (JOSE)
- `httpx` - HTTP client for API requests
- `uvicorn` - ASGI server for production deployment

## External Context

**MCP Inspector Usage**:

```bash
# Launch MCP Inspector UI (requires Node.js)
npx @modelcontextprotocol/inspector
```

**Key External References**:

- [MCP Security Best Practices](https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices) - Critical for security implementations
- FastMCP documentation for server implementation patterns
- Delinea Secret Server API documentation in `docs/delinea-secret-server-openapi-spec.json`

**Client Integration Examples**:

- Claude Desktop: `docs/claude-desktop.md`
- ChatGPT Custom Connector: `docs/chatgpt-connector.md`
- VSCode Copilot: `docs/vscode-copilot.md`
- OpenWebUI: `docs/openwebui-admin.md`
