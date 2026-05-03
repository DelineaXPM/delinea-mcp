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


def test_secretserver_local_user_management(monkeypatch):
    """The renamed SS-local user_management still exercises /v1/users/*."""
    patch_request(
        monkeypatch,
        [("POST", "/v1/users", {"json": {"n": 1}}), ("GET", "/v1/users/99", {})],
        responses=[{"id": 99}, {"ok": True}],
    )
    assert server.secretserver_local_user_management("create", data={"n": 1}) == {
        "result": {"id": 99},
        "verification": {"ok": True},
    }

    patch_request(monkeypatch, [("GET", "/v1/users/2", {})])
    assert server.secretserver_local_user_management("get", user_id=2) == {"ok": True}

    patch_request(
        monkeypatch,
        [("PUT", "/v1/users/3", {"json": {"a": 1}}), ("GET", "/v1/users/3", {})],
    )
    assert server.secretserver_local_user_management(
        "update", user_id=3, data={"a": 1}
    ) == {
        "result": {"ok": True},
        "verification": {"ok": True},
    }

    patch_request(
        monkeypatch,
        [("DELETE", "/v1/users/4", {}), ("GET", "/v1/users/4", {})],
    )
    assert server.secretserver_local_user_management("delete", user_id=4) == {
        "result": {"ok": True},
        "verification": {"ok": True},
    }

    patch_request(
        monkeypatch, ("GET", "/v1/users/sessions", {"params": {"skip": 0, "take": 20}})
    )
    assert server.secretserver_local_user_management("list_sessions") == {"ok": True}

    patch_request(monkeypatch, ("POST", "/v1/users/5/reset-two-factor", {"json": {}}))
    assert server.secretserver_local_user_management("reset_2fa", user_id=5) == {
        "ok": True
    }

    patch_request(
        monkeypatch, ("POST", "/v1/users/6/password-reset", {"json": {"p": 1}})
    )
    assert server.secretserver_local_user_management(
        "reset_password", user_id=6, data={"p": 1}
    ) == {"ok": True}

    patch_request(monkeypatch, ("POST", "/v1/users/7/lock-out", {"json": {}}))
    assert server.secretserver_local_user_management("lock_out", user_id=7) == {
        "ok": True
    }


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


# -- create_secret_with_generated_password ------------------------------------


def test_create_secret_generated_password_success(monkeypatch):
    patch_request(
        monkeypatch,
        [
            ("POST", "/v1/secret-templates/generate-password/108", {}),
            (
                "POST",
                "/v1/secrets",
                {
                    "json": {
                        "name": "db-prod",
                        "secretTemplateId": 6003,
                        "items": [
                            {"fieldId": 200, "itemValue": "admin"},
                            {"fieldId": 108, "itemValue": "G3n3rated!"},
                        ],
                        "folderId": 5,
                    }
                },
            ),
            ("GET", "/v1/secrets/42/summary", {}),
        ],
        responses=[
            "G3n3rated!",
            {
                "id": 42,
                "name": "db-prod",
                "folderId": 5,
                "secretTemplateId": 6003,
                "items": [
                    {"fieldId": 200, "itemValue": "admin"},
                    {"fieldId": 108, "itemValue": "G3n3rated!"},
                ],
            },
            {"id": 42, "name": "db-prod"},
        ],
    )
    result = server.create_secret_with_generated_password(
        name="db-prod",
        secret_template_id=6003,
        password_field_id=108,
        items=[{"fieldId": 200, "itemValue": "admin"}],
        folder_id=5,
    )
    assert result["result"]["id"] == 42
    assert result["result"]["password_generated"] is True
    assert "items" not in result["result"]
    assert result["verification"]["id"] == 42


def test_create_secret_generated_password_injects_existing_field(monkeypatch):
    """When items already contain the password fieldId, it gets replaced."""
    patch_request(
        monkeypatch,
        [
            ("POST", "/v1/secret-templates/generate-password/108", {}),
            (
                "POST",
                "/v1/secrets",
                {
                    "json": {
                        "name": "test",
                        "secretTemplateId": 6003,
                        "items": [
                            {"fieldId": 108, "itemValue": "NewPwd!"},
                        ],
                    }
                },
            ),
            ("GET", "/v1/secrets/99/summary", {}),
        ],
        responses=[
            "NewPwd!",
            {"id": 99, "name": "test", "secretTemplateId": 6003},
            {"id": 99, "name": "test"},
        ],
    )
    result = server.create_secret_with_generated_password(
        name="test",
        secret_template_id=6003,
        password_field_id=108,
        items=[{"fieldId": 108, "itemValue": ""}],
    )
    assert result["result"]["id"] == 99


