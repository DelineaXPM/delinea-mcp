"""Tool selection: presets (read-only, all, custom), config and env lists."""

from __future__ import annotations

import asyncio
import json
import os

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
        "DELINEA_TOOL_PRESET",
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
    "create_folder",
    "update_folder",
    "delete_folder",
    "update_secret_fields",
    "set_secret_field_environment_variable",
    "create_secret_with_generated_password",
    "create_platform_user",
    "update_platform_user",
    "delete_platform_user",
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
    monkeypatch.setenv("DELINEA_ENABLED_TOOLS", " get_secret , delete_folder ,")
    assert fresh() == {"get_secret", "delete_folder"}


def test_env_all_enables_everything(fresh, monkeypatch):
    monkeypatch.setenv("DELINEA_ENABLED_TOOLS", "All")
    assert WRITE_TOOLS <= fresh()


def test_config_list_beats_env(fresh, monkeypatch):
    monkeypatch.setenv("DELINEA_ENABLED_TOOLS", "folder_management")
    assert fresh({"enabled_tools": ["get_secret"]}) == {"get_secret"}


def test_explicit_empty_config_list_is_final(fresh, monkeypatch):
    """``enabled_tools: []`` means every tool; inherited env can't change it."""
    monkeypatch.setenv("DELINEA_ENABLED_TOOLS", "get_secret")
    monkeypatch.setenv("DELINEA_TOOL_PRESET", "Read-only")
    assert WRITE_TOOLS <= fresh({"enabled_tools": []})


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


# --------------------------------------------------------------------------- #
# Tool access presets (the plugin's "Tool access" picker)                     #
# --------------------------------------------------------------------------- #

READ_ONLY_EXPECTED = {
    "get_secret",
    "search_secrets",
    "search_folders",
    "get_folder",
    "search",
    "fetch",
    "health_check",
    "list_example_reports",
    "run_report",
    "get_secret_environment_variable",
    "search_users",
    "platform_reports",
    "get_roles",
    "get_groups",
    "get_user_roles",
    "get_platform_user",
}


@pytest.mark.parametrize("value", ["Read-only", "read-only", "READ_ONLY", "readonly"])
def test_read_only_preset(fresh, monkeypatch, value):
    monkeypatch.setenv("DELINEA_MCP_PLUGIN", "1")
    monkeypatch.setenv("DELINEA_TOOL_PRESET", value)
    names = fresh()
    assert READ_ONLY_EXPECTED <= names
    assert not names & WRITE_TOOLS
    assert "handle_access_request" not in names
    assert "reveal_secret_field" not in names  # still its own opt-in


def test_read_only_preset_keeps_reveal_opt_in(fresh, monkeypatch):
    monkeypatch.setenv("DELINEA_TOOL_PRESET", "Read-only")
    monkeypatch.setenv("DELINEA_SECRET_REVEAL_MODE", "true")
    assert "reveal_secret_field" in fresh()


def test_read_only_tools_are_annotated_read_only_or_listed_extras():
    from delinea_mcp.annotations import TOOL_ANNOTATIONS

    for name in server.read_only_tools() - server.READ_ONLY_EXTRA_TOOLS:
        assert TOOL_ANNOTATIONS[name].read_only_hint, name


def test_all_preset_ignores_custom_list(fresh, monkeypatch):
    monkeypatch.setenv("DELINEA_TOOL_PRESET", "All tools")
    monkeypatch.setenv("DELINEA_ENABLED_TOOLS", "get_secret")
    assert WRITE_TOOLS <= fresh()


def test_read_only_preset_ignores_custom_list(fresh, monkeypatch):
    monkeypatch.setenv("DELINEA_TOOL_PRESET", "Read-only")
    monkeypatch.setenv("DELINEA_ENABLED_TOOLS", "delete_folder")
    names = fresh()
    assert "delete_folder" not in names
    assert "get_secret" in names


def test_custom_preset_uses_list(fresh, monkeypatch):
    monkeypatch.setenv("DELINEA_TOOL_PRESET", "Custom")
    monkeypatch.setenv("DELINEA_ENABLED_TOOLS", "get_secret, delete_folder")
    assert fresh() == {"get_secret", "delete_folder"}


# --------------------------------------------------------------------------- #
# Pre-3.0 tool names expand to their replacements                             #
# --------------------------------------------------------------------------- #


