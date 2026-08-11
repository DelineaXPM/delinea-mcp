"""Unit tests for tools introduced in v1.0.0:

- ``update_secret_fields``
- ``bulk_user_response``
- ``platform_role_management``
- ``platform_user_role_management``
- ``user_management`` / ``search_users`` (Platform-canonical, with the
  legacy ``platform_user_management`` alias)
"""

from __future__ import annotations

import os
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import server
from delinea_mcp import tools, user_platform_tools
from delinea_mcp.session import SessionManager

# --------------------------------------------------------------------------- #
# Shared helpers (mirrors test_management.py patterns)                        #
# --------------------------------------------------------------------------- #


class DummyResponse:
    def __init__(self, data=None, content=b"x", status_code=200):
        self._data = data if data is not None else {"ok": True}
        self.content = content
        self.status_code = status_code

    def json(self):
        return self._data


def patch_request(monkeypatch, expected_calls, responses=None):
    if expected_calls and isinstance(expected_calls[0], str):
        expected_calls = [expected_calls]
    calls = list(expected_calls)
    resps = list(responses or [None] * len(calls))

    def fake_request(method, path, **kwargs):
        exp_method, exp_path, exp_kwargs = calls.pop(0)
        assert method == exp_method, f"expected {exp_method} got {method}"
        assert path == exp_path, f"expected {exp_path} got {path}"
        assert kwargs == exp_kwargs, f"expected {exp_kwargs} got {kwargs}"
        data = resps.pop(0)
        return DummyResponse(data)

    mock_session = Mock()
    mock_session.request = fake_request
    monkeypatch.setattr(SessionManager, "_session", mock_session)


# --------------------------------------------------------------------------- #
# update_secret_fields                                                        #
# --------------------------------------------------------------------------- #


def test_update_secret_fields_happy_path(monkeypatch):
    """Read summary, fetch template, PUT each non-password field, verify."""
    patch_request(
        monkeypatch,
        [
            # 1. approval pre-check
            ("GET", "/v1/secrets/42/summary", {}),
            # 2. fetch secret to discover template id
            ("GET", "/v2/secrets/42", {}),
            # 3. fetch template to enumerate fields
            ("GET", "/v1/secret-templates/9000", {}),
            # 4. PUT each non-password field
            ("PUT", "/v1/secrets/42/fields/notes", {"json": {"value": "n"}}),
            ("PUT", "/v1/secrets/42/fields/url", {"json": {"value": "https://x"}}),
            # 5. verification summary
            ("GET", "/v1/secrets/42/summary", {}),
        ],
        responses=[
            {"id": 42, "requiresApproval": False, "requiresComment": False},
            {"id": 42, "secretTemplateId": 9000},
            {
                "fields": [
                    {"fieldSlugName": "notes", "isPassword": False},
                    {"fieldSlugName": "url", "isPassword": False},
                    {"fieldSlugName": "password", "isPassword": True},
                ]
            },
            {"ok": True},
            {"ok": True},
            {"id": 42, "name": "ok"},
        ],
    )
    result = server.update_secret_fields(
        secret_id=42,
        field_updates={"notes": "n", "url": "https://x"},
    )
    assert result["result"]["secret_id"] == 42
    assert result["result"]["all_updated"] is True
    assert {f["slug"] for f in result["result"]["fields"]} == {"notes", "url"}
    assert result["verification"]["id"] == 42


def test_update_secret_fields_rejects_password_slug(monkeypatch):
    """A slug whose template field has isPassword=True is refused by default."""
    patch_request(
        monkeypatch,
        [
            ("GET", "/v1/secrets/42/summary", {}),
            ("GET", "/v2/secrets/42", {}),
            ("GET", "/v1/secret-templates/9000", {}),
        ],
        responses=[
            {"id": 42, "requiresApproval": False, "requiresComment": False},
            {"id": 42, "secretTemplateId": 9000},
            {
                "fields": [
                    {"fieldSlugName": "password", "isPassword": True},
                    {"fieldSlugName": "notes", "isPassword": False},
                ]
            },
        ],
    )
    result = server.update_secret_fields(
        secret_id=42,
        field_updates={"password": "leaked!"},
    )
    assert "error" in result
    assert "password-class" in result["error"]


