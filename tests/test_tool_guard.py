import inspect
import json

import jsonschema  # a dependency of ``mcp`` itself
import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer

from delinea_mcp import secretserver_users, strongdm_tools, tools, user_platform_tools
from delinea_mcp.session import SessionManager
from delinea_mcp.tool_guard import guard_tool


class RecordingMCP:
    """Capture the callables handed to ``mcp.tool`` at registration."""

    def __init__(self):
        self.tools = {}

    def tool(self, **kwargs):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


def test_guard_tool_passes_through_results():
    def sample(a: int, b: int = 2) -> dict:
        return {"sum": a + b}

    wrapped = guard_tool(sample)
    assert wrapped(1) == {"sum": 3}


def test_guard_tool_converts_exceptions_to_error_payload():
    def boom() -> dict:
        raise ValueError("user_id required for get")

    wrapped = guard_tool(boom)
    assert wrapped() == {"error": "user_id required for get"}


def test_guard_tool_preserves_introspection():
    def sample(a: int, b: str = "x") -> dict:
        """Docstring the MCP server advertises."""
        return {}

    wrapped = guard_tool(sample)
    assert wrapped.__name__ == "sample"
    assert wrapped.__doc__ == sample.__doc__
    assert inspect.signature(wrapped) == inspect.signature(sample)


def test_registered_tool_reports_uninitialised_session(monkeypatch):
    mcp = RecordingMCP()
    tools.register(mcp, {"get_secret"})
    monkeypatch.setattr(SessionManager, "_session", None)
    result = mcp.tools["get_secret"](1)
    assert set(result) == {"error"}
    assert "session" in result["error"].lower()


def test_registered_tool_reports_invalid_json(monkeypatch):
    mcp = RecordingMCP()
    user_platform_tools.register(mcp, {"user_management"})
    monkeypatch.setattr(user_platform_tools, "_build_headers", lambda: {})
    result = mcp.tools["user_management"](action="get", user_id="u", data="{not json")
    assert result == {"error": "Invalid JSON data"}


def test_registered_ss_local_tool_reports_uninitialised_session(monkeypatch):
    mcp = RecordingMCP()
    secretserver_users.register(mcp, {"secretserver_local_user_management"})
    monkeypatch.setattr(SessionManager, "_session", None)
    result = mcp.tools["secretserver_local_user_management"](action="get", user_id=1)
    assert set(result) == {"error"}


# --- SDK output-schema interplay -------------------------------------------
#
# ``MCPServer.tool()`` derives an ``outputSchema`` from the return annotation
# and validates every result against it. ``guard_tool`` returns
# ``{"error": ...}`` on failure, so that payload must satisfy the schema of
# every registered tool or the SDK discards the detail and the client sees
# only ``Error executing tool <name>`` (the exact regression #61 fixed).


def _server_with_all_tools() -> MCPServer:
    mcp = MCPServer("delinea-test")
    for module in (tools, secretserver_users, user_platform_tools, strongdm_tools):
        module.register(mcp)
    return mcp


def _guard_payload_fits(schema: dict) -> bool:
    """True if ``{"error": ...}`` validates, plain or SDK-wrapped in ``result``."""
    payload = {"error": "boom"}
    for candidate in (payload, {"result": payload}):
        try:
            jsonschema.validate(candidate, schema)
            return True
        except jsonschema.ValidationError:
            continue
    return False


@pytest.mark.asyncio
async def test_every_registered_tool_schema_accepts_guard_error_payload():
    async with Client(_server_with_all_tools()) as client:
        listed = (await client.list_tools()).tools
    assert listed, "no tools registered"
    offenders = [
        f"{tool.name}: {tool.output_schema}"
        for tool in listed
        if tool.output_schema is not None
        and not _guard_payload_fits(tool.output_schema)
    ]
    assert not offenders, "\n".join(offenders)


@pytest.mark.asyncio
async def test_search_error_detail_survives_output_validation(monkeypatch):
    # A malformed backend payload makes ``search`` raise inside the loop.
    monkeypatch.setattr(tools, "_SEARCH_ALLOWED", {"secret"})
    monkeypatch.setattr(tools, "search_secrets", lambda query: {"records": None})
    mcp = MCPServer("delinea-test")
    tools.register(mcp, {"search"})
    async with Client(mcp) as client:
        result = await client.call_tool("search", {"query": "x"})
    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert set(payload) == {"error"}
    assert "NoneType" in payload["error"]


@pytest.mark.asyncio
async def test_fetch_error_detail_survives_output_validation():
    mcp = MCPServer("delinea-test")
    tools.register(mcp, {"fetch"})
    async with Client(mcp) as client:
        result = await client.call_tool("fetch", {"id": "no-slash"})
    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload == {"error": "identifier must be in '<type>/<id>' format"}
