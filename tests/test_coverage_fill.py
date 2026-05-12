"""Targeted coverage tests for v1.0.0 error and edge-case paths.

Codecov flagged 24 missing lines on the PR; this file covers them.
Each test is small and deliberately exercises one specific branch.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import requests as _requests  # for raising real exceptions

from delinea_mcp import secretserver_users, tools, user_platform_tools
from delinea_mcp.session import SessionManager


class DummyResponse:
    def __init__(self, data=None, content=b"x", status_code=200, text=""):
        self._data = data if data is not None else {"ok": True}
        self.content = content
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._data


# --------------------------------------------------------------------------- #
# secretserver_users._parse_json_data error path                              #
# --------------------------------------------------------------------------- #


def test_secretserver_users_parse_json_data_invalid():
    """A malformed JSON string raises ValueError (covers lines 29-33)."""
    with pytest.raises(ValueError, match="Invalid JSON data"):
        secretserver_users._parse_json_data("{not valid json")


def test_secretserver_users_parse_json_data_passthrough_dict():
    assert secretserver_users._parse_json_data({"a": 1}) == {"a": 1}


def test_secretserver_users_parse_json_data_none():
    assert secretserver_users._parse_json_data(None) is None


# --------------------------------------------------------------------------- #
# user_platform_tools._parse_json_data error path                             #
# --------------------------------------------------------------------------- #


def test_platform_parse_json_data_invalid():
    """Malformed JSON raises ValueError (covers lines 43-47)."""
    with pytest.raises(ValueError, match="Invalid JSON data"):
        user_platform_tools._parse_json_data("{nope")


# --------------------------------------------------------------------------- #
# user_platform_tools._build_headers network exception path                   #
# --------------------------------------------------------------------------- #


def test_build_headers_network_exception(monkeypatch):
    """When the token endpoint connection fails, RuntimeError surfaces
    (covers lines 144-146)."""
    monkeypatch.setattr(user_platform_tools, "_headers", None)
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")
    monkeypatch.setattr(user_platform_tools, "platform_service_account", "a")
    monkeypatch.setattr(user_platform_tools, "platform_service_password", "p")

    def boom(*a, **kw):
        raise _requests.exceptions.ConnectionError("DNS failure")

    monkeypatch.setattr(user_platform_tools.requests, "post", boom)
    with pytest.raises(RuntimeError, match="Failed to get token"):
        user_platform_tools._build_headers()


# --------------------------------------------------------------------------- #
# user_platform_tools._platform_url branches                                  #
# --------------------------------------------------------------------------- #


def test_platform_url_verbatim_identity_prefix(monkeypatch):
    """Paths beginning ``/identity/...`` are used as-is (covers line 175)."""
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host.example")
    assert (
        user_platform_tools._platform_url("/identity/api/foo")
        == "https://host.example/identity/api/foo"
    )


def test_platform_url_legacy_api_prefix(monkeypatch):
    """Paths beginning ``/api/...`` get ``/identity`` prepended."""
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host.example")
    assert (
        user_platform_tools._platform_url("/api/Report/RunReport")
        == "https://host.example/identity/api/Report/RunReport"
    )


def test_platform_url_bare_endpoint(monkeypatch):
    """Bare endpoint names get the full ``/identity/api`` prefix."""
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host.example")
    assert (
        user_platform_tools._platform_url("/UserMgmt/GetUserAttributes")
        == "https://host.example/identity/api/UserMgmt/GetUserAttributes"
    )


# --------------------------------------------------------------------------- #
# user_platform_tools.search_users error paths                                #
# --------------------------------------------------------------------------- #


def test_search_users_empty_query_returns_error(monkeypatch):
    """An empty query returns the validation error (covers line 210)."""
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": "1"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")
    assert user_platform_tools.search_users("") == {"error": "query required"}


def test_search_users_build_headers_runtime_error(monkeypatch):
    """If _build_headers raises RuntimeError, search_users surfaces it
    (covers lines 213-214)."""
    monkeypatch.setattr(user_platform_tools, "_headers", None)
    monkeypatch.setattr(user_platform_tools, "platform_hostname", None)
    monkeypatch.setattr(user_platform_tools, "platform_service_account", None)
    monkeypatch.setattr(user_platform_tools, "platform_service_password", None)
    res = user_platform_tools.search_users("alice")
    assert "error" in res
    assert "Platform is not configured" in res["error"]


def test_search_users_request_exception(monkeypatch):
    """If the HTTP POST itself raises, the exception is captured
    (covers lines 249-251)."""
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": "1"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")

    def boom(*a, **kw):
        raise _requests.exceptions.ReadTimeout("read timeout")

    monkeypatch.setattr(user_platform_tools.requests, "post", boom)
    res = user_platform_tools.search_users("alice")
    assert "error" in res
    assert "read timeout" in res["error"]


def test_search_platform_user_alias_delegates(monkeypatch):
    """The deprecated search_platform_user alias forwards to search_users
    (covers line 258)."""
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": "1"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")

    captured = []

    def fake_post(url, **kwargs):
        captured.append(kwargs.get("json"))
        return DummyResponse({"success": True, "Result": {"Results": []}})

    monkeypatch.setattr(user_platform_tools.requests, "post", fake_post)
    user_platform_tools.search_platform_user("bob")
    # Verify the query value carried through.
    params = captured[0]["Args"]["Parameters"]
    search_value = next(p["Value"] for p in params if p["Name"] == "searchString")
    assert search_value == "%bob%"


# --------------------------------------------------------------------------- #
# user_platform_tools.user_management validation branches                     #
# --------------------------------------------------------------------------- #


def _stub_post_safety(monkeypatch):
    """For validation-only tests that should never reach the API."""

    def fake_post(*a, **kw):
        raise AssertionError("validation path should reject before HTTP")

    monkeypatch.setattr(user_platform_tools, "_headers", {"h": "1"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")
    monkeypatch.setattr(user_platform_tools.requests, "post", fake_post)


def test_user_management_get_missing_user_id(monkeypatch):
    """``get`` without user_id returns the validation error (covers line 313)."""
    _stub_post_safety(monkeypatch)
    res = user_platform_tools.user_management("get", user_id=None)
    assert res == {"error": "user_id required for get"}


def test_user_management_create_missing_data(monkeypatch):
    """``create`` without data (covers line 328)."""
    _stub_post_safety(monkeypatch)
    res = user_platform_tools.user_management("create", data=None)
    assert res == {"error": "data required for create"}


def test_user_management_delete_missing_user_id(monkeypatch):
    """``delete`` without user_id (covers line 339)."""
    _stub_post_safety(monkeypatch)
    res = user_platform_tools.user_management("delete", user_id=None)
    assert res == {"error": "user_id required for delete"}


def test_user_management_update_missing_pieces(monkeypatch):
    """``update`` without user_id or data (covers line 353)."""
    _stub_post_safety(monkeypatch)
    assert user_platform_tools.user_management(
        "update", user_id=None, data={"a": 1}
    ) == {"error": "user_id and data required for update"}
    assert user_platform_tools.user_management("update", user_id="u", data=None) == {
        "error": "user_id and data required for update"
    }


def test_user_management_search_missing_username(monkeypatch):
    """``search`` without username (covers line 367)."""
    _stub_post_safety(monkeypatch)
    res = user_platform_tools.user_management("search", username=None)
    assert res == {"error": "username required for search"}


def test_user_management_unknown_action(monkeypatch):
    """Unknown action returns a structured error (covers line 370)."""
    _stub_post_safety(monkeypatch)
    res = user_platform_tools.user_management("frobnicate")
    assert res == {"error": "Unknown action: frobnicate"}


# --------------------------------------------------------------------------- #
# user_platform_tools.platform_role_management error / branch paths           #
# --------------------------------------------------------------------------- #


def test_platform_role_management_unconfigured(monkeypatch):
    """When Platform isn't configured the RuntimeError surfaces as error
    (covers lines 506-507)."""
    monkeypatch.setattr(user_platform_tools, "_headers", None)
    monkeypatch.setattr(user_platform_tools, "platform_hostname", None)
    monkeypatch.setattr(user_platform_tools, "platform_service_account", None)
    monkeypatch.setattr(user_platform_tools, "platform_service_password", None)
    res = user_platform_tools.platform_role_management("list")
    assert "error" in res
    assert "Platform is not configured" in res["error"]


def test_platform_role_management_get_missing_role_id(monkeypatch):
    """``get`` without role_id (covers line 517)."""
    _stub_post_safety(monkeypatch)
    res = user_platform_tools.platform_role_management("get", role_id=None)
    assert res == {"error": "role_id required for get"}


def test_platform_role_management_update_missing_pieces(monkeypatch):
    """``update`` without role_id or data (covers line 547)."""
    _stub_post_safety(monkeypatch)
    assert user_platform_tools.platform_role_management(
        "update", role_id=None, data={"x": 1}
    ) == {"error": "role_id and data required for update"}
    assert user_platform_tools.platform_role_management(
        "update", role_id="r", data=None
    ) == {"error": "role_id and data required for update"}


def test_platform_role_management_delete_missing_role_id(monkeypatch):
    """``delete`` without role_id (covers line 561)."""
    _stub_post_safety(monkeypatch)
    res = user_platform_tools.platform_role_management("delete", role_id=None)
    assert res == {"error": "role_id required for delete"}


def test_platform_role_management_unknown_action(monkeypatch):
    """Unknown action (covers line 572)."""
    _stub_post_safety(monkeypatch)
    res = user_platform_tools.platform_role_management("frobnicate")
    assert res == {"error": "Unknown action: frobnicate"}


def test_platform_role_management_create_dict_result_with_rowkey(monkeypatch):
    """The Result-is-dict branch extracts _RowKey (covers lines 538-539)."""
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": "1"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")

    def fake_post(url, **kwargs):
        if "StoreRole" in url:
            return DummyResponse(
                {"success": True, "Result": {"_RowKey": "role-uuid-123"}}
            )
        return DummyResponse({"success": True, "Result": {"Results": []}})

    monkeypatch.setattr(user_platform_tools.requests, "post", fake_post)
    res = user_platform_tools.platform_role_management(
        "create", data={"Name": "Auditors"}
    )
    assert "result" in res
    assert res["result"]["Result"]["_RowKey"] == "role-uuid-123"


# --------------------------------------------------------------------------- #
# user_platform_tools.platform_user_role_management error paths               #
# --------------------------------------------------------------------------- #


def test_platform_user_role_unconfigured(monkeypatch):
    """RuntimeError from _build_headers surfaces (covers lines 631-632)."""
    monkeypatch.setattr(user_platform_tools, "_headers", None)
    monkeypatch.setattr(user_platform_tools, "platform_hostname", None)
    monkeypatch.setattr(user_platform_tools, "platform_service_account", None)
    monkeypatch.setattr(user_platform_tools, "platform_service_password", None)
    res = user_platform_tools.platform_user_role_management("list", role_id="r")
    assert "error" in res
    assert "Platform is not configured" in res["error"]


def test_platform_user_role_unknown_action(monkeypatch):
    """Unknown action raises ValueError caught and returned as error
    (covers line 662)."""
    _stub_post_safety(monkeypatch)
    res = user_platform_tools.platform_user_role_management("frobnicate", role_id="r")
    assert res == {"error": "Unknown action: frobnicate"}


# --------------------------------------------------------------------------- #
# user_platform_tools._endpoint_not_available                                 #
# --------------------------------------------------------------------------- #


def test_endpoint_not_available_detects_404():
    assert user_platform_tools._endpoint_not_available(DummyResponse(status_code=404))


def test_endpoint_not_available_passes_2xx_and_5xx():
    assert not user_platform_tools._endpoint_not_available(
        DummyResponse(status_code=200)
    )
    assert not user_platform_tools._endpoint_not_available(
        DummyResponse(status_code=500)
    )


# --------------------------------------------------------------------------- #
# tools.bulk_user_response invalid JSON string                                #
# --------------------------------------------------------------------------- #


def test_bulk_user_response_invalid_json_user_ids(monkeypatch):
    """A non-JSON string for user_ids is rejected (covers lines 1966-1967)."""
    monkeypatch.setattr(SessionManager, "_session", Mock())
    res = tools.bulk_user_response(
        user_ids="not-a-json-list", scenario="force_logout", comment="why"
    )
    assert "error" in res
    assert "JSON-encoded list" in res["error"]


# --------------------------------------------------------------------------- #
# tools.search drops records with no extractable id                           #
# --------------------------------------------------------------------------- #


def test_tools_search_skips_records_without_id(monkeypatch):
    """A record with no id/userId/folderId/groupId/roleId is skipped
    (covers line 1598)."""
    # Configure search to include the 'secret' kind only.
    tools.configure({"search_objects": ["secret"], "delinea_base_url": "https://x"})

    def fake_search_secrets(query):
        return {
            "records": [
                {"name": "no-id-here"},  # missing all id-shaped keys -> skipped
                {"id": 7, "name": "real"},  # included
            ]
        }

    monkeypatch.setattr(tools, "search_secrets", fake_search_secrets)
    res = tools.search("q")
    assert {r["id"] for r in res["results"]} == {"secret/7"}


# --------------------------------------------------------------------------- #
# tools.fetch unknown kind                                                    #
# --------------------------------------------------------------------------- #


def test_tools_fetch_unknown_kind():
    """fetch() with an unknown object type raises ValueError (covers 1668)."""
    tools.configure({"fetch_objects": ["secret", "spaceship"]})
    with pytest.raises(ValueError, match="unknown fetch type"):
        tools.fetch("spaceship/1")
    # Restore default to avoid bleed-through to other tests.
    tools.configure({"fetch_objects": ["secret"]})