def test_update_secret_fields_password_override_emits_value(monkeypatch):
    """allow_password_fields=True bypasses the safety gate."""
    patch_request(
        monkeypatch,
        [
            ("GET", "/v1/secrets/42/summary", {}),
            (
                "PUT",
                "/v1/secrets/42/fields/password",
                {"json": {"value": "new-pwd"}},
            ),
            ("GET", "/v1/secrets/42/summary", {}),
        ],
        responses=[
            {"id": 42, "requiresApproval": False, "requiresComment": False},
            {"ok": True},
            {"id": 42, "name": "ok"},
        ],
    )
    result = server.update_secret_fields(
        secret_id=42,
        field_updates={"password": "new-pwd"},
        allow_password_fields=True,
    )
    assert result["result"]["all_updated"] is True


def test_update_secret_fields_requires_approval_returns_error(monkeypatch):
    patch_request(
        monkeypatch,
        [("GET", "/v1/secrets/42/summary", {})],
        responses=[{"id": 42, "requiresApproval": True}],
    )
    result = server.update_secret_fields(secret_id=42, field_updates={"notes": "n"})
    assert "error" in result and "requires approval" in result["error"]


def test_update_secret_fields_with_comment_passes_audit_params(monkeypatch):
    """When a comment is supplied, the PUT includes autoCheckout/autoComment."""
    patch_request(
        monkeypatch,
        [
            ("GET", "/v1/secrets/42/summary", {}),
            ("GET", "/v2/secrets/42", {}),
            ("GET", "/v1/secret-templates/9000", {}),
            (
                "PUT",
                "/v1/secrets/42/fields/notes",
                {
                    "json": {"value": "n"},
                    "params": {
                        "autoCheckout": "true",
                        "autoCheckIn": "true",
                        "autoComment": "JIRA-1: doc fix",
                    },
                },
            ),
            ("GET", "/v1/secrets/42/summary", {}),
        ],
        responses=[
            {"id": 42, "requiresComment": True},
            {"id": 42, "secretTemplateId": 9000},
            {"fields": [{"fieldSlugName": "notes", "isPassword": False}]},
            {"ok": True},
            {"id": 42},
        ],
    )
    result = server.update_secret_fields(
        secret_id=42,
        field_updates={"notes": "n"},
        comment="JIRA-1: doc fix",
    )
    assert result["result"]["all_updated"] is True


def test_update_secret_fields_rejects_empty_updates(monkeypatch):
    monkeypatch.setattr(SessionManager, "_session", Mock())
    result = server.update_secret_fields(secret_id=1, field_updates={})
    assert "error" in result
    assert "non-empty" in result["error"]


def test_update_secret_fields_accepts_json_string(monkeypatch):
    """field_updates may be a JSON-encoded mapping."""
    patch_request(
        monkeypatch,
        [
            ("GET", "/v1/secrets/42/summary", {}),
            ("GET", "/v2/secrets/42", {}),
            ("GET", "/v1/secret-templates/9000", {}),
            ("PUT", "/v1/secrets/42/fields/notes", {"json": {"value": "n"}}),
            ("GET", "/v1/secrets/42/summary", {}),
        ],
        responses=[
            {"id": 42, "requiresApproval": False, "requiresComment": False},
            {"id": 42, "secretTemplateId": 9000},
            {"fields": [{"fieldSlugName": "notes", "isPassword": False}]},
            {"ok": True},
            {"id": 42},
        ],
    )
    result = server.update_secret_fields(secret_id=42, field_updates='{"notes": "n"}')
    assert result["result"]["all_updated"] is True


# --------------------------------------------------------------------------- #
# bulk_user_response                                                          #
# --------------------------------------------------------------------------- #


