import importlib
import delinea_api
import json
import pytest

import delinea_mcp.tools as tools


class DummySession:
    def request(self, method, path, **kwargs):
        raise AssertionError("network")


def setup_module(module):
    delinea_api.DelineaSession = DummySession  # type: ignore
    importlib.reload(tools)
    tools.configure({"delinea_base_url": "https://ss.local/SecretServer"})


def test_search_unknown_type(monkeypatch):
    tools.configure({"search_objects": ["secret", "unknown"]})
    monkeypatch.setattr(tools, "search_secrets", lambda q: {"records": []})
    res = tools.search("q")
    assert res == {"results": []}


def test_search_function_error(monkeypatch):
    monkeypatch.setattr(tools, "search_secrets", lambda q: (_ for _ in ()).throw(RuntimeError()))
    res = tools.search("x")
    assert res == {"results": []}


def test_fetch_errors(monkeypatch):
    with pytest.raises(ValueError):
        tools.fetch("bad")

    tools.configure({"fetch_objects": ["secret"]})
    with pytest.raises(ValueError):
        tools.fetch("user/1")

    tools.configure({"fetch_objects": ["secret", "user"]})
    with pytest.raises(ValueError):
        tools.fetch("other/1")

