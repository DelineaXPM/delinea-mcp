import importlib
import json

import pytest

import delinea_api


# Avoid network calls by patching DelineaSession
class DummySession:
    def request(self, method, path, **kwargs):
        raise AssertionError("network")


import delinea_mcp.tools as tools


def setup_module(module):
    delinea_api.DelineaSession = DummySession  # type: ignore
    importlib.reload(tools)
    tools.configure({"delinea_base_url": "https://ss.local/SecretServer"})


def test_search_default(monkeypatch):
    captured = {}

    def fake_search_secrets(query):
        captured["query"] = query
        return {"records": [{"id": 1, "name": "s"}]}

    monkeypatch.setattr(tools, "search_secrets", fake_search_secrets)
    res = tools.search("foo")
    assert captured["query"] == "foo"
    assert "results" in res
    assert res["results"] == [
        {
            "id": "secret/1",
            "title": "s",
            "text": json.dumps({"id": 1, "name": "s"}, sort_keys=True),
            "url": "https://ss.local/SecretServer/api/v2/secrets/1",
        }
    ]


def test_search_user_not_enabled(monkeypatch):
    called = []

    def fake_search_users(q):
        called.append(q)
        return {}

    monkeypatch.setattr(tools, "search_users", fake_search_users)
    tools.search("u")
    assert not called


def test_search_user_enabled(monkeypatch):
    tools.configure({"search_objects": ["secret", "user"]})

    monkeypatch.setattr(
        tools,
        "search_users",
        lambda q: {"records": [{"id": 2, "username": "bob"}]},
    )
    res = tools.search("bob")
    assert "results" in res
    assert {
        "id": "user/2",
        "title": "bob",
        "text": json.dumps({"id": 2, "username": "bob"}, sort_keys=True),
        "url": "https://ss.local/SecretServer/api/v1/users/2",
    } in res["results"]


def test_fetch_secret(monkeypatch):
    monkeypatch.setattr(
        tools, "get_secret", lambda i, summary=False: {"id": int(i), "name": "s"}
    )
    res = tools.fetch("secret/3")
    assert res == {
        "id": "secret/3",
        "title": "s",
        "text": json.dumps({"id": 3, "name": "s"}, sort_keys=True),
        "url": "https://ss.local/SecretServer/api/v2/secrets/3",
        "metadata": {"id": 3, "name": "s"},
    }


def test_fetch_user_enabled(monkeypatch):
    tools.configure({"fetch_objects": ["secret", "user"]})
    monkeypatch.setattr(
        tools,
        "user_management",
        lambda action, user_id=None, **_: (
            {"id": user_id, "username": "bob"} if action == "get" else None
        ),
    )
    res = tools.fetch("user/4")
    assert res["id"] == "user/4"
    assert res["title"] == "bob"
    assert res["text"] == json.dumps({"id": 4, "username": "bob"}, sort_keys=True)
    assert res["url"] == "https://ss.local/SecretServer/api/v1/users/4"