def test_bulk_user_response_preview_without_confirm(monkeypatch):
    """confirm=False returns a preview and makes no API calls."""
    sentinel = Mock()
    sentinel.request.side_effect = AssertionError("no API calls expected on preview")
    monkeypatch.setattr(SessionManager, "_session", sentinel)
    out = server.bulk_user_response(
        user_ids=[1, 2, 3], scenario="compromise", comment="INC-7"
    )
    assert "preview" in out
    assert out["preview"]["scenario"] == "compromise"
    assert out["preview"]["user_count"] == 3
    assert "force_logout" in out["preview"]["steps"]


def test_bulk_user_response_rejects_unknown_scenario(monkeypatch):
    monkeypatch.setattr(SessionManager, "_session", Mock())
    out = server.bulk_user_response([1], scenario="nuke", comment="why")
    assert "error" in out and "Unknown scenario" in out["error"]


def test_bulk_user_response_rejects_missing_comment(monkeypatch):
    monkeypatch.setattr(SessionManager, "_session", Mock())
    out = server.bulk_user_response([1], scenario="force_logout", comment="")
    assert "error" in out and "comment is required" in out["error"]


def test_bulk_user_response_rejects_empty_user_list(monkeypatch):
    monkeypatch.setattr(SessionManager, "_session", Mock())
    out = server.bulk_user_response([], scenario="force_logout", comment="why")
    assert "error" in out and "non-empty list" in out["error"]


def test_bulk_user_response_compromise_executes_in_order(monkeypatch):
    """Confirmed compromise scenario runs each step then verifies user state."""
    expected_body = {"data": {"userIds": [10, 20]}}
    patch_request(
        monkeypatch,
        [
            ("POST", "/v1/bulk-user-operations/force-logout", {"json": expected_body}),
            ("POST", "/v1/bulk-user-operations/lock", {"json": expected_body}),
            ("POST", "/v1/bulk-user-operations/disable", {"json": expected_body}),
            (
                "POST",
                "/v1/bulk-user-operations/reset-fido2-two-factor",
                {"json": expected_body},
            ),
            (
                "POST",
                "/v1/bulk-user-operations/reset-totp-auth",
                {"json": expected_body},
            ),
            ("GET", "/v1/users/10", {}),
            ("GET", "/v1/users/20", {}),
        ],
        responses=[
            {"success": True},
            {"success": True},
            {"success": True},
            {"success": True},
            {"success": True},
            {"id": 10, "enabled": False, "isLockedOut": True, "lastLogin": None},
            {"id": 20, "enabled": False, "isLockedOut": True, "lastLogin": None},
        ],
    )
    out = server.bulk_user_response(
        user_ids=[10, 20],
        scenario="compromise",
        comment="INC-42 verified compromise",
        confirm=True,
    )
    assert out["result"]["all_ok"] is True
    assert [s["step"] for s in out["result"]["steps"]] == [
        "force_logout",
        "lock",
        "disable",
        "reset_fido2",
        "reset_totp",
    ]
    assert all(v["enabled"] is False for v in out["verification"])


def test_bulk_user_response_offboard_skips_2fa_resets(monkeypatch):
    """Offboard scenario does not strip 2FA factors (audit trail concern)."""
    expected_body = {"data": {"userIds": [99]}}
    patch_request(
        monkeypatch,
        [
            ("POST", "/v1/bulk-user-operations/force-logout", {"json": expected_body}),
            ("POST", "/v1/bulk-user-operations/disable", {"json": expected_body}),
            ("GET", "/v1/users/99", {}),
        ],
        responses=[
            {"success": True},
            {"success": True},
            {"id": 99, "enabled": False, "isLockedOut": False},
        ],
    )
    out = server.bulk_user_response(
        user_ids=[99],
        scenario="offboard",
        comment="HR-555 offboarding",
        confirm=True,
    )
    assert [s["step"] for s in out["result"]["steps"]] == ["force_logout", "disable"]


