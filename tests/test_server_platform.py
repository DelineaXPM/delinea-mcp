import importlib
import os
import sys

from delinea_mcp import tools


class DummyMCP:
    def __init__(self):
        self.called = False

    def tool(self):
        def deco(f):
            self.called = True
            return f

        return deco

    def run(self, transport="stdio"):
        self.called = True


def test_server_registers_platform_tools(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"platform_hostname": "x"}')
    monkeypatch.chdir(tmp_path)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    called = {}

    def fake_register(mcp):
        called["reg"] = True

    def fake_configure(**kw):
        called["cfg"] = True

    import server

    monkeypatch.setattr(server, "mcp", DummyMCP())
    monkeypatch.setattr(server.user_platform_tools, "register", fake_register)
    monkeypatch.setattr(server.user_platform_tools, "configure", fake_configure)
    server.run_server([])
    assert called["reg"] and called["cfg"]
