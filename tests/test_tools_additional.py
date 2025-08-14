from types import SimpleNamespace
import pytest
from delinea_mcp import tools

class Session:
    def __init__(self):
        self.calls = []
    def request(self, method, path, **kw):
        self.calls.append((method, path, kw))
        return SimpleNamespace(json=lambda: {"ok": True})


def test_get_secret_template_field(monkeypatch):
    s = Session()
    monkeypatch.setattr(tools, "delinea", s)
    out = tools.get_secret_template_field(1)
    assert out == {"ok": True}
    assert s.calls[0][1] == "/v1/secret-templates/fields/1"


def test_user_management_extra(monkeypatch):
    s = Session()
    monkeypatch.setattr(tools, "delinea", s)
    res = tools.user_management("list_sessions", skip=0, take=1, is_exporting=True)
    assert res == {"ok": True}
    assert s.calls[0][2]["params"]["isExporting"]

    res = tools.user_management("unknown")
    assert res["error"] == "Unknown action: unknown"
