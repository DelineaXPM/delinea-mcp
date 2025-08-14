import importlib
import sys
import json
import os
import types



class DummyMCP:
    def __init__(self):
        self.called = None

    def run(self, transport="stdio"):
        self.called = transport

    def tool(self):
        def deco(f):
            return f
        return deco


def test_none_stdio(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"auth_mode": "none", "transport_mode": "stdio"}))
    monkeypatch.chdir(tmp_path)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    monkeypatch.setattr(server, "mcp", DummyMCP())
    server.run_server([])
    assert server.mcp.called == "stdio"


def test_none_sse(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"auth_mode": "none", "transport_mode": "sse"}))
    monkeypatch.chdir(tmp_path)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    monkeypatch.setattr(server, "mcp", DummyMCP())
    called = {}
    def fake_uvicorn_run(app, host="0.0.0.0", port=8000, **kw):
        called.update(kw)
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=fake_uvicorn_run))
    server.run_server([])
    assert called == {}


def test_none_sse_https(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "auth_mode": "none",
        "transport_mode": "sse",
        "ssl_keyfile": "key.pem",
        "ssl_certfile": "cert.pem"
    }))
    monkeypatch.chdir(tmp_path)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    monkeypatch.setattr(server, "mcp", DummyMCP())
    called = {}
    def fake_uvicorn_run(app, host="0.0.0.0", port=8000, **kw):
        called.update(kw)
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=fake_uvicorn_run))
    server.run_server([])
    assert called.get("ssl_keyfile") == "key.pem"
    assert called.get("ssl_certfile") == "cert.pem"


def test_port_and_debug(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "auth_mode": "none",
        "transport_mode": "sse",
        "port": 1234,
        "debug": True
    }))
    monkeypatch.chdir(tmp_path)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    monkeypatch.setattr(server, "mcp", DummyMCP())
    called = {}
    def fake_uvicorn_run(app, host="0.0.0.0", port=8000, **kw):
        called["port"] = port
        called["middleware_count"] = len(app.user_middleware)
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=fake_uvicorn_run))
    server.run_server([])
    assert called["port"] == 1234
    assert called["middleware_count"] == 1


def test_oauth_sse(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "auth_mode": "oauth",
        "transport_mode": "sse",
        "registration_psk": "x"
    }))
    monkeypatch.chdir(tmp_path)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    monkeypatch.setattr(server, "mcp", DummyMCP())
    called = {}
    def fake_uvicorn_run(app, host="0.0.0.0", port=8000, **kw):
        called["run"] = True
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=fake_uvicorn_run))
    import delinea_mcp.auth.routes as routes
    import delinea_mcp.transports.sse as sse
    monkeypatch.setattr(routes, "mount_oauth_routes", lambda app, cfg=None: called.setdefault("oauth", True))
    monkeypatch.setattr(sse, "mount_sse_routes", lambda app, mcp, dep=None: called.setdefault("sse", True))
    server.run_server([])
    assert called["run"] and called["oauth"] and called["sse"]


def test_oauth_sse_https_audience(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "auth_mode": "oauth",
        "transport_mode": "sse",
        "registration_psk": "x",
        "ssl_keyfile": "key.pem",
        "ssl_certfile": "cert.pem",
    }))
    monkeypatch.chdir(tmp_path)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    monkeypatch.setattr(server, "mcp", DummyMCP())
    called = {}
    def fake_uvicorn_run(app, host="0.0.0.0", port=8000, **kw):
        called["run"] = True
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=fake_uvicorn_run))
    import delinea_mcp.auth.routes as routes
    import delinea_mcp.transports.sse as sse
    import delinea_mcp.auth.validators as validators
    monkeypatch.setattr(routes, "mount_oauth_routes", lambda app, cfg=None: called.setdefault("oauth", True))
    def fake_mount(app, mcp, dep=None):
        called["aud"] = dep
    monkeypatch.setattr(sse, "mount_sse_routes", fake_mount)
    def fake_require_scopes(required, audience=None, chatgpt_no_scope_check=False, **kw):
        called["audience"] = audience
        def dep():
            pass
        return dep
    monkeypatch.setattr(validators, "require_scopes", fake_require_scopes)
    server.run_server([])
    assert called["audience"] == "https://0.0.0.0:8000"


def test_oauth_sse_external_hostname(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "auth_mode": "oauth",
                "transport_mode": "sse",
                "registration_psk": "x",
                "external_hostname": "example.com",
            }
        )
    )
    monkeypatch.chdir(tmp_path)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    monkeypatch.setattr(server, "mcp", DummyMCP())
    called = {}

    def fake_uvicorn_run(app, host="0.0.0.0", port=8000, **kw):
        called["run"] = True

    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=fake_uvicorn_run))
    import delinea_mcp.auth.routes as routes
    import delinea_mcp.transports.sse as sse
    import delinea_mcp.auth.validators as validators

    monkeypatch.setattr(routes, "mount_oauth_routes", lambda app, cfg=None: called.setdefault("oauth", True))

    def fake_mount(app, mcp, dep=None):
        called["aud"] = dep

    monkeypatch.setattr(sse, "mount_sse_routes", fake_mount)

    def fake_require_scopes(required, audience=None, chatgpt_no_scope_check=False, **kw):
        called["audience"] = audience

        def dep():
            pass

        return dep

    monkeypatch.setattr(validators, "require_scopes", fake_require_scopes)
    server.run_server([])
    assert called["audience"] == "http://example.com:8000"

