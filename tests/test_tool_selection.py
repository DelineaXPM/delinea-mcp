import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from delinea_mcp import (
    secretserver_users,
    strongdm_tools,
    tools,
    user_platform_tools,
)
from delinea_mcp.annotations import TOOL_ANNOTATIONS

server = importlib.import_module("server")

_MODULES = (tools, secretserver_users, user_platform_tools, strongdm_tools)
_ALL = {n for m in _MODULES for n, _ in m.TOOLS}
_RO = {n for n, a in TOOL_ANNOTATIONS.items() if a.read_only_hint}


class NameMCP:
    def __init__(self):
        self.names = set()

    def tool(self, **kwargs):
        def deco(f):
            self.names.add(f.__name__)
            return f

        return deco


@pytest.fixture
def reg(monkeypatch):
    for var in (
        "DELINEA_MCP_PLUGIN",
        "DELINEA_ENABLED_TOOLS",
        "AZURE_OPENAI_ENDPOINT",
        "SDM_API_ACCESS_KEY",
        "DELINEA_USERNAME",
        "DELINEA_PASSWORD",
        "DELINEA_SECRET_SERVER_USERNAME",
        "DELINEA_SECRET_SERVER_PASSWORD",
        "DELINEA_SECRET_SERVER_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    fake = NameMCP()
    monkeypatch.setattr(server, "mcp", fake)

    def run(cfg=None):
        fake.names.clear()
        server._init_from_config(cfg or {})
        return fake.names

    return run


def test_plugin_default_is_read_only(monkeypatch, reg):
    monkeypatch.setenv("DELINEA_MCP_PLUGIN", "1")
    names = reg()
    assert names == _RO & _ALL
    assert "get_secret" in names


def test_non_plugin_registers_all(reg):
    assert reg() >= _ALL - {"ai_generate_and_run_report"}


def test_env_list_trims_and_ignores_unknown(monkeypatch, reg):
    monkeypatch.setenv("DELINEA_ENABLED_TOOLS", " get_folder , search_secrets,,nope ")
    assert reg() == {"get_folder", "search_secrets"}


@pytest.mark.parametrize("val", ["", "  ", " , ,"])
def test_blank_env_list_is_unset(monkeypatch, reg, val):
    monkeypatch.setenv("DELINEA_ENABLED_TOOLS", val)
    assert reg() >= _ALL - {"ai_generate_and_run_report"}
    monkeypatch.setenv("DELINEA_MCP_PLUGIN", "1")
    assert reg() == _RO & _ALL


def test_plugin_env_list_overrides_read_only_default(monkeypatch, reg):
    monkeypatch.setenv("DELINEA_MCP_PLUGIN", "1")
    write = "create_secret_with_generated_password"
    assert write in _ALL - _RO
    monkeypatch.setenv("DELINEA_ENABLED_TOOLS", write)
    assert reg() == {write}


def test_config_list_beats_env(monkeypatch, reg):
    monkeypatch.setenv("DELINEA_ENABLED_TOOLS", "get_folder")
    assert reg({"enabled_tools": ["search_folders"]}) == {"search_folders"}