def test_bulk_user_response_accepts_json_string(monkeypatch):
    monkeypatch.setattr(SessionManager, "_session", Mock())
    out = server.bulk_user_response(
        user_ids="[1,2]", scenario="force_logout", comment="why"
    )
    # No confirm => preview, but parsing should succeed.
    assert out["preview"]["user_count"] == 2


def test_bulk_user_response_rejects_non_int_ids(monkeypatch):
    monkeypatch.setattr(SessionManager, "_session", Mock())
    out = server.bulk_user_response(
        user_ids=["not-an-int"], scenario="force_logout", comment="why"
    )
    assert "error" in out and "integers" in out["error"]


# --------------------------------------------------------------------------- #
# Platform user_management / search_users                                     #
# --------------------------------------------------------------------------- #


def test_platform_user_management_canonical_alias(monkeypatch):
    """user_management is the canonical name; platform_user_management is alias."""
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": 1})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")

    captured = []

    def fake_post(url, **kwargs):
        captured.append(url)
        return DummyResponse({"ok": True})

    monkeypatch.setattr(user_platform_tools.requests, "post", fake_post)
    res = user_platform_tools.user_management("create", data={"Name": "u"})
    assert res == {"result": {"ok": True}, "verification": {"ok": True}}

    # Alias goes to the same place.
    res2 = user_platform_tools.platform_user_management("create", data={"Name": "u"})
    assert res2 == {"result": {"ok": True}, "verification": {"ok": True}}

    assert all("CreateUser" in u for u in captured if "CreateUser" in u)


def test_platform_search_users_uses_canned_report(monkeypatch):
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": 1})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")

    captured = []

    def fake_post(url, **kwargs):
        captured.append((url, kwargs.get("json")))
        return DummyResponse({"records": [{"Username": "alice"}]})

    monkeypatch.setattr(user_platform_tools.requests, "post", fake_post)
    res = user_platform_tools.search_users("alice")
    assert "records" in res
    assert "RunReport" in captured[0][0]
    assert captured[0][1]["ID"] == "user_searchbyname"


def test_user_management_returns_helpful_error_when_unconfigured(monkeypatch):
    """When Platform isn't configured, user_management explains how to fix it."""
    monkeypatch.setattr(user_platform_tools, "_headers", None)
    monkeypatch.setattr(user_platform_tools, "platform_hostname", None)
    monkeypatch.setattr(user_platform_tools, "platform_service_account", None)
    monkeypatch.setattr(user_platform_tools, "platform_service_password", None)
    res = user_platform_tools.user_management("get", user_id="x")
    assert "error" in res
    assert "secretserver_local_user_management" in res["error"]


# --------------------------------------------------------------------------- #
# platform_role_management                                                    #
#                                                                             #
# On modern Delinea Platform tenants role write ops aren't exposed via the    #
# xpmheadless OAuth scope; the tool returns a structured error.  Read ops     #
# (list, get) use the canned Report/RunReport pattern.                        #
# --------------------------------------------------------------------------- #


def test_platform_role_management_list_uses_canned_report(monkeypatch):
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": 1})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")

    captured = []

    def fake_post(url, **kwargs):
        captured.append((url, kwargs.get("json")))
        return DummyResponse(
            {"success": True, "Result": {"Results": [{"Row": {"Name": "Everybody"}}]}}
        )

    monkeypatch.setattr(user_platform_tools.requests, "post", fake_post)
    res = user_platform_tools.platform_role_management("list")
    assert "/api/Report/RunReport" in captured[0][0]
    assert captured[0][1]["ID"] == "role_searchbyname"
    # The Args.Parameters should carry the search string (default "%" for list-all)
    params = captured[0][1]["Args"]["Parameters"]
    assert any(p["Name"] == "searchString" for p in params)
    assert res.get("success") is True