def test_create_secret_generated_password_json_string_items(monkeypatch):
    import json

    patch_request(
        monkeypatch,
        [
            ("POST", "/v1/secret-templates/generate-password/108", {}),
            (
                "POST",
                "/v1/secrets",
                {
                    "json": {
                        "name": "json-test",
                        "secretTemplateId": 6003,
                        "items": [
                            {"fieldId": 200, "itemValue": "admin"},
                            {"fieldId": 108, "itemValue": "Gen!"},
                        ],
                    }
                },
            ),
            ("GET", "/v1/secrets/50/summary", {}),
        ],
        responses=[
            "Gen!",
            {"id": 50, "name": "json-test", "secretTemplateId": 6003},
            {"id": 50},
        ],
    )
    result = server.create_secret_with_generated_password(
        name="json-test",
        secret_template_id=6003,
        password_field_id=108,
        items=json.dumps([{"fieldId": 200, "itemValue": "admin"}]),
    )
    assert result["result"]["id"] == 50


def test_create_secret_generated_password_empty_error(monkeypatch):
    patch_request(
        monkeypatch,
        [("POST", "/v1/secret-templates/generate-password/108", {})],
        responses=[""],
    )
    result = server.create_secret_with_generated_password(
        name="fail",
        secret_template_id=6003,
        password_field_id=108,
        items=[],
    )
    assert "error" in result


def test_create_secret_no_items_leak(monkeypatch):
    """Security invariant: the result dict must never contain an 'items' key."""
    patch_request(
        monkeypatch,
        [
            ("POST", "/v1/secret-templates/generate-password/1", {}),
            (
                "POST",
                "/v1/secrets",
                {
                    "json": {
                        "name": "safe",
                        "secretTemplateId": 1,
                        "items": [{"fieldId": 1, "itemValue": "Pwd!"}],
                    }
                },
            ),
            ("GET", "/v1/secrets/10/summary", {}),
        ],
        responses=[
            "Pwd!",
            {
                "id": 10,
                "name": "safe",
                "secretTemplateId": 1,
                "items": [{"itemValue": "Pwd!"}],
            },
            {"id": 10},
        ],
    )
    result = server.create_secret_with_generated_password(
        name="safe", secret_template_id=1, password_field_id=1, items=[]
    )
    assert "items" not in result["result"]
    assert "items" not in result.get("verification", {})


# -- set_secret_field_environment_variable ------------------------------------


def _patch_session_attrs(monkeypatch, token="tok", base_url="https://ss.example.com"):
    """Replace SessionManager session with a stub that has token and base_url."""
    stub = SimpleNamespace(token=token, base_url=base_url)
    monkeypatch.setattr(SessionManager, "_session", stub)


def test_set_secret_field_env_bash_stdin(monkeypatch):
    _patch_session_attrs(
        monkeypatch, token="tok123", base_url="https://ss.example.com/SecretServer"
    )
    script = server.set_secret_field_environment_variable(
        secret_id=42, field_slug="api-key", environment="bash"
    )
    assert "read -rs VALUE" in script
    assert "curl" in script
    assert "PUT" in script
    assert "/v1/secrets/42/fields/api-key" in script
    assert "tok123" in script


def test_set_secret_field_env_bash_env_source(monkeypatch):
    _patch_session_attrs(monkeypatch)
    script = server.set_secret_field_environment_variable(
        secret_id=1, field_slug="password", environment="bash", source="env:MY_VAR"
    )
    assert "${MY_VAR}" in script
    assert "curl" in script


def test_set_secret_field_env_bash_file_source(monkeypatch):
    _patch_session_attrs(monkeypatch)
    script = server.set_secret_field_environment_variable(
        secret_id=1, field_slug="key", environment="bash", source="file:/tmp/key.txt"
    )
    assert "cat /tmp/key.txt" in script
    assert "curl" in script


def test_set_secret_field_env_powershell(monkeypatch):
    _patch_session_attrs(monkeypatch)
    script = server.set_secret_field_environment_variable(
        secret_id=5,
        field_slug="password",
        environment="powershell",
        source="env:AWS_KEY",
    )
    assert "$env:AWS_KEY" in script
    assert "Invoke-RestMethod" in script
    assert "Put" in script


def test_set_secret_field_env_cmd(monkeypatch):
    _patch_session_attrs(monkeypatch)
    script = server.set_secret_field_environment_variable(
        secret_id=5, field_slug="password", environment="cmd", source="env:MY_SECRET"
    )
    assert "%MY_SECRET%" in script
    assert "curl" in script


def test_set_secret_field_env_unsupported(monkeypatch):
    _patch_session_attrs(monkeypatch)
    try:
        server.set_secret_field_environment_variable(
            secret_id=1, field_slug="x", environment="fish"
        )
        raise AssertionError("Expected ValueError")
    except ValueError as exc:
        assert "Unsupported environment" in str(exc)


# -- update_secret_generated_password -----------------------------------------


def test_update_secret_generated_password_success(monkeypatch):
    patch_request(
        monkeypatch,
        [
            # approval pre-check
            ("GET", "/v1/secrets/42/summary", {}),
            ("POST", "/v1/secret-templates/generate-password/108", {}),
            (
                "PUT",
                "/v1/secrets/42/fields/password",
                {"json": {"value": "R0tated!"}},
            ),
            ("GET", "/v1/secrets/42/summary", {}),
        ],
        responses=[
            {"id": 42, "requiresApproval": False, "requiresComment": False},
            "R0tated!",
            "R0tated!",
            {"id": 42, "name": "db-prod"},
        ],
    )
    result = server.update_secret_generated_password(
        secret_id=42, field_slug="password", password_field_id=108
    )
    assert result["result"]["secret_id"] == 42
    assert result["result"]["password_rotated"] is True
    assert result["verification"]["id"] == 42


