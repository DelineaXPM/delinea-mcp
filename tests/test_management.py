from types import SimpleNamespace
from unittest.mock import Mock

import server
from delinea_mcp.session import SessionManager


class DummyResponse:
    def __init__(self, data=None):
        self._data = data or {"ok": True}

    def json(self):
        return self._data


def patch_request(monkeypatch, expected_calls, responses=None):
    if expected_calls and isinstance(expected_calls[0], str):
        expected_calls = [expected_calls]
    calls = list(expected_calls)
    resps = list(responses or [None] * len(calls))

    def fake_request(method, path, **kwargs):
        exp_method, exp_path, exp_kwargs = calls.pop(0)
        assert method == exp_method
        assert path == exp_path
        assert kwargs == exp_kwargs
        data = resps.pop(0)
        return DummyResponse(data)

    # Create a mock session with the fake_request method
    mock_session = Mock()
    mock_session.request = fake_request
    monkeypatch.setattr(SessionManager, "_session", mock_session)


def test_user_management(monkeypatch):
    patch_request(
        monkeypatch,
        [("POST", "/v1/users", {"json": {"n": 1}}), ("GET", "/v1/users/99", {})],
        responses=[{"id": 99}, {"ok": True}],
    )
    assert server.user_management("create", data={"n": 1}) == {
        "result": {"id": 99},
        "verification": {"ok": True},
    }

    patch_request(monkeypatch, [("GET", "/v1/users/2", {})])
    assert server.user_management("get", user_id=2) == {"ok": True}

    patch_request(
        monkeypatch,
        [("PUT", "/v1/users/3", {"json": {"a": 1}}), ("GET", "/v1/users/3", {})],
    )
    assert server.user_management("update", user_id=3, data={"a": 1}) == {
        "result": {"ok": True},
        "verification": {"ok": True},
    }

    patch_request(
        monkeypatch,
        [("DELETE", "/v1/users/4", {}), ("GET", "/v1/users/4", {})],
    )
    assert server.user_management("delete", user_id=4) == {
        "result": {"ok": True},
        "verification": {"ok": True},
    }

    patch_request(
        monkeypatch, ("GET", "/v1/users/sessions", {"params": {"skip": 0, "take": 20}})
    )
    assert server.user_management("list_sessions") == {"ok": True}

    patch_request(monkeypatch, ("POST", "/v1/users/5/reset-two-factor", {"json": {}}))
    assert server.user_management("reset_2fa", user_id=5) == {"ok": True}

    patch_request(
        monkeypatch, ("POST", "/v1/users/6/password-reset", {"json": {"p": 1}})
    )
    assert server.user_management("reset_password", user_id=6, data={"p": 1}) == {
        "ok": True
    }

    patch_request(monkeypatch, ("POST", "/v1/users/7/lock-out", {"json": {}}))
    assert server.user_management("lock_out", user_id=7) == {"ok": True}


def test_role_management(monkeypatch):
    patch_request(monkeypatch, [("GET", "/v1/roles", {"params": {}})])
    assert server.role_management("list") == {"ok": True}

    patch_request(monkeypatch, [("GET", "/v1/roles/1", {})])
    assert server.role_management("get", role_id=1) == {"ok": True}

    patch_request(
        monkeypatch,
        [("POST", "/v1/roles", {"json": {"r": 1}}), ("GET", "/v1/roles/5", {})],
        responses=[{"id": 5}, {"ok": True}],
    )
    assert server.role_management("create", data={"r": 1}) == {
        "result": {"id": 5},
        "verification": {"ok": True},
    }

    patch_request(
        monkeypatch,
        [("PATCH", "/v1/roles/2", {"json": {"x": 1}}), ("GET", "/v1/roles/2", {})],
    )
    assert server.role_management("update", role_id=2, data={"x": 1}) == {
        "result": {"ok": True},
        "verification": {"ok": True},
    }