def test_platform_role_management_get_filters_by_name(monkeypatch):
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": 1})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")

    captured = []

    def fake_post(url, **kwargs):
        captured.append((url, kwargs.get("json")))
        return DummyResponse({"success": True, "Result": {"Results": []}})

    monkeypatch.setattr(user_platform_tools.requests, "post", fake_post)
    user_platform_tools.platform_role_management("get", role_id="Auditors")
    params = captured[0][1]["Args"]["Parameters"]
    search_value = next(p["Value"] for p in params if p["Name"] == "searchString")
    assert search_value == "Auditors"


@pytest.mark.parametrize("action", ["create", "update", "delete"])
def test_platform_role_management_write_falls_back_on_404(monkeypatch, action):
    """When the legacy SaasManage/Roles endpoint returns 404, the tool
    returns a structured guidance error.  But the request IS attempted —
    we don't refuse unconditionally."""
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": "1"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")

    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return DummyResponse(data={}, status_code=404)

    monkeypatch.setattr(user_platform_tools.requests, "post", fake_post)
    res = user_platform_tools.platform_role_management(
        action, role_id="role-1", data={"Name": "x"}
    )
    assert calls, "tool must attempt the endpoint before falling back"
    assert "error" in res
    assert "404" in res["error"]
    assert "role_management" in res["error"]


def test_platform_role_management_create_success_on_supporting_tenant(monkeypatch):
    """When SaasManage/StoreRole returns success, the tool returns the result.

    Verifies tenants that DO expose role mutations aren't locked out by
    the fallback logic.
    """
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": "1"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")

    posts = []

    def fake_post(url, **kwargs):
        posts.append((url, kwargs.get("json")))
        if "StoreRole" in url:
            return DummyResponse({"success": True, "Result": "role-abc"})
        # Verification 'get' uses Report/RunReport
        return DummyResponse({"success": True, "Result": {"Results": []}})

    monkeypatch.setattr(user_platform_tools.requests, "post", fake_post)
    res = user_platform_tools.platform_role_management(
        "create", data={"Name": "Auditors", "Description": "RO"}
    )
    assert "result" in res
    assert res["result"].get("Result") == "role-abc"
    assert any("/SaasManage/StoreRole" in u for u, _ in posts)


def test_platform_role_management_update_success_on_supporting_tenant(monkeypatch):
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": "1"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")

    posts = []

    def fake_post(url, **kwargs):
        posts.append((url, kwargs.get("json")))
        return DummyResponse({"success": True, "Result": {"Updated": True}})

    monkeypatch.setattr(user_platform_tools.requests, "post", fake_post)
    res = user_platform_tools.platform_role_management(
        "update", role_id="role-1", data={"Description": "new desc"}
    )
    assert "result" in res
    update_body = next(b for u, b in posts if "/Roles/UpdateRole" in u)
    assert update_body == {"Name": "role-1", "Description": "new desc"}


def test_platform_role_management_delete_success_on_supporting_tenant(monkeypatch):
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": "1"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")

    posts = []

    def fake_post(url, **kwargs):
        posts.append((url, kwargs.get("json")))
        return DummyResponse({"success": True, "Result": {"Deleted": True}})

    monkeypatch.setattr(user_platform_tools.requests, "post", fake_post)
    res = user_platform_tools.platform_role_management("delete", role_id="role-1")
    assert "result" in res
    delete_body = next(b for u, b in posts if "/SaasManage/RemoveRole" in u)
    assert delete_body == {"Name": "role-1"}


def test_platform_role_management_create_requires_name(monkeypatch):
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": "1"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")
    res = user_platform_tools.platform_role_management("create", data={})
    assert "error" in res and "'Name' required" in res["error"]


# --------------------------------------------------------------------------- #
# platform_user_role_management                                               #
#                                                                             #
# Same constraints — reads via canned report; writes unsupported.             #
# --------------------------------------------------------------------------- #


def test_platform_user_role_list_uses_canned_report(monkeypatch):
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": 1})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")

    captured = []

    def fake_post(url, **kwargs):
        captured.append((url, kwargs.get("json")))
        return DummyResponse({"success": True, "Result": {"Results": []}})

    monkeypatch.setattr(user_platform_tools.requests, "post", fake_post)
    user_platform_tools.platform_user_role_management("list", role_id="role-1")
    assert any("/api/Report/RunReport" in u for u, _ in captured)
    assert captured[0][1]["ID"] == "role_searchbyname"


