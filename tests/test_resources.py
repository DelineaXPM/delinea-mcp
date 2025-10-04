import importlib
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from delinea_mcp.session import SessionManager


# Patch DelineaSession before importing server to avoid network calls
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


def test_get_secret_detail(monkeypatch):
    def fake_request(self, method, path, **kwargs):
        assert method == "GET"
        assert path == "/v2/secrets/1"
        assert kwargs == {}
        return DummyResponse({"id": 1, "name": "detail"})

    mock_session = type("MockSession", (), {"request": fake_request})()
    monkeypatch.setattr(SessionManager, "_session", mock_session)
    assert server.get_secret(1) == {"id": 1, "name": "detail"}


def test_get_secret_summary(monkeypatch):
    def fake_request(self, method, path, **kwargs):
        assert method == "GET"
        assert path == "/v1/secrets/1/summary"
        return DummyResponse({"id": 1, "name": "summary"})

    mock_session = type("MockSession", (), {"request": fake_request})()
    monkeypatch.setattr(SessionManager, "_session", mock_session)
    assert server.get_secret(1, summary=True) == {"id": 1, "name": "summary"}


def test_get_folder_children(monkeypatch):
    def fake_request(self, method, path, **kwargs):
        assert path == "/v1/folders/5"
        assert kwargs.get("params") == {"getAllChildren": "true"}
        return DummyResponse({"id": 5, "children": []})

    mock_session = type("MockSession", (), {"request": fake_request})()
    monkeypatch.setattr(SessionManager, "_session", mock_session)
    assert server.get_folder(5) == {"id": 5, "children": []}


def test_user_details_and_search(monkeypatch):
    calls = []

    def fake_request(self, method, path, **kwargs):
        calls.append((path, kwargs))
        if path == "/v1/users/2":
            return DummyResponse({"id": 2, "name": "bob"})
        elif path == "/v1/users":
            assert kwargs.get("params") == {"filter.searchText": "bob"}
            return DummyResponse({"records": []})
        else:
            raise AssertionError("unexpected path")

    mock_session = type("MockSession", (), {"request": fake_request})()
    monkeypatch.setattr(SessionManager, "_session", mock_session)
    user = server.user_management("get", user_id=2)
    search = server.search_users("bob")
    assert user == {"id": 2, "name": "bob"}
    assert search == {"records": []}
    assert calls[0][0] == "/v1/users/2"
    assert calls[1][0] == "/v1/users"


def test_secret_search_and_lookup(monkeypatch):
    calls = []

    def fake_request(self, method, path, **kwargs):
        calls.append((path, kwargs))
        if path == "/v2/secrets":
            assert kwargs.get("params") == {"filter.searchText": "foo"}
            return DummyResponse({"records": ["full"]})
        elif path == "/v1/secrets/lookup":
            assert kwargs.get("params") == {"filter.searchText": "foo"}
            return DummyResponse({"records": ["meta"]})
        else:
            raise AssertionError("unexpected path")

    mock_session = type("MockSession", (), {"request": fake_request})()
    monkeypatch.setattr(SessionManager, "_session", mock_session)
    data = server.search_secrets("foo")
    meta = server.search_secrets("foo", lookup=True)
    assert data == {"records": ["full"]}
    assert meta == {"records": ["meta"]}
    assert calls[0][0] == "/v2/secrets"
    assert calls[1][0] == "/v1/secrets/lookup"


def test_folder_search_and_lookup(monkeypatch):
    calls = []

    def fake_request(self, method, path, **kwargs):
        calls.append((path, kwargs))
        if path == "/v1/folders":
            assert kwargs.get("params") == {"filter.searchText": "bar"}
            return DummyResponse({"records": ["folder"]})
        elif path == "/v1/folders/lookup":
            assert kwargs.get("params") == {"filter.searchText": "bar"}
            return DummyResponse({"records": ["lookup"]})
        else:
            raise AssertionError("unexpected path")

    mock_session = type("MockSession", (), {"request": fake_request})()
    monkeypatch.setattr(SessionManager, "_session", mock_session)
    data = server.search_folders("bar")
    meta = server.search_folders("bar", lookup=True)
    assert data == {"records": ["folder"]}
    assert meta == {"records": ["lookup"]}
    assert calls[0][0] == "/v1/folders"
    assert calls[1][0] == "/v1/folders/lookup"