def test_user_role_management(monkeypatch):
    patch_request(monkeypatch, ("GET", "/v1/users/1/roles", {}))
    assert server.user_role_management("get", 1) == {"ok": True}

    patch_request(
        monkeypatch, ("POST", "/v1/users/1/roles", {"json": {"roleIds": [2]}})
    )
    assert server.user_role_management("add", 1, [2]) == {"ok": True}

    patch_request(
        monkeypatch, ("DELETE", "/v1/users/1/roles", {"json": {"roleIds": [2]}})
    )
    assert server.user_role_management("remove", 1, [2]) == {"ok": True}


def test_group_management(monkeypatch):
    patch_request(monkeypatch, ("GET", "/v1/groups/9", {}))
    assert server.group_management("get", group_id=9) == {"ok": True}

    patch_request(monkeypatch, ("GET", "/v1/groups", {"params": {}}))
    assert server.group_management("list") == {"ok": True}

    patch_request(
        monkeypatch,
        [("POST", "/v1/groups", {"json": {"g": 1}}), ("GET", "/v1/groups/7", {})],
        responses=[{"id": 7}, {"ok": True}],
    )
    assert server.group_management("create", data={"g": 1}) == {
        "result": {"id": 7},
        "verification": {"ok": True},
    }

    patch_request(
        monkeypatch,
        [("DELETE", "/v1/groups/9", {}), ("GET", "/v1/groups/9", {})],
    )
    assert server.group_management("delete", group_id=9) == {
        "result": {"ok": True},
        "verification": {"ok": True},
    }


def test_user_group_management(monkeypatch):
    patch_request(monkeypatch, ("GET", "/v1/users/2/groups", {}))
    assert server.user_group_management("get", 2) == {"ok": True}

    patch_request(
        monkeypatch, ("POST", "/v1/users/2/groups", {"json": {"groupIds": [3]}})
    )
    assert server.user_group_management("add", 2, [3]) == {"ok": True}

    patch_request(
        monkeypatch, ("DELETE", "/v1/users/2/groups", {"params": {"groupIds": [3]}})
    )
    assert server.user_group_management("remove", 2, [3]) == {"ok": True}


def test_group_role_management(monkeypatch):
    patch_request(monkeypatch, ("GET", "/v1/groups/3/roles", {}))
    assert server.group_role_management("list", 3) == {"ok": True}

    patch_request(
        monkeypatch, ("POST", "/v1/groups/3/roles", {"json": {"roleIds": [4]}})
    )
    assert server.group_role_management("add", 3, [4]) == {"ok": True}

    patch_request(
        monkeypatch, ("DELETE", "/v1/groups/3/roles", {"json": {"roleIds": [4]}})
    )
    assert server.group_role_management("remove", 3, [4]) == {"ok": True}


def test_folder_management(monkeypatch):
    patch_request(
        monkeypatch,
        [("POST", "/v1/folders", {"json": {"f": 1}}), ("GET", "/v1/folders/6", {})],
        responses=[{"id": 6}, {"ok": True}],
    )
    assert server.folder_management("create", data={"f": 1}) == {
        "result": {"id": 6},
        "verification": {"ok": True},
    }

    patch_request(
        monkeypatch,
        [("PUT", "/v1/folders/7", {"json": {"x": 2}}), ("GET", "/v1/folders/7", {})],
    )
    assert server.folder_management("update", folder_id=7, data={"x": 2}) == {
        "result": {"ok": True},
        "verification": {"ok": True},
    }

    patch_request(
        monkeypatch, [("DELETE", "/v1/folders/8", {}), ("GET", "/v1/folders/8", {})]
    )
    assert server.folder_management("delete", folder_id=8) == {
        "result": {"ok": True},
        "verification": {"ok": True},
    }

    patch_request(
        monkeypatch, [("GET", "/v1/folders/9", {"params": {"getAllChildren": "true"}})]
    )
    assert server.folder_management("get", folder_id=9) == {"ok": True}

    patch_request(monkeypatch, [("GET", "/v1/folders", {"params": {}})])
    assert server.folder_management("list") == {"ok": True}


def test_health_check(monkeypatch):
    patch_request(monkeypatch, ("GET", "/v1/healthcheck", {"params": {"noBus": True}}))
    assert server.health_check() == {"ok": True}
