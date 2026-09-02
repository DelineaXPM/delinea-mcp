import inspect

from delinea_mcp import secretserver_users, tools, user_platform_tools
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