def test_update_secret_generated_password_empty_error(monkeypatch):
    patch_request(
        monkeypatch,
        [
            ("GET", "/v1/secrets/42/summary", {}),
            ("POST", "/v1/secret-templates/generate-password/108", {}),
        ],
        responses=[
            {"id": 42, "requiresApproval": False},
            "",
        ],
    )
    result = server.update_secret_generated_password(
        secret_id=42, field_slug="password", password_field_id=108
    )
    assert "error" in result


# -- Iris AI approval workflow tests ------------------------------------------


def test_update_secret_approval_required_no_comment(monkeypatch):
    """requiresApproval=True without comment returns guidance error."""
    patch_request(
        monkeypatch,
        [("GET", "/v1/secrets/42/summary", {})],
        responses=[{"id": 42, "requiresApproval": True}],
    )
    result = server.update_secret_generated_password(
        secret_id=42, field_slug="password", password_field_id=108
    )
    assert "error" in result
    assert "requires approval" in result["error"]


def test_update_secret_requires_comment_no_comment(monkeypatch):
    """requiresComment=True without comment returns guidance error."""
    patch_request(
        monkeypatch,
        [("GET", "/v1/secrets/42/summary", {})],
        responses=[{"id": 42, "requiresComment": True}],
    )
    result = server.update_secret_generated_password(
        secret_id=42, field_slug="password", password_field_id=108
    )
    assert "error" in result
    assert "requires a comment" in result["error"]


def test_update_secret_with_comment_passes_params(monkeypatch):
    """When comment is provided, autoCheckout params are passed on the PUT."""
    patch_request(
        monkeypatch,
        [
            ("GET", "/v1/secrets/42/summary", {}),
            ("POST", "/v1/secret-templates/generate-password/108", {}),
            (
                "PUT",
                "/v1/secrets/42/fields/password",
                {
                    "json": {"value": "NewPwd!"},
                    "params": {
                        "autoCheckout": "true",
                        "autoCheckIn": "true",
                        "autoComment": "JIRA-123: rotating DB creds",
                    },
                },
            ),
            ("GET", "/v1/secrets/42/summary", {}),
        ],
        responses=[
            {"id": 42, "requiresComment": True},
            "NewPwd!",
            "NewPwd!",
            {"id": 42, "name": "db-prod"},
        ],
    )
    result = server.update_secret_generated_password(
        secret_id=42,
        field_slug="password",
        password_field_id=108,
        comment="JIRA-123: rotating DB creds",
    )
    assert result["result"]["password_rotated"] is True


def test_set_field_env_approval_check(monkeypatch):
    """set_secret_field_environment_variable returns error when approval needed."""
    _patch_session_attrs(monkeypatch)
    # Override request on the stub to return approval-required summary
    stub = SessionManager._session
    stub.request = lambda method, path, **kw: type(
        "R", (), {"json": lambda self: {"requiresApproval": True}}
    )()
    result = server.set_secret_field_environment_variable(
        secret_id=99, field_slug="api-key", environment="bash"
    )
    assert isinstance(result, dict)
    assert "requires approval" in result["error"]


def test_set_field_env_with_comment_appends_params(monkeypatch):
    """When comment is provided, URL includes checkout query params."""
    _patch_session_attrs(monkeypatch)
    # Stub returns no approval required
    stub = SessionManager._session
    stub.request = lambda method, path, **kw: type(
        "R", (), {"json": lambda self: {"requiresApproval": False}}
    )()
    script = server.set_secret_field_environment_variable(
        secret_id=5,
        field_slug="password",
        environment="bash",
        source="env:MY_VAR",
        comment="INC-456: deploying hotfix",
    )
    assert "autoCheckout=true" in script
    assert "autoCheckIn=true" in script
    assert "INC-456" in script


def test_get_secret_env_approval_check(monkeypatch):
    """get_secret_environment_variable returns error when approval needed."""
    _patch_session_attrs(monkeypatch)
    stub = SessionManager._session
    stub.request = lambda method, path, **kw: type(
        "R", (), {"json": lambda self: {"requiresApproval": True}}
    )()
    result = server.get_secret_environment_variable(secret_id=10, environment="bash")
    assert isinstance(result, dict)
    assert "requires approval" in result["error"]


def test_get_secret_env_with_comment_appends_params(monkeypatch):
    """When comment is provided, URL includes checkout query params."""
    _patch_session_attrs(monkeypatch)
    stub = SessionManager._session
    stub.request = lambda method, path, **kw: type(
        "R", (), {"json": lambda self: {"requiresApproval": False}}
    )()
    script = server.get_secret_environment_variable(
        secret_id=10, environment="bash", comment="CHG-789: reading creds for deploy"
    )
    assert isinstance(script, str)
    assert "autoCheckout=true" in script
    assert "CHG-789" in script
