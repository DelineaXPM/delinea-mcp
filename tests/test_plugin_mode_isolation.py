"""Plugin mode must not read config files from the user's project.

Claude Code starts the plugin's server with the user's project as the working
directory. Without isolation, a ``config.json`` committed to a cloned repo
could set ``delinea_base_url`` and receive the keychain password the plugin
passes in ``DELINEA_PASSWORD``.
"""

import importlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EVIL = {"delinea_base_url": "https://attacker.example", "delinea_username": "x"}


class DummyMCP:
    def __init__(self):
        self.called = None

    def run(self, transport="stdio"):
        self.called = transport

    def tool(self, **kwargs):
        return lambda f: f


@pytest.fixture
def server_mod(monkeypatch):
    def load(plugin: bool):
        if plugin:
            monkeypatch.setenv("DELINEA_MCP_PLUGIN", "1")
        else:
            monkeypatch.delenv("DELINEA_MCP_PLUGIN", raising=False)
        sys.modules.pop("server", None)
        server = importlib.import_module("server")
        monkeypatch.setattr(server, "mcp", DummyMCP())
        seen = []
        monkeypatch.setattr(server, "_init_from_config", lambda cfg: seen.append(cfg))
        return server, seen

    return load


def test_plugin_mode_ignores_project_config_json(monkeypatch, tmp_path, server_mod):
    (tmp_path / "config.json").write_text(json.dumps(EVIL))
    monkeypatch.chdir(tmp_path)
    server, seen = server_mod(plugin=True)
    server.run_server([])
    assert seen == [{}]
    assert server.CURRENT_CONFIG == {}
    assert server.mcp.called == "stdio"


def test_plugin_mode_ignores_inherited_config_env(monkeypatch, tmp_path, server_mod):
    evil = tmp_path / "evil.json"
    evil.write_text(json.dumps(EVIL))
    monkeypatch.setenv("DELINEA_MCP_CONFIG", str(evil))
    monkeypatch.chdir(tmp_path)
    server, seen = server_mod(plugin=True)
    server.run_server([])
    assert seen == [{}]


def test_plugin_mode_rejects_abbreviated_options(monkeypatch, tmp_path, server_mod):
    monkeypatch.chdir(tmp_path)
    server, _ = server_mod(plugin=True)
    with pytest.raises(SystemExit):
        server.run_server(["--conf", "x.json"])


def test_plugin_mode_honours_explicit_config_flag(monkeypatch, tmp_path, server_mod):
    cfg = tmp_path / "chosen.json"
    cfg.write_text(json.dumps({"transport_mode": "stdio", "debug": True}))
    monkeypatch.chdir(tmp_path)
    server, seen = server_mod(plugin=True)
    server.run_server(["--config", str(cfg)])
    assert seen == [{"transport_mode": "stdio", "debug": True}]


def test_standalone_mode_still_reads_project_config(monkeypatch, tmp_path, server_mod):
    (tmp_path / "config.json").write_text(json.dumps({"transport_mode": "stdio"}))
    monkeypatch.chdir(tmp_path)
    server, seen = server_mod(plugin=False)
    server.run_server([])
    assert seen == [{"transport_mode": "stdio"}]


def test_manifest_sets_plugin_mode_and_ignores_uv_project_config():
    path = os.path.join(ROOT, "plugins", "delinea", ".claude-plugin", "plugin.json")
    with open(path) as fh:
        server_cfg = json.load(fh)["mcpServers"]["delinea"]
    assert server_cfg["env"]["DELINEA_MCP_PLUGIN"] == "1"
    assert server_cfg["args"][0] == "--no-config"
    assert server_cfg["args"][-1].startswith("delinea-mcp==")


def test_setup_script_python_probe_ignores_project_modules(tmp_path):
    """`setup-uv.sh check` runs in the user's project before any approval."""
    import shutil
    import subprocess
    from pathlib import Path

    if not shutil.which("bash") or not shutil.which("python3"):
        pytest.skip("bash and python3 required")
    script = Path(__file__).resolve().parents[1] / "plugins/delinea/scripts/setup-uv.sh"
    marker = tmp_path / "shadow-ran"
    shadow = f"open({str(marker)!r}, 'w').write('x')\n"
    for name in ("venv.py", "ensurepip.py"):
        (tmp_path / name).write_text(shadow)
    out = subprocess.run(
        ["bash", str(script), "check"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path)},
    )
    assert out.returncode == 0, out.stderr
    assert "methods=" in out.stdout
    assert not marker.exists()
