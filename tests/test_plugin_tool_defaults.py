"""Tool selection: every tool by default, narrowed by config or env."""

from __future__ import annotations

import asyncio

import pytest
from mcp.server.mcpserver import MCPServer

from delinea_mcp import server, tools
from delinea_mcp.session import SessionManager


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


@pytest.mark.parametrize("plugin", ["1", ""])
def test_default_is_every_tool(fresh, monkeypatch, plugin):
    if plugin:
        monkeypatch.setenv("DELINEA_MCP_PLUGIN", plugin)
    names = fresh()
    assert WRITE_TOOLS <= names
    assert {"get_secret", "get_secret_environment_variable", "run_report"} <= names
    assert "reveal_secret_field" not in names  # its own opt-in


def test_blank_setting_means_every_tool(fresh, monkeypatch):
    """The plugin substitutes an empty string when the setting is blank."""
    monkeypatch.setenv("DELINEA_MCP_PLUGIN", "1")
    monkeypatch.setenv("DELINEA_ENABLED_TOOLS", "")
    assert WRITE_TOOLS <= fresh()


def test_env_allowlist_narrows(fresh, monkeypatch):
    monkeypatch.setenv("DELINEA_MCP_PLUGIN", "1")
    monkeypatch.setenv("DELINEA_ENABLED_TOOLS", " get_secret , folder_management ,")
    assert fresh() == {"get_secret", "folder_management"}


def test_env_all_enables_everything(fresh, monkeypatch):
    monkeypatch.setenv("DELINEA_ENABLED_TOOLS", "All")
    assert WRITE_TOOLS <= fresh()


def test_config_list_beats_env(fresh, monkeypatch):
    monkeypatch.setenv("DELINEA_ENABLED_TOOLS", "folder_management")
    assert fresh({"enabled_tools": ["get_secret"]}) == {"get_secret"}


def test_platform_tools_reuse_main_account(fresh, monkeypatch):
    """One Platform service account serves the vault and the Platform tools."""
    from delinea_mcp import user_platform_tools

    seen = {}
    monkeypatch.setattr(
        user_platform_tools, "configure", lambda **kw: seen.update(kw) or None
    )
    monkeypatch.setattr(server, "DelineaSession", lambda **kw: object())
    monkeypatch.setenv("DELINEA_USERNAME", "svc-client")
    monkeypatch.setenv("DELINEA_PASSWORD", "svc-secret")
    monkeypatch.setenv("PLATFORM_HOSTNAME", "acme.delinea.app")
    monkeypatch.setenv("PLATFORM_SERVICE_ACCOUNT", "")
    monkeypatch.setenv("PLATFORM_SERVICE_PASSWORD", "")
    fresh()
    assert seen["service_account"] == "svc-client"
    assert seen["service_password"] == "svc-secret"


def test_separate_platform_account_wins(fresh, monkeypatch):
    from delinea_mcp import user_platform_tools

    seen = {}
    monkeypatch.setattr(
        user_platform_tools, "configure", lambda **kw: seen.update(kw) or None
    )
    monkeypatch.setattr(server, "DelineaSession", lambda **kw: object())
    monkeypatch.setenv("DELINEA_USERNAME", "vault-user")
    monkeypatch.setenv("DELINEA_PASSWORD", "vault-pw")
    monkeypatch.setenv("PLATFORM_HOSTNAME", "acme.delinea.app")
    monkeypatch.setenv("PLATFORM_SERVICE_ACCOUNT", "platform-svc")
    monkeypatch.setenv("PLATFORM_SERVICE_PASSWORD", "platform-pw")
    fresh()
    assert seen["service_account"] == "platform-svc"
