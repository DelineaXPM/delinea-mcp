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
    assert result == {
        "columns": ["c"],
        "rows": [[1]],
        "total_rows": 1,
        "truncated": False,
    }
    assert calls[0][1] == "/v1/reports"
    assert calls[1][1] == "/v1/reports/execute"
    assert calls[2][1] == "/v1/reports/42"


def test_run_report_error(monkeypatch):
    from delinea_mcp import tools

    mock_session = type("MockSession", (), {"request": lambda *a, **k: None})()
    monkeypatch.setattr(SessionManager, "_session", mock_session)

    def fail_create(name, sql):
        raise RuntimeError("boom")

    monkeypatch.setattr(tools, "create_report", fail_create)
    result = tools.run_report("SELECT 1")
    assert result["error"] == "Report 'MCP Generated Report' failed: boom"


def test_list_example_reports():
    text = server.list_example_reports()
    assert "Retrieve Secrets" in text
    assert "Special Fields" in text


def test_list_example_reports_includes_sql_rules():
    text = server.list_example_reports()
    assert "Report SQL Rules" in text
    assert "temporary tables" in text


def _rejected(message: str, action: str = "POST /v1/reports") -> Exception:
    """Raise the way ``DelineaSession.request`` does on a 400: through
    :func:`delinea_mcp.api.raise_for_status`, with the Secret Server
    validation message only in the response body."""
    from delinea_mcp import api

    def _json():
        raise ValueError("not JSON")

    resp = SimpleNamespace(status_code=400, reason="Bad Request", text=message)
    resp.json = _json
    try:
        api.raise_for_status(resp, action)
    except api.DelineaAPIError as exc:
        return exc
    raise AssertionError("raise_for_status did not raise")


def test_run_report_surfaces_rejected_sql_message(monkeypatch):
    from delinea_mcp import tools

    body = '{"message":"Custom report SQL must be a read-only query"}'

    def fake_request(method, path, **kwargs):
        assert path == "/v1/reports"
        raise _rejected(body)

    mock_session = SimpleNamespace(request=fake_request)
    monkeypatch.setattr(SessionManager, "_session", mock_session)
    result = tools.run_report("IF 1 = 1 SELECT 1", report_name="t")
    assert "HTTP 400" in result["error"]
    assert "read-only query" in result["error"]


def test_run_report_surfaces_execute_failure_body(monkeypatch):
    from delinea_mcp import tools

    def fake_request(method, path, **kwargs):
        if path == "/v1/reports":
            return DummyResponse({"id": 7})
        assert path == "/v1/reports/execute"
        raise _rejected("report 7 timed out", "POST /v1/reports/execute")

    mock_session = SimpleNamespace(request=fake_request)
    monkeypatch.setattr(SessionManager, "_session", mock_session)
    result = tools.run_report("SELECT 1", report_name="t")
    assert "POST /v1/reports/execute failed" in result["error"]
    assert "timed out" in result["error"]


def test_compat_run_report_accepts_every_tool_parameter(monkeypatch):
    """``import server; server.run_report(..., max_rows=...)`` must work."""
    import inspect

    from delinea_mcp import tools

    tool_params = inspect.signature(tools.run_report).parameters
    assert list(inspect.signature(server.run_report).parameters) == list(tool_params)
    seen = {}
    monkeypatch.setattr(
        tools, "run_report", lambda sql, name=None, rows=0: seen.update(rows=rows)
    )
    server.run_report("SELECT 1", max_rows=7)
    assert seen == {"rows": 7}
