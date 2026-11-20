"""The 3.0 read / write / delete tools send the request their name promises."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from delinea_mcp import secretserver_users, strongdm_tools, tools, user_platform_tools
from delinea_mcp.session import SessionManager


@pytest.fixture
def calls(monkeypatch):
    """Record every Secret Server request; each returns ``{"id": 7}``."""
    seen = []

    def request(method, path, **kwargs):
        seen.append((method, path, kwargs))
        return Mock(json=lambda: {"id": 7})

    monkeypatch.setattr(SessionManager, "_session", Mock(request=request))
    return seen


def first(calls):
    method, path, kwargs = calls[0]
    return method, path, kwargs


@pytest.mark.parametrize(
    "call, method, path",
    [
        (lambda: tools.get_roles(), "GET", "/v1/roles"),
        (lambda: tools.get_roles(3), "GET", "/v1/roles/3"),
        (lambda: tools.create_or_update_role({"name": "r"}), "POST", "/v1/roles"),
        (lambda: tools.create_or_update_role({"name": "r"}, 3), "PATCH", "/v1/roles/3"),
        (lambda: tools.get_user_roles(5), "GET", "/v1/users/5/roles"),
        (lambda: tools.add_user_roles(5, [1]), "POST", "/v1/users/5/roles"),
        (lambda: tools.remove_user_roles(5, [1]), "DELETE", "/v1/users/5/roles"),
        (lambda: tools.get_groups(), "GET", "/v1/groups"),
        (lambda: tools.get_groups(4), "GET", "/v1/groups/4"),
        (lambda: tools.create_group({"name": "g"}), "POST", "/v1/groups"),
        (lambda: tools.delete_group(4), "DELETE", "/v1/groups/4"),
        (lambda: tools.get_user_groups(5), "GET", "/v1/users/5/groups"),
        (lambda: tools.add_user_to_groups(5, [4]), "POST", "/v1/users/5/groups"),
        (lambda: tools.remove_user_from_groups(5, [4]), "DELETE", "/v1/users/5/groups"),
        (lambda: tools.get_group_roles(4), "GET", "/v1/groups/4/roles"),
        (lambda: tools.add_group_roles(4, [1]), "POST", "/v1/groups/4/roles"),
        (lambda: tools.remove_group_roles(4, [1]), "DELETE", "/v1/groups/4/roles"),
        (
            lambda: tools.create_or_update_folder({"folderName": "f"}),
            "POST",
            "/v1/folders",
        ),
        (
            lambda: tools.create_or_update_folder({"folderName": "f"}, 9),
            "PUT",
            "/v1/folders/9",
        ),
        (lambda: tools.delete_folder(9), "DELETE", "/v1/folders/9"),
    ],
)
def test_secret_server_tool_request(calls, call, method, path):
    result = call()
    assert "error" not in result
    assert first(calls)[:2] == (method, path)
    # Writes read the object back; reads make exactly one request.
    if method == "GET":
        assert len(calls) == 1


# --------------------------------------------------------------------------- #
# Secret Server local users                                                   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "call, method, path",
    [
        (
            lambda: secretserver_users.get_secretserver_local_user(5),
            "GET",
            "/v1/users/5",
        ),
        (
            lambda: secretserver_users.list_secretserver_user_sessions(),
            "GET",
            "/v1/users/sessions",
        ),
        (
            lambda: secretserver_users.create_or_update_secretserver_local_user(
                {"userName": "u"}
            ),
            "POST",
            "/v1/users",
        ),
        (
            lambda: secretserver_users.create_or_update_secretserver_local_user(
                {"userName": "u"}, 5
            ),
            "PUT",
            "/v1/users/5",
        ),
        (
            lambda: secretserver_users.delete_secretserver_local_user(5),
            "DELETE",
            "/v1/users/5",
        ),
        (
            lambda: secretserver_users.secretserver_local_user_security_action(
                "lock_out", 5
            ),
            "POST",
            "/v1/users/5/lock-out",
        ),
        (
            lambda: secretserver_users.secretserver_local_user_security_action(
                "reset_2fa", 5
            ),
            "POST",
            "/v1/users/5/reset-two-factor",
        ),
    ],
)
def test_local_user_tool_request(calls, call, method, path):
    assert "error" not in call()
    assert first(calls)[:2] == (method, path)


def test_security_action_refuses_reads(calls):
    result = secretserver_users.secretserver_local_user_security_action("get", 5)
    assert "error" in result
    assert calls == []


# --------------------------------------------------------------------------- #
# Delinea Platform                                                            #
# --------------------------------------------------------------------------- #


@pytest.fixture
def posts(monkeypatch):
    """Record every Platform POST URL and body."""
    seen = []

    def post(url, json=None, **kwargs):
        seen.append((url.split("/identity/api", 1)[-1], json))
        return Mock(
            status_code=200, ok=True, json=lambda: {"success": True, "Result": {}}
        )

    monkeypatch.setattr(user_platform_tools, "_headers", {"h": "1"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")
    monkeypatch.setattr(user_platform_tools.requests, "post", post)
    return seen


@pytest.mark.parametrize(
    "call, path",
    [
        (
            lambda: user_platform_tools.get_platform_user("u-1"),
            "/UserMgmt/GetUserAttributes",
        ),
        (
            lambda: user_platform_tools.create_or_update_platform_user({"Name": "a@t"}),
            "/CDirectoryService/CreateUser",
        ),
        (
            lambda: user_platform_tools.create_or_update_platform_user(
                {"Mail": "m"}, "u-1"
            ),
            "/CDirectoryService/ChangeUser",
        ),
        (
            lambda: user_platform_tools.delete_platform_user("u-1"),
            "/UserMgmt/RemoveUsers",
        ),
        (lambda: user_platform_tools.get_platform_roles(), "/Report/RunReport"),
        (
            lambda: user_platform_tools.create_or_update_platform_role({"Name": "r"}),
            "/SaasManage/StoreRole",
        ),
        (
            lambda: user_platform_tools.create_or_update_platform_role(
                {"Description": "d"}, "r"
            ),
            "/Roles/UpdateRole",
        ),
        (
            lambda: user_platform_tools.delete_platform_role("r"),
            "/SaasManage/RemoveRole",
        ),
        (
            lambda: user_platform_tools.get_platform_role_members("r"),
            "/Report/RunReport",
        ),
        (
            lambda: user_platform_tools.add_platform_role_members("r", ["a@t"]),
            "/Roles/UpdateRole",
        ),
        (
            lambda: user_platform_tools.remove_platform_role_members("r", ["a@t"]),
            "/Roles/UpdateRole",
        ),
    ],
)
def test_platform_tool_request(posts, call, path):
    call()
    assert posts[0][0] == path


def test_platform_member_tools_add_and_delete(posts):
    user_platform_tools.add_platform_role_members("r", ["a@t"])
    user_platform_tools.remove_platform_role_members("r", ["a@t"])
    bodies = [body for path, body in posts if path == "/Roles/UpdateRole"]
    assert "Add" in bodies[0]["Users"]
    assert "Delete" in bodies[1]["Users"]


# --------------------------------------------------------------------------- #
# StrongDM: each tool dispatches one fixed action                             #
# --------------------------------------------------------------------------- #


@pytest.fixture
def sdm(monkeypatch):
    seen = []
    for name in ("sdm_user_management", "sdm_role_management"):
        monkeypatch.setattr(
            strongdm_tools, name, lambda action, **kw: seen.append(action) or {}
        )
    return seen


@pytest.mark.parametrize(
    "call, action",
    [
        (lambda: strongdm_tools.sdm_get_users(), "list"),
        (lambda: strongdm_tools.sdm_get_users(email="a@x"), "get"),
        (lambda: strongdm_tools.sdm_create_user("a@x", "A", "B"), "create"),
        (
            lambda: strongdm_tools.sdm_create_user("a@x", "A", "B", roles=["dev"]),
            "onboard",
        ),
        (lambda: strongdm_tools.sdm_set_user_status("offboard", "a@x"), "offboard"),
        (lambda: strongdm_tools.sdm_delete_user("a@x"), "delete"),
        (lambda: strongdm_tools.sdm_get_roles(), "list"),
        (lambda: strongdm_tools.sdm_get_roles("dev"), "get"),
        (lambda: strongdm_tools.sdm_get_roles("dev", members=True), "list_members"),
        (lambda: strongdm_tools.sdm_create_role("dev"), "create"),
        (lambda: strongdm_tools.sdm_delete_role("dev"), "delete"),
        (lambda: strongdm_tools.sdm_add_role_member("dev", "a@x"), "add_user"),
        (lambda: strongdm_tools.sdm_remove_role_member("dev", "a@x"), "remove_user"),
    ],
)
def test_strongdm_tool_action(sdm, call, action):
    call()
    assert sdm == [action]


def test_set_user_status_refuses_reads(sdm):
    assert "error" in strongdm_tools.sdm_set_user_status("list", "a@x")
    assert sdm == []


def test_search_folders_lists_direct_children(calls):
    tools.search_folders("", parent_folder_id=12)
    assert first(calls)[2]["params"]["filter.parentFolderId"] == 12
