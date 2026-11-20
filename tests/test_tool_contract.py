"""Directory review rules, checked over every tool the server can register.

https://claude.com/docs/connectors/building/review-criteria: no tool mixes
read and write operations, every tool has a title and a read-only or
destructive hint, and tools that take a caller-built request body link the
target API's documentation.
"""

from __future__ import annotations

import asyncio
import re

import pytest
from mcp.server.mcpserver import MCPServer

from delinea_mcp import server, strongdm_tools
from delinea_mcp.annotations import LEGACY_TOOL_NAMES
from delinea_mcp.session import SessionManager

# Tools with an ``action`` parameter whose actions are all reads or all
# writes. Any other tool with ``action`` is a read/write mix.
SINGLE_KIND_ACTION_TOOLS = {
    "platform_reports",  # list, describe, run, snapshots: all reads
    "sdm_access_requests",  # list, status
    "sdm_set_user_status",  # suspend, reactivate, offboard
    "secretserver_local_user_security_action",  # reset_2fa, reset_password, lock_out
}


@pytest.fixture(scope="module")
def all_tools():
    mcp = MCPServer("contract")
    mp = pytest.MonkeyPatch()
    mp.setattr(server, "mcp", mcp)
    mp.setattr(SessionManager, "_session", None)
    mp.setenv("DELINEA_SECRET_REVEAL_MODE", "true")
    for var in ("DELINEA_ENABLED_TOOLS", "DELINEA_TOOL_PRESET", "DELINEA_PASSWORD"):
        mp.delenv(var, raising=False)
    server._init_from_config({"enabled_tools": [], "platform_hostname": "x.example"})
    strongdm_tools.register(mcp, set())
    yield asyncio.run(mcp.list_tools())
    mp.undo()


def test_legacy_names_are_not_registered(all_tools):
    assert not {t.name for t in all_tools} & set(LEGACY_TOOL_NAMES)


def test_every_tool_has_title_and_hint(all_tools):
    for tool in all_tools:
        hints = tool.annotations
        assert tool.title and hints and hints.title, tool.name
        assert hints.read_only_hint or hints.destructive_hint is not None, tool.name


def test_no_tool_mixes_reads_and_writes(all_tools):
    mixed = {
        t.name
        for t in all_tools
        if "action" in t.input_schema.get("properties", {})
        and t.name not in SINGLE_KIND_ACTION_TOOLS
    }
    assert not mixed


def test_request_body_tools_link_api_docs(all_tools):
    for tool in all_tools:
        if "data" in tool.input_schema.get("properties", {}):
            assert "https://" in (tool.description or ""), tool.name


def test_tool_names_fit_the_limit(all_tools):
    assert all(len(t.name) <= 64 for t in all_tools)


# Descriptions must say what a tool does, not tell Claude how to behave.
DIRECTIVE = re.compile(
    r"\byou must\b|\balways\b|\bcall this only\b|\bbefore calling\b"
    r"|\bcall ``\w+`` first\b|\bprefer\b|\bverify .* with the (user|caller)\b"
    r"|:func:|:mod:|\b_[a-z]\w+\(?`",
    re.IGNORECASE,
)


def test_descriptions_do_not_direct_claude(all_tools):
    found = {
        t.name: m.group(0)
        for t in all_tools
        if (m := DIRECTIVE.search(t.description or ""))
    }
    assert not found
    names = {t.name for t in all_tools}
    for old, new in LEGACY_TOOL_NAMES.items():
        assert set(new) <= names, old
