import importlib
import json
import os
import sys
import types


class DummyMCP:
    def __init__(self):
        self.called = None
        self._lowlevel_server = types.SimpleNamespace(
            run=lambda *a, **k: None,
            create_initialization_options=lambda: None,
        )

    def run(self, transport="stdio"):
        self.called = transport

    def tool(self, **kwargs):
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
    server.run_server(["--config", "config.json"])
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

    monkeypatch.setitem(
        sys.modules, "uvicorn", types.SimpleNamespace(run=fake_uvicorn_run)
    )
    server.run_server(["--config", "config.json"])
    assert called == {}


def test_none_sse_https(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "auth_mode": "none",
                "transport_mode": "sse",
                "ssl_keyfile": "key.pem",
                "ssl_certfile": "cert.pem",
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
        called.update(kw)

    monkeypatch.setitem(
        sys.modules, "uvicorn", types.SimpleNamespace(run=fake_uvicorn_run)
    )
    server.run_server(["--config", "config.json"])
    assert called.get("ssl_keyfile") == "key.pem"
    assert called.get("ssl_certfile") == "cert.pem"


def test_port_and_debug(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {"auth_mode": "none", "transport_mode": "sse", "port": 1234, "debug": True}
        )
    )
    monkeypatch.chdir(tmp_path)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    monkeypatch.setattr(server, "mcp", DummyMCP())
    called = {}

    def fake_uvicorn_run(app, host="0.0.0.0", port=8000, **kw):
        called["port"] = port
        called["middleware_count"] = len(app.user_middleware)
        called["paths"] = {r.path for r in app.router.routes}

    monkeypatch.setitem(
        sys.modules, "uvicorn", types.SimpleNamespace(run=fake_uvicorn_run)
    )
    server.run_server(["--config", "config.json"])
    assert called["port"] == 1234
    assert called["middleware_count"] == 1
    # Both transports live on the same app: legacy SSE + streamable HTTP.
    assert {"/mcp", "/mcp/sse", "/messages/"} <= called["paths"]


def test_oauth_sse(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {"auth_mode": "oauth", "transport_mode": "sse", "registration_psk": "x"}
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

    monkeypatch.setitem(
        sys.modules, "uvicorn", types.SimpleNamespace(run=fake_uvicorn_run)
    )
    import delinea_mcp.auth.routes as routes
    import delinea_mcp.transports.sse as sse

    monkeypatch.setattr(
        routes,
        "mount_oauth_routes",
        lambda app, cfg=None: called.setdefault("oauth", True),
    )
    monkeypatch.setattr(
        sse,
        "mount_sse_routes",
        lambda app, mcp, dep=None, **kw: called.setdefault("sse", True),
    )
    server.run_server(["--config", "config.json"])
    assert called["run"] and called["oauth"] and called["sse"]


def test_oauth_sse_https_audience(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "auth_mode": "oauth",
                "transport_mode": "sse",
                "registration_psk": "x",
                "ssl_keyfile": "key.pem",
                "ssl_certfile": "cert.pem",
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

    monkeypatch.setitem(
        sys.modules, "uvicorn", types.SimpleNamespace(run=fake_uvicorn_run)
    )
    import delinea_mcp.auth.routes as routes
    import delinea_mcp.auth.validators as validators
    import delinea_mcp.transports.sse as sse

    monkeypatch.setattr(
        routes,
        "mount_oauth_routes",
        lambda app, cfg=None: called.setdefault("oauth", True),
    )

    def fake_mount(app, mcp, dep=None, **kw):
        called["aud"] = dep
        called["origin_guard"] = kw.get("origin_guard")

    monkeypatch.setattr(sse, "mount_sse_routes", fake_mount)

    def fake_require_scopes(
        required, audience=None, chatgpt_no_scope_check=False, **kw
    ):
        called["audience"] = audience

        def dep():
            pass

        return dep

    monkeypatch.setattr(validators, "require_scopes", fake_require_scopes)
    server.run_server(["--config", "config.json"])
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

    monkeypatch.setitem(
        sys.modules, "uvicorn", types.SimpleNamespace(run=fake_uvicorn_run)
    )
    import delinea_mcp.auth.routes as routes
    import delinea_mcp.auth.validators as validators
    import delinea_mcp.transports.sse as sse

    monkeypatch.setattr(
        routes,
        "mount_oauth_routes",
        lambda app, cfg=None: called.setdefault("oauth", True),
    )

    def fake_mount(app, mcp, dep=None, **kw):
        called["aud"] = dep
        called["origin_guard"] = kw.get("origin_guard")

    monkeypatch.setattr(sse, "mount_sse_routes", fake_mount)

    def fake_require_scopes(
        required, audience=None, chatgpt_no_scope_check=False, **kw
    ):
        called["audience"] = audience

        def dep():
            pass

        return dep

    monkeypatch.setattr(validators, "require_scopes", fake_require_scopes)
    server.run_server(["--config", "config.json"])
    assert called["audience"] == "http://example.com:8000"
    # The Origin guard is wired into the OAuth app as well as the open one.
    assert callable(called["origin_guard"])


def test_none_sse_mounts_origin_guard(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"auth_mode": "none", "transport_mode": "sse"}))
    monkeypatch.chdir(tmp_path)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    monkeypatch.setattr(server, "mcp", DummyMCP())
    captured = {}

    def fake_uvicorn_run(app, host="0.0.0.0", port=8000, **kw):
        captured["app"] = app

    monkeypatch.setitem(
        sys.modules, "uvicorn", types.SimpleNamespace(run=fake_uvicorn_run)
    )
    server.run_server(["--config", "config.json"])
    from delinea_mcp.transports.origin import OriginNotAllowed

    app = captured["app"]
    assert OriginNotAllowed in app.exception_handlers
    routes = {r.path: r for r in app.router.routes}
    # Every MCP channel carries the Origin guard (spec MUST).
    for path in ("/mcp", "/mcp/sse", "/messages/"):
        assert len(routes[path].dependencies) == 1, path