def test_legacy_name_in_config_expands(fresh, caplog):
    names = fresh({"enabled_tools": ["role_management"]})
    assert names == {"get_roles", "create_role", "update_role"}
    assert "role_management" in caplog.text


def test_legacy_name_in_custom_list_keeps_reads(fresh, monkeypatch):
    monkeypatch.setenv("DELINEA_TOOL_PRESET", "Custom")
    monkeypatch.setenv("DELINEA_ENABLED_TOOLS", "folder_management")
    assert fresh() == {
        "get_folder",
        "search_folders",
        "create_folder",
        "update_folder",
        "delete_folder",
    }


def test_read_only_preset_has_no_write_replacements(fresh, monkeypatch):
    from delinea_mcp.annotations import LEGACY_TOOL_NAMES, TOOL_ANNOTATIONS

    monkeypatch.setenv("DELINEA_TOOL_PRESET", "Read-only")
    names = fresh()
    for new in LEGACY_TOOL_NAMES.values():
        for name in new:
            if name in names:
                assert TOOL_ANNOTATIONS[name].read_only_hint, name


@pytest.mark.parametrize(
    "raw, preset",
    [
        ("All tools", "all"),
        ("ALL", "all"),
        ("read_only", "read-only"),
        (" Custom ", "custom"),
        ("all-disabled", "read-only"),
        ("allow-writes", "read-only"),
        ("customize", "read-only"),
        ("---", "read-only"),
        ("", None),
        ("   ", None),
    ],
)
def test_tool_preset_matches_labels_exactly(raw, preset):
    assert server._tool_preset(raw) == preset


@pytest.mark.parametrize("preset", ["Custom", "something-else", "all-disabled"])
def test_empty_custom_or_unknown_preset_falls_back_to_read_only(
    fresh, monkeypatch, preset
):
    monkeypatch.setenv("DELINEA_TOOL_PRESET", preset)
    names = fresh()
    assert "get_secret" in names
    assert not names & WRITE_TOOLS


def test_config_preset(fresh):
    assert not fresh({"tool_preset": "read-only"}) & WRITE_TOOLS


def test_config_list_beats_preset(fresh):
    """An explicit config.json list still wins over any preset."""
    assert fresh({"tool_preset": "all", "enabled_tools": ["get_secret"]}) == {
        "get_secret"
    }


# --------------------------------------------------------------------------- #
# Plugin settings layout                                                      #
# --------------------------------------------------------------------------- #

MANIFEST = os.path.join(
    os.path.dirname(__file__),
    "..",
    "plugins",
    "delinea",
    ".claude-plugin",
    "plugin.json",
)


def _manifest():
    with open(MANIFEST) as fh:
        return json.load(fh)


def test_manifest_settings_required_first_then_optional():
    settings = _manifest()["userConfig"]
    titles = [entry["title"] for entry in settings.values()]
    optional = [t.startswith("Optional:") for t in titles]
    first_optional = optional.index(True)
    assert all(t.startswith("Required") for t in titles[:first_optional])
    assert all(optional[first_optional:])
    assert list(settings)[:4] == [
        "platform_hostname",
        "delinea_username",
        "delinea_password",
        "tool_preset",
    ]
    for key, entry in settings.items():
        if entry.get("required"):
            assert entry["title"].startswith("Required:"), key


def test_manifest_secret_server_url_is_an_optional_override():
    settings = _manifest()["userConfig"]
    assert not settings["delinea_base_url"].get("required")
    assert settings["delinea_base_url"]["title"].startswith("Optional:")


def test_manifest_tool_preset_picker_maps_to_presets():
    manifest = _manifest()
    picker = manifest["userConfig"]["tool_preset"]
    assert picker["default"] in picker["options"]
    assert [server._tool_preset(o) for o in picker["options"]] == [
        "read-only",
        "all",
        "custom",
    ]
    env = manifest["mcpServers"]["delinea"]["env"]
    assert env["DELINEA_TOOL_PRESET"] == "${user_config.tool_preset}"


def test_plugin_pins_the_package_version():
    """pyproject, the plugin version and the uvx pin move together."""
    import pathlib
    import tomllib

    root = pathlib.Path(__file__).resolve().parent.parent
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    plugin = json.loads(
        (root / "plugins/delinea/.claude-plugin/plugin.json").read_text()
    )
    assert plugin["version"] == version
    args = plugin["mcpServers"]["delinea"]["args"]
    assert f"delinea-mcp=={version}" in args