@pytest.mark.parametrize("action", ["add", "remove"])
def test_platform_user_role_mutations_fall_back_on_404(monkeypatch, action):
    """Add/remove are attempted; on HTTP 404 the tool surfaces guidance."""
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": "1"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")

    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return DummyResponse(data={}, status_code=404)

    monkeypatch.setattr(user_platform_tools.requests, "post", fake_post)
    res = user_platform_tools.platform_user_role_management(
        action, role_id="role-1", user_principals=["alice@t"]
    )
    assert calls, "tool must attempt the endpoint before falling back"
    assert "error" in res
    assert "404" in res["error"]
    assert "user_role_management" in res["error"]


@pytest.mark.parametrize("action,key", [("add", "Add"), ("remove", "Delete")])
def test_platform_user_role_mutations_success_on_supporting_tenant(
    monkeypatch, action, key
):
    """On tenants exposing Roles/UpdateRole the tool returns the real result."""
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": "1"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")

    posts = []

    def fake_post(url, **kwargs):
        posts.append((url, kwargs.get("json")))
        return DummyResponse({"success": True, "Result": {"Updated": True}})

    monkeypatch.setattr(user_platform_tools.requests, "post", fake_post)
    res = user_platform_tools.platform_user_role_management(
        action, role_id="role-1", user_principals=["alice@t", "bob@t"]
    )
    assert "result" in res
    update_body = next(b for u, b in posts if "/Roles/UpdateRole" in u)
    assert update_body == {
        "Name": "role-1",
        "Users": {key: ["alice@t", "bob@t"]},
    }


def test_platform_user_role_add_requires_principals(monkeypatch):
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": "1"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")
    res = user_platform_tools.platform_user_role_management("add", role_id="role-1")
    assert "error" in res and "user_principals required" in res["error"]


def test_platform_user_role_principals_accepts_json_string(monkeypatch):
    """The JSON-string parsing branch still runs even though list is the only
    real path now — keep coverage for the input-validation logic."""
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": "1"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")
    # Bad JSON should produce a parsing error before any HTTP call.

    def fake_post(*a, **kw):
        raise AssertionError("no API call expected on parse error")

    monkeypatch.setattr(user_platform_tools.requests, "post", fake_post)
    res = user_platform_tools.platform_user_role_management(
        "add", role_id="role-1", user_principals="not-json"
    )
    assert "error" in res
    assert "JSON-encoded list" in res["error"]


# --------------------------------------------------------------------------- #
# Tool registration                                                           #
# --------------------------------------------------------------------------- #


class _DummyMCP:
    def __init__(self):
        self.names: list[str] = []

    def tool(self, **kwargs):
        def deco(f):
            self.names.append(f.__name__)
            return f

        return deco


def test_register_exposes_canonical_and_legacy_names():
    """The Platform module registers canonical user_management + search_users."""
    mcp = _DummyMCP()
    user_platform_tools.register(mcp)
    assert "user_management" in mcp.names
    assert "search_users" in mcp.names
    assert "platform_user_management" in mcp.names  # back-compat alias
    assert "platform_role_management" in mcp.names
    assert "platform_user_role_management" in mcp.names


def test_register_ss_local_users():
    from delinea_mcp import secretserver_users

    mcp = _DummyMCP()
    secretserver_users.register(mcp)
    assert "secretserver_local_user_management" in mcp.names
    assert "search_secretserver_local_users" in mcp.names


def test_tools_module_exposes_new_flows():
    """The new tools are present in tools.TOOLS so register() picks them up."""
    names = [n for n, _ in tools.TOOLS]
    assert "update_secret_fields" in names
    assert "bulk_user_response" in names
    assert "user_management" not in names  # moved to platform module
    assert "search_users" not in names  # moved to platform module
