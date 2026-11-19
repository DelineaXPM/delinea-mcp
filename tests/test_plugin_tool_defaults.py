"""Tool selection: read-only plugin default, env allowlist, config precedence."""

from __future__ import annotations

import asyncio

import pytest
from delinea_mcp import server, tools
from delinea_mcp.annotations import TOOL_ANNOTATIONS
from delinea_mcp.session import SessionManager
from mcp.server.mcpserver import MCPServer


@pytest.fixture
def fresh(monkeypatch):
    """Register into a new server with no session and a clean environment."""
    mcp = MCPServer("t")
    monkeypatch.setattr(server, "mcp", mcp)
    monkeypatch.setattr(SessionManager, "_session", None)
    for var in (
        "DELINEA_MCP_PLUGIN",
        "DELINEA_ENABLED_TOOLS",
        "DELINEA_SECRET_REVEAL_MODE",
        "DELINEA_USERNAME",
        "DELINEA_PASSWORD",
        "PLATFORM_HOSTNAME",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delitem(tools._CFG, "secret_reveal_mode", raising=False)

    def names(cfg=None):
        server._init_from_config(cfg or {})
        return {t.name for t in asyncio.run(mcp.list_tools())}

    return names


WRITE_TOOLS = {
    "folder_management",
    "update_secret_fields",
    "set_secret_field_environment_variable",
    "create_secret_with_generated_password",
    "user_management",
    "bulk_user_response",
}


def test_plugin_default_is_read_only_plus_handoff_and_reports(fresh, monkeypatch):
    monkeypatch.setenv("DELINEA_MCP_PLUGIN", "1")
    names = fresh()
    assert {"get_secret", "search_secrets", "list_example_reports"} <= names
    assert {"get_secret_environment_variable", "run_report"} <= names
    assert not names & WRITE_TOOLS
    # Every registered tool is read-only or one of the documented exceptions.
    for name in names:
        assert (
            TOOL_ANNOTATIONS[name].read_only_hint
            or name in server.PLUGIN_DEFAULT_EXTRA_TOOLS
        ), name
    assert "reveal_secret_field" not in names  # reveal stays off by default


def test_plugin_default_keeps_explicit_reveal_opt_in(fresh, monkeypatch):
    monkeypatch.setenv("DELINEA_MCP_PLUGIN", "1")
    monkeypatch.setenv("DELINEA_SECRET_REVEAL_MODE", "true")
    names = fresh()
    assert "reveal_secret_field" in names
    assert not names & WRITE_TOOLS


def test_env_allowlist_and_all(fresh, monkeypatch):
    monkeypatch.setenv("DELINEA_MCP_PLUGIN", "1")
    monkeypatch.setenv("DELINEA_ENABLED_TOOLS", " get_secret , folder_management ,")
    assert fresh() == {"get_secret", "folder_management"}


def test_env_all_enables_everything(fresh, monkeypatch):
    monkeypatch.setenv("DELINEA_MCP_PLUGIN", "1")
    monkeypatch.setenv("DELINEA_ENABLED_TOOLS", "All")
    assert WRITE_TOOLS <= fresh()


def test_config_list_beats_env(fresh, monkeypatch):
    monkeypatch.setenv("DELINEA_ENABLED_TOOLS", "folder_management")
    assert fresh({"enabled_tools": ["get_secret"]}) == {"get_secret"}


def test_standalone_default_is_unchanged(fresh):
    """Outside plugin mode an empty allowlist still means every tool."""
    assert WRITE_TOOLS <= fresh()
