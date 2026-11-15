import importlib
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from delinea_mcp.session import SessionManager


# patch DelineaSession before importing server to avoid network
class DummySession:
    def request(self, method, path, **kwargs):
        raise AssertionError("request not patched")


import delinea_api

delinea_api.DelineaSession = DummySession  # type: ignore

server = importlib.import_module("server")


class DummyResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def test_run_report(monkeypatch):
    calls = []

    def fake_request(self, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/v1/reports":
            assert method == "POST"
            assert kwargs["json"]["reportSql"] == "SELECT 1"
            return DummyResponse({"id": 42})
        elif path == "/v1/reports/execute":
            assert method == "POST"
            assert kwargs["json"] == {"id": 42, "useDefaultParameters": True}
            return DummyResponse({"columns": ["c"], "rows": [[1]]})
        elif path == "/v1/reports/42":
            assert method == "DELETE"
            return DummyResponse(True)
        else:
            raise AssertionError("unexpected path")

    mock_session = type("MockSession", (), {"request": fake_request})()
    monkeypatch.setattr(SessionManager, "_session", mock_session)
    result = server.run_report("SELECT 1", report_name="t")
    assert result == {"columns": ["c"], "rows": [[1]]}
    assert calls[0][1] == "/v1/reports"
    assert calls[1][1] == "/v1/reports/execute"
    assert calls[2][1] == "/v1/reports/42"


def test_ai_generate_and_run_report(monkeypatch):
    def fake_generate(desc):
        assert desc == "foo"
        return "SELECT 2"

    def fake_run(sql, report_name=None):
        assert sql == "SELECT 2"
        return {"columns": ["c"], "rows": [[2]]}

    monkeypatch.setattr(server, "generate_sql_query", fake_generate)
    monkeypatch.setattr(server, "run_report", fake_run)
    result = server.ai_generate_and_run_report("foo")
    assert result["generated_sql"] == "SELECT 2"
    assert result["rows"] == [[2]]


def test_run_report_error(monkeypatch):
    from delinea_mcp import tools

    mock_session = type("MockSession", (), {"request": lambda *a, **k: None})()
    monkeypatch.setattr(SessionManager, "_session", mock_session)

    def fail_create(name, sql):
        raise RuntimeError("boom")

    monkeypatch.setattr(tools, "create_report", fail_create)
    result = tools.run_report("SELECT 1")
    assert result["error"].startswith("Failed to run report")


def test_ai_generate_and_run_report_error(monkeypatch):
    from delinea_mcp import tools

    monkeypatch.setattr(tools, "generate_sql_query", lambda d: "Error: bad")
    result = tools.ai_generate_and_run_report("x")
    assert result == {"error": "Error: bad"}


def test_ai_generate_and_run_report_run_error(monkeypatch):
    from delinea_mcp import tools

    monkeypatch.setattr(tools, "generate_sql_query", lambda d: "SQL")
    monkeypatch.setattr(
        tools, "run_report", lambda sql, report_name=None: {"error": "fail"}
    )
    result = tools.ai_generate_and_run_report("x")
    assert result == {"error": "fail"}


def test_list_example_reports():
    text = server.list_example_reports()
    assert "Retrieve Secrets" in text
    assert "Special Fields" in text


def test_list_example_reports_includes_sql_rules():
    text = server.list_example_reports()
    assert "Report SQL Rules" in text
    assert "temporary tables" in text


def _rejected(message: str) -> Exception:
    """Mimic ``requests.HTTPError``: a bare status in ``str()`` and the
    Secret Server validation message only in ``response.text``."""
    exc = RuntimeError("400 Client Error: Bad Request for url: /api/v1/reports")
    exc.response = SimpleNamespace(text=message)  # type: ignore[attr-defined]
    return exc


def test_run_report_surfaces_rejected_sql_message(monkeypatch):
    from delinea_mcp import tools

    body = '{"message":"Custom report SQL must be a read-only query"}'

    def fake_request(method, path, **kwargs):
        assert path == "/v1/reports"
        raise _rejected(body)

    mock_session = SimpleNamespace(request=fake_request)
    monkeypatch.setattr(SessionManager, "_session", mock_session)
    result = tools.run_report("IF 1 = 1 SELECT 1", report_name="t")
    assert "400 Client Error" in result["error"]
    assert "read-only query" in result["error"]


def test_run_report_surfaces_execute_failure_body(monkeypatch):
    from delinea_mcp import tools

    def fake_request(method, path, **kwargs):
        if path == "/v1/reports":
            return DummyResponse({"id": 7})
        assert path == "/v1/reports/execute"
        raise _rejected("report 7 timed out")

    mock_session = SimpleNamespace(request=fake_request)
    monkeypatch.setattr(SessionManager, "_session", mock_session)
    result = tools.run_report("SELECT 1", report_name="t")
    assert "Failed to execute report 7" in result["error"]
    assert "timed out" in result["error"]


def test_generate_sql_query_prompt_includes_sql_rules(monkeypatch):
    from delinea_mcp import tools

    captured = {}

    class DummyChat:
        @staticmethod
        def create(model, messages, temperature, max_tokens, n):
            captured["messages"] = messages
            message = SimpleNamespace(content="SELECT 1")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    fake_openai = SimpleNamespace(ChatCompletion=DummyChat)
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setattr(tools, "_CFG", {})
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "e")
    monkeypatch.setenv("AZURE_OPENAI_KEY", "k")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "dep")
    assert tools.generate_sql_query("desc") == "SELECT 1"
    assert "Report SQL Rules" in captured["messages"][0]["content"]
