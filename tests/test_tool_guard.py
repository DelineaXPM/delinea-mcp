import asyncio
import inspect
import json

import jsonschema  # a dependency of ``mcp`` itself
import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer

from delinea_mcp import (
    secretserver_users,
    strongdm_tools,
    tool_guard,
    tools,
    user_platform_tools,
)
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


@pytest.fixture
def result_limit(monkeypatch):
    """Set ``max_result_bytes`` for one test; restored afterwards."""
    monkeypatch.setattr(tool_guard, "_max_result_bytes", None)

    def set_limit(value):
        tool_guard.configure(value)

    return set_limit


def test_result_limit_is_off_by_default(result_limit):
    wrapped = guard_tool(lambda: {"rows": "x" * 2_000_000})
    assert len(wrapped()["rows"]) == 2_000_000


def test_result_limit_replaces_oversized_result(result_limit):
    result_limit(1000)
    wrapped = guard_tool(lambda: {"rows": ["x" * 100] * 20})
    result = wrapped()
    assert set(result) == {"error"}
    assert "Result too large" in result["error"]
    assert "max_result_bytes limit of 1000" in result["error"]
    assert str(tool_guard.result_size({"rows": ["x" * 100] * 20})) in result["error"]


def test_result_limit_passes_results_under_the_limit(result_limit):
    result_limit(1000)
    wrapped = guard_tool(lambda: {"rows": ["x"] * 5})
    assert wrapped() == {"rows": ["x"] * 5}


def test_result_limit_measures_string_results(result_limit):
    result_limit(100)
    assert guard_tool(lambda: "y" * 50)() == "y" * 50
    assert set(guard_tool(lambda: "y" * 500)()) == {"error"}


def test_result_limit_leaves_error_payloads_alone(result_limit):
    result_limit(10)

    def boom() -> dict:
        raise ValueError("short")

    assert guard_tool(boom)() == {"error": "short"}


@pytest.mark.parametrize("value", [None, 0, "", "0"])
def test_configure_disables_limit(result_limit, value):
    tool_guard.configure(5)
    tool_guard.configure(value)
    assert tool_guard._max_result_bytes is None


def test_configure_accepts_numeric_strings(result_limit):
    tool_guard.configure("524288")
    assert tool_guard._max_result_bytes == 524288


@pytest.mark.parametrize("value", [-1, "abc", True, [1]])
def test_configure_rejects_invalid_values(result_limit, value):
    with pytest.raises(ValueError, match="max_result_bytes"):
        tool_guard.configure(value)


def _call_through_sdk(func, **arguments):
    """Register ``func`` on a real MCPServer and call it via the SDK client."""
    server = MCPServer(name="guard-test")
    server.tool()(guard_tool(func))

    async def call():
        async with Client(server) as client:
            return await client.call_tool(func.__name__, arguments)

    return asyncio.run(call())


def test_result_size_matches_sdk_text_content(result_limit):
    def sample() -> dict:
        return {"rows": [{"name": 'caf\u00e9 "q"', "id": i} for i in range(50)]}

    result = _call_through_sdk(sample)
    text = result.content[0].text
    assert tool_guard.result_size(sample()) == len(json.dumps(text).encode())


def test_oversized_result_reaches_client_as_readable_error(result_limit):
    result_limit(2048)

    def report() -> dict:
        return {"rows": ["x" * 100] * 100}

    result = _call_through_sdk(report)
    assert result.is_error is False
    assert "Result too large" in result.content[0].text


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
