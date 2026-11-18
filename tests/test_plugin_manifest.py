"""Guard the Claude Code plugin manifests (plugin/, .claude-plugin/)."""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text())


def test_mcp_json_is_exactly_expected():
    # Exact equality so no extra uvx flags (--from, --with, --index), servers or
    # env can slip in, and DELINEA_MCP_PLUGIN stays the string "1".
    assert _load("plugin/.mcp.json") == {
        "mcpServers": {
            "delinea": {
                "command": "uvx",
                "args": ["--no-config", "--python", "3.13", f"delinea-mcp=={VERSION}"],
                "env": {
                    "DELINEA_MCP_PLUGIN": "1",
                    "DELINEA_SECRET_SERVER_URL": "${user_config.secret_server_url}",
                    "DELINEA_SECRET_SERVER_USERNAME": "${user_config.secret_server_username}",
                    "DELINEA_SECRET_SERVER_PASSWORD": "${user_config.secret_server_password}",
                    "PLATFORM_HOSTNAME": "${user_config.platform_hostname}",
                    "PLATFORM_SERVICE_ACCOUNT": "${user_config.platform_service_account}",
                    "PLATFORM_SERVICE_PASSWORD": "${user_config.platform_service_password}",
                    "PLATFORM_TENANT_ID": "${user_config.platform_tenant_id}",
                    "DELINEA_ENABLED_TOOLS": "${user_config.enabled_tools}",
                },
            }
        }
    }


def test_plugin_and_marketplace_versions_match_pyproject():
    assert _load("plugin/.claude-plugin/plugin.json")["version"] == VERSION
    entries = [
        p
        for p in _load(".claude-plugin/marketplace.json")["plugins"]
        if p["name"] == "delinea"
    ]
    assert len(entries) == 1
    assert entries[0]["source"] == "./plugin"
    assert entries[0]["version"] == VERSION
