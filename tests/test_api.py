import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import importlib
from types import SimpleNamespace

import pytest

from delinea_mcp import tools


class DummyResponse:
    def __init__(self, data=None, status_code=200):
        self._data = data or {}
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class DummyRequests:
    def __init__(self, post_resp=None, request_resp=None):
        self.post_resp = post_resp or DummyResponse({"access_token": "tok"})
        self.request_resp = request_resp or DummyResponse({"ok": True})
        self.headers = {}

    def Session(self):
        return self

    def post(self, url, data=None):
        self.post_called = (url, data)
        return self.post_resp

    def request(self, method, url, **kwargs):
        self.request_called = (method, url, kwargs)
        return self.request_resp


class FailFirstRequests(DummyRequests):
    def __init__(self):
        super().__init__()
        self.request_calls = 0
        self.post_count = 0

    def post(self, url, data=None):
        self.post_count += 1
        return super().post(url, data)

    def request(self, method, url, **kwargs):
        self.request_calls += 1
        if self.request_calls == 1:
            return DummyResponse(status_code=401)
        return super().request(method, url, **kwargs)


def test_session_auth_and_request(monkeypatch):
    import delinea_api

    importlib.reload(delinea_api)
    dummy = DummyRequests()
    monkeypatch.setattr(delinea_api, "requests", dummy)
    monkeypatch.setenv("DELINEA_USERNAME", "u")
    monkeypatch.setenv("DELINEA_PASSWORD", "p")
    s = delinea_api.DelineaSession(base_url="http://x")
    assert dummy.post_called == (
        "http://x/oauth2/token",
        {"username": "u", "password": "p", "grant_type": "password"},
    )
    assert s.token == "tok"
    assert dummy.headers["Authorization"] == "Bearer tok"
    resp = s.request("GET", "/foo")
    assert dummy.request_called == (
        "GET",
        "http://x/api/foo",
        {"timeout": 10},
    )
    assert resp.json() == {"ok": True}


def test_request_custom_timeout(monkeypatch):
    import delinea_api

    importlib.reload(delinea_api)
    dummy = DummyRequests()
    monkeypatch.setattr(delinea_api, "requests", dummy)
    monkeypatch.setenv("DELINEA_USERNAME", "u")
    monkeypatch.setenv("DELINEA_PASSWORD", "p")
    s = delinea_api.DelineaSession(base_url="http://x")
    s.request("GET", "/foo", timeout=5)
    assert dummy.request_called[2]["timeout"] == 5


def test_session_missing_credentials(monkeypatch):
    import delinea_api

    importlib.reload(delinea_api)
    dummy = DummyRequests()
    monkeypatch.setattr(delinea_api, "requests", dummy)
    monkeypatch.delenv("DELINEA_USERNAME", raising=False)
    monkeypatch.delenv("DELINEA_PASSWORD", raising=False)
    with pytest.raises(ValueError):
        delinea_api.DelineaSession(base_url="http://x")


def test_session_no_token(monkeypatch):
    import delinea_api

    importlib.reload(delinea_api)
    dummy = DummyRequests(post_resp=DummyResponse({}))
    monkeypatch.setattr(delinea_api, "requests", dummy)
    monkeypatch.setenv("DELINEA_USERNAME", "u")
    monkeypatch.setenv("DELINEA_PASSWORD", "p")
    with pytest.raises(RuntimeError):
        delinea_api.DelineaSession(base_url="http://x")


def test_generate_sql_query(monkeypatch):
    import delinea_api

    importlib.reload(delinea_api)
    captured = {}

    class DummyChat:
        @staticmethod
        def create(model, messages, temperature, max_tokens, n):
            captured["model"] = model
            captured["messages"] = messages
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="SELECT 1"))]
            )

    sys.modules["openai"] = SimpleNamespace(ChatCompletion=DummyChat)
    # Clear the config to ensure we only use environment variables in test
    tools._CFG.clear()
    monkeypatch.setitem(os.environ, "AZURE_OPENAI_ENDPOINT", "e")
    monkeypatch.setitem(os.environ, "AZURE_OPENAI_KEY", "k")
    monkeypatch.setitem(os.environ, "AZURE_OPENAI_DEPLOYMENT", "dep")
    sql = tools.generate_sql_query("desc")
    assert captured["model"] == "dep"  # Uses environment variable, not config
    assert "desc" in captured["messages"][1]["content"]
    assert sql == "SELECT 1"


def test_generate_sql_query_missing_env(monkeypatch):
    import delinea_api

    importlib.reload(delinea_api)
    sys.modules["openai"] = SimpleNamespace()
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT", raising=False)
    result = tools.generate_sql_query("desc")
    assert result.startswith("Error")


def test_server_helpers(monkeypatch):
    import delinea_api

    importlib.reload(delinea_api)
    import server

    monkeypatch.setattr(server.tools, "generate_sql_query", lambda x: "SQL")
    assert server.generate_sql_query("foo") == "SQL"


def test_run_report_delete_failure(monkeypatch):
    import delinea_api

    importlib.reload(delinea_api)
    from delinea_mcp import tools

    calls = []

    def fake_request(method, path, **kwargs):
        calls.append(path)
        if path == "/v1/reports":
            return DummyResponse({"id": 1})
        elif path == "/v1/reports/execute":
            return DummyResponse({"columns": ["c"], "rows": [[1]]})
        else:
            raise RuntimeError("boom")

    monkeypatch.setattr(tools, "delinea", SimpleNamespace(request=fake_request))
    result = tools.run_report("SELECT 1", report_name="t")
    assert result["rows"] == [[1]]
    assert calls[-1] == "/v1/reports/1"


def test_tools_ai_generate_and_run_report(monkeypatch):
    import delinea_api

    importlib.reload(delinea_api)
    from delinea_mcp import tools

    monkeypatch.setattr(tools, "generate_sql_query", lambda d: "SQLX")
    monkeypatch.setattr(
        tools,
        "run_report",
        lambda sql, report_name=None: {"rows": [[2]], "columns": ["c"]},
    )
    result = tools.ai_generate_and_run_report("desc")
    assert result["generated_sql"] == "SQLX"
    assert result["rows"] == [[2]]


def test_request_auto_reauth(monkeypatch):
    import delinea_api

    importlib.reload(delinea_api)

    dummy = FailFirstRequests()
    monkeypatch.setattr(delinea_api, "requests", dummy)
    monkeypatch.setenv("DELINEA_USERNAME", "u")
    monkeypatch.setenv("DELINEA_PASSWORD", "p")

    s = delinea_api.DelineaSession(base_url="http://x")
    resp = s.request("GET", "/foo")
    assert resp.json() == {"ok": True}
    assert dummy.request_calls == 2
    assert dummy.post_count == 2
