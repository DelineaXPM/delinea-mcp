import importlib
import os
import sys

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
