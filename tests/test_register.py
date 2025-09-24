from delinea_mcp import tools


class DummyMCP:
    def __init__(self):
        self.registered = []

    def tool(self):
        def decorator(func):
            self.registered.append(func.__name__)
            return func

        return decorator

    def run(self, transport="stdio"):
        pass


def test_register_skips_ai_when_env_missing(monkeypatch):
    dummy = DummyMCP()
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT", raising=False)
    tools.register(dummy)
    assert "ai_generate_and_run_report" not in dummy.registered


def test_register_respects_enabled_list(monkeypatch):
    dummy = DummyMCP()
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "e")
    monkeypatch.setenv("AZURE_OPENAI_KEY", "k")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "d")
    tools.register(dummy, {"get_secret", "run_report"})
    assert set(dummy.registered) == {"get_secret", "run_report"}
    assert "ai_generate_and_run_report" not in dummy.registered


def test_load_enabled_tools(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"enabled_tools": ["get_user"]}')
    assert tools.load_enabled_tools(cfg) == {"get_user"}


def test_server_reads_config(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"enabled_tools": ["get_user"]}')
    monkeypatch.chdir(tmp_path)

    class DummySession:
        def request(self, *a, **kw):
            raise AssertionError("network call")

    monkeypatch.setattr("delinea_api.DelineaSession", DummySession)
    captured = {}

    def fake_register(mcp, enabled):
        captured["enabled"] = enabled

    monkeypatch.setattr(tools, "register", fake_register)
    import server

    monkeypatch.setattr(server, "mcp", DummyMCP())
    monkeypatch.setattr(server.tools, "register", fake_register)
    server.run_server(["--config", "config.json"])
    assert captured["enabled"] == {"get_user"}