def test_max_result_bytes_configures_tool_guard(monkeypatch, tmp_path):
    from delinea_mcp import tool_guard

    monkeypatch.setattr(tool_guard, "_max_result_bytes", None)
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {"auth_mode": "none", "transport_mode": "stdio", "max_result_bytes": 4096}
        )
    )
    monkeypatch.chdir(tmp_path)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    monkeypatch.setattr(server, "mcp", DummyMCP())
    server.run_server(["--config", "config.json"])
    assert tool_guard._max_result_bytes == 4096


def _fresh_server(monkeypatch, plugin=None):
    if plugin is None:
        monkeypatch.delenv("DELINEA_MCP_PLUGIN", raising=False)
    else:
        monkeypatch.setenv("DELINEA_MCP_PLUGIN", plugin)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    monkeypatch.setattr(server, "mcp", DummyMCP())
    return server


def _record_init(monkeypatch, server):
    seen = []
    monkeypatch.setattr(server, "_init_from_config", seen.append)
    return seen


def test_plugin_mode_ignores_cwd_and_cached_config(monkeypatch, tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"transport_mode": "sse"}))
    monkeypatch.chdir(tmp_path)
    server = _fresh_server(monkeypatch, plugin="1")
    monkeypatch.setattr(server, "CURRENT_CONFIG", {"transport_mode": "sse"})
    monkeypatch.setitem(
        sys.modules, "uvicorn", types.SimpleNamespace(run=lambda *a, **k: None)
    )
    seen = _record_init(monkeypatch, server)
    server.run_server([])
    assert seen == [{}]
    assert server.mcp.called == "stdio"


def test_plugin_mode_honours_explicit_config(monkeypatch, tmp_path):
    cfg = {"transport_mode": "stdio", "enabled_tools": ["get_secret"]}
    (tmp_path / "explicit.json").write_text(json.dumps(cfg))
    monkeypatch.chdir(tmp_path)
    server = _fresh_server(monkeypatch, plugin="1")
    seen = _record_init(monkeypatch, server)
    server.run_server(["--config", "explicit.json"])
    assert seen == [cfg]


def test_plugin_flag_other_than_1_is_off(monkeypatch, tmp_path):
    cfg = {"transport_mode": "stdio", "enabled_tools": ["get_secret"]}
    (tmp_path / "config.json").write_text(json.dumps(cfg))
    monkeypatch.chdir(tmp_path)
    server = _fresh_server(monkeypatch, plugin="true")
    seen = _record_init(monkeypatch, server)
    server.run_server([])
    assert seen == [cfg]


def test_plugin_mode_skips_import_time_config(monkeypatch):
    from delinea_mcp import config

    calls = []
    real = config.load_config

    def spy(*a, **k):
        calls.append(a)
        return real(*a, **k)

    monkeypatch.setattr(config, "load_config", spy)
    _fresh_server(monkeypatch, plugin="1")
    assert calls == []
    _fresh_server(monkeypatch, plugin="0")
    assert calls == [()]


class _RecordingSession:
    def __init__(self, **kw):
        self.kw = kw


def _init_session(monkeypatch, cfg, env_user="env"):
    server = _fresh_server(monkeypatch)
    for key in ("DELINEA_USERNAME", "DELINEA_PASSWORD", "DELINEA_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    if env_user:
        monkeypatch.setenv("DELINEA_USERNAME", env_user)
    monkeypatch.setenv("DELINEA_PASSWORD", "pw")
    monkeypatch.setenv("DELINEA_BASE_URL", "https://ss.example")
    inited = []
    monkeypatch.setattr(server, "DelineaSession", _RecordingSession)
    monkeypatch.setattr(server.SessionManager, "init", inited.append)
    server._init_from_config(cfg)
    return inited


def test_init_from_env_only(monkeypatch):
    inited = _init_session(monkeypatch, {})
    assert inited[0].kw["username"] == "env"
    assert inited[0].kw["base_url"] == "https://ss.example"


def test_init_config_username_wins_over_env(monkeypatch):
    inited = _init_session(monkeypatch, {"delinea_username": "cfg"})
    assert inited[0].kw["username"] == "cfg"


def test_init_placeholder_or_blank_username_falls_back_to_env(monkeypatch):
    for value in ("<username>", "", "  "):
        inited = _init_session(monkeypatch, {"delinea_username": value})
        assert inited[0].kw["username"] == "env"


def test_init_without_any_username_skips_session(monkeypatch):
    assert _init_session(monkeypatch, {}, env_user=None) == []
