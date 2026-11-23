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
        (lambda: tools.create_role({"name": "r"}), "POST", "/v1/roles"),
        (lambda: tools.update_role(3, name="r"), "PATCH", "/v1/roles/3"),
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
            lambda: tools.create_folder({"folderName": "f"}),
            "POST",
            "/v1/folders",
        ),
        (
            lambda: tools.update_folder(9, {"folderName": "f"}),
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


def test_update_role_sends_dirty_fields(calls):
    # A plain role object gets HTTP 500 from Secret Server (seen live).
    tools.update_role(3, enabled=False)
    assert first(calls)[2]["json"] == {
        "data": {"enabled": {"dirty": True, "value": False}}
    }
    assert "error" in tools.update_role(3)


@pytest.mark.parametrize(
    "call",
    [
        lambda **kw: tools.get_user_roles(5, **kw),
        lambda **kw: tools.get_user_groups(5, **kw),
        lambda **kw: tools.get_group_roles(4, **kw),
        lambda **kw: tools.get_pending_access_requests(**kw),
        lambda **kw: secretserver_users.search_secretserver_local_users("", **kw),
    ],
)
def test_list_tools_page(calls, call):
    # Without take, Secret Server returns only 10 records.
    call()
    call(take=10_000, skip=20)
    params = [c[2]["params"] for c in calls]
    assert (params[0]["take"], params[0]["skip"]) == (50, 0)
    assert (params[1]["take"], params[1]["skip"]) == (500, 20)


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
            lambda: secretserver_users.create_secretserver_local_user(
                {"userName": "u"}
            ),
            "POST",
            "/v1/users",
        ),
        (
            lambda: secretserver_users.update_secretserver_local_user(
                5, {"userName": "u"}
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
            lambda: secretserver_users.lock_out_secretserver_local_user(5),
            "POST",
            "/v1/users/5/lock-out",
        ),
        (
            lambda: secretserver_users.reset_secretserver_local_user_two_factor(5),
            "POST",
            "/v1/users/5/reset-two-factor",
        ),
        (
            lambda: secretserver_users.reset_secretserver_local_user_password(5, "pw"),
            "POST",
            "/v1/users/5/password-reset",
        ),
    ],
)
def test_local_user_tool_request(calls, call, method, path):
    assert "error" not in call()
    assert first(calls)[:2] == (method, path)


def test_security_actions_build_the_api_body(calls):
    # Secret Server returns HTTP 500 unless the body is wrapped in "data".
    secretserver_users.reset_secretserver_local_user_password(5, "pw")
    secretserver_users.reset_secretserver_local_user_two_factor(5, "Fido")
    secretserver_users.lock_out_secretserver_local_user(5, "phished")
    assert [c[2]["json"] for c in calls] == [
        {"data": {"userId": 5, "password": "pw"}},
        {"data": {"twoFactorType": "Fido"}},
        {"data": {"reasonType": "Other", "description": "phished"}},
    ]
    assert "error" in secretserver_users.reset_secretserver_local_user_password(5, "")
    assert "error" in secretserver_users.lock_out_secretserver_local_user(5, "", "x")
    assert len(calls) == 3


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
            lambda: user_platform_tools.create_platform_user({"Name": "a@t"}),
            "/CDirectoryService/CreateUser",
        ),
        (
            lambda: user_platform_tools.update_platform_user("u-1", {"Mail": "m"}),
            "/CDirectoryService/ChangeUser",
        ),
        (
            lambda: user_platform_tools.delete_platform_user("u-1"),
            "/UserMgmt/RemoveUsers",
        ),
    ],
)
def test_platform_tool_request(posts, call, path):
    call()
    assert posts[0][0] == path


# Platform roles live in the Permission service (/permission/api), not the
# identity API.


@pytest.fixture
def perm(monkeypatch):
    """Record Permission API calls; ``replies`` maps (method, path) to a status."""
    seen, replies = [], {}

    def request(method, url, json=None, params=None, **kwargs):
        path = url.split("/permission/api", 1)[1]
        seen.append((method, path, json, params))
        status = replies.get((method, path), 200)
        body = {} if status < 400 else {"title": "Not Found"}
        return Mock(status_code=status, json=lambda: body, text="")

    monkeypatch.setattr(user_platform_tools, "_headers", {"h": "1"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")
    monkeypatch.setattr(user_platform_tools.requests, "request", request)
    return seen, replies


def test_platform_role_reads(perm):
    seen, _ = perm
    user_platform_tools.get_platform_roles(query="ops")
    user_platform_tools.get_platform_roles("Ops Team")
    user_platform_tools.get_platform_role_members("Ops Team")
    assert seen[0][:2] == ("GET", "/roles")
    assert seen[0][3] == {
        "RecordsPerPage": 100,
        "PageNumber": 1,
        "Name.Contains": "ops",
    }
    assert [c[:2] for c in seen[1:]] == [
        ("GET", "/roles/Ops%20Team"),
        ("GET", "/roles/Ops%20Team/members"),
    ]


def test_create_platform_role(perm):
    seen, _ = perm
    user_platform_tools.create_platform_role("new", "d")
    body = {"roleName": "new", "enabled": True, "description": "d"}
    assert seen == [("POST", "/roles", body, None)]


def test_update_platform_role(perm):
    seen, _ = perm
    user_platform_tools.update_platform_role("Old Role", "d", False)
    body = {"id": "Old Role", "enabled": False, "description": "d"}
    assert seen == [("PUT", "/roles/Old%20Role", body, None)]


def test_update_platform_role_reports_errors(perm):
    _, replies = perm
    replies[("PUT", "/roles/r")] = 403
    result = user_platform_tools.update_platform_role("r", "", True)
    assert "HTTP 403" in result["error"]


def test_platform_roles_page_and_cap(perm):
    seen, _ = perm
    user_platform_tools.get_platform_roles(page=3, page_size=10_000)
    assert seen[0][3] == {"RecordsPerPage": 500, "PageNumber": 3}
    assert "error" in user_platform_tools.get_platform_roles(page="x")
    user_platform_tools.get_platform_role_members("r")
    user_platform_tools.get_platform_role_members("r", page=2, page_size=0)
    assert [c[3] for c in seen[1:]] == [
        {"RecordsPerPage": 100, "PageNumber": 1},
        {"RecordsPerPage": 1, "PageNumber": 2},
    ]
    assert "error" in user_platform_tools.get_platform_role_members("r", page="x")


def test_platform_user_search_pages(monkeypatch):
    sent = []

    def post(url, json=None, **kwargs):
        sent.append(json["Args"])
        return Mock(status_code=200, json=lambda: {"Result": {}}, text="")

    monkeypatch.setattr(user_platform_tools, "_headers", {"h": "1"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")
    monkeypatch.setattr(user_platform_tools.requests, "post", post)
    user_platform_tools.search_users("a", page=2, page_size=10_000)
    assert (sent[0]["PageNumber"], sent[0]["PageSize"]) == (2, 500)
    assert "error" in user_platform_tools.search_users("a", page="x")


def test_delete_platform_role(perm):
    seen, replies = perm
    replies[("DELETE", "/roles/r")] = 204
    assert user_platform_tools.delete_platform_role("r") == {"success": True}
    assert seen == [("DELETE", "/roles/r", None, None)]


def test_add_platform_role_members_creates_membership_when_missing(perm):
    seen, replies = perm
    replies[("PATCH", "/role-memberships/u2/add-role")] = 404
    out = user_platform_tools.add_platform_role_members("r", ["u1", "u2"])
    assert set(out["results"]) == {"u1", "u2"}
    assert [c[:2] for c in seen] == [
        ("PATCH", "/role-memberships/u1/add-role"),
        ("PATCH", "/role-memberships/u2/add-role"),
        ("POST", "/role-memberships"),
    ]
    assert seen[-1][2] == {"subjectId": "u2", "roleName": "r"}


def test_remove_platform_role_members(perm):
    seen, _ = perm
    user_platform_tools.remove_platform_role_members("r", ["u1"])
    body = {"subjectId": "u1", "roleName": "r"}
    assert seen == [("PATCH", "/role-memberships/u1/remove-role", body, None)]


def test_role_member_timeout_keeps_other_results(monkeypatch):
    def request(method, url, **kwargs):
        if "/u2/" in url:
            raise user_platform_tools.requests.Timeout()
        return Mock(status_code=204)

    monkeypatch.setattr(user_platform_tools, "_headers", {"h": "1"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")
    monkeypatch.setattr(user_platform_tools.requests, "request", request)
    out = user_platform_tools.add_platform_role_members("r", ["u1", "u2", "u3"])
    results = out["results"]
    assert results["u1"] == results["u3"] == {"success": True}
    assert "may or may not have been applied" in results["u2"]["error"]


def test_platform_role_tools_report_unconfigured_platform(monkeypatch):
    monkeypatch.setattr(user_platform_tools, "_headers", None)
    monkeypatch.setattr(user_platform_tools, "platform_hostname", None)
    assert "error" in user_platform_tools.get_platform_roles()


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
    # parentFolderId alone also returns grandchildren (seen on a live tenant).
    tools.search_folders("", parent_folder_id=12)
    tools.search_folders("", parent_folder_id=-1)
    child, root = (c[2]["params"] for c in calls)
    assert child["filter.parentFolderId"] == 12
    assert child["filter.limitToDirectDescendents"] == "true"
    assert root["filter.onlyIncludeRootFolders"] == "true"
    assert "filter.parentFolderId" not in root


@pytest.mark.parametrize(
    "call",
    [
        lambda: tools.update_folder(9, {"id": 10, "folderName": "f"}),
        lambda: secretserver_users.update_secretserver_local_user(5, {"Id": 6}),
    ],
)
def test_update_refuses_body_naming_another_object(calls, call):
    # The approval shows the path ID; the body must not retarget the write.
    assert "must name the same object" in call()["error"]
    assert calls == []


def test_update_platform_user_targets_user_id(monkeypatch):
    sent = []

    def post(url, json=None, **kwargs):
        sent.append(json)
        return Mock(status_code=200, json=lambda: {"success": True}, text="")

    monkeypatch.setattr(user_platform_tools, "_headers", {"h": "1"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")
    monkeypatch.setattr(user_platform_tools.requests, "post", post)
    out = user_platform_tools.update_platform_user("u1", {"ID": "u2"})
    assert "must name the same object" in out["error"] and sent == []
    user_platform_tools.update_platform_user("u1", {"DisplayName": "x"})
    assert sent[0]["ID"] == "u1"


def test_role_removal_lockout_is_explained(monkeypatch):
    def refuse(*a, **k):
        return {"error": "DELETE failed: HTTP 500 - ... would lock you out of ..."}

    monkeypatch.setattr(tools, "user_role_management", refuse)
    monkeypatch.setattr(tools, "group_role_management", refuse)
    for result in (tools.remove_user_roles(5, [3]), tools.remove_group_roles(4, [3])):
        assert "Secret Server UI" in result["error"]


def test_paging_clamps_take_and_skip(calls):
    tools.get_user_roles(5, take=10_000, skip=-3)
    tools.get_roles(take=0, skip="x")
    tools.get_groups(query="ops", take=10)
    tools.get_inbox_messages(take=10_000)
    got = [c[2]["params"] for c in calls]
    assert (got[0]["take"], got[0]["skip"]) == (500, 0)
    assert (got[1]["take"], got[1]["skip"]) == (1, 0)
    assert got[2] == {"take": 10, "skip": 0, "filter.searchText": "ops"}
    assert got[3]["take"] == 500


@pytest.mark.parametrize(
    "slug", ["../../2/fields/password", "x/../password", "a?b=c", "", None]
)
def test_field_slug_cannot_change_the_path(slug):
    from delinea_mcp.api import field_path

    with pytest.raises(ValueError):
        field_path(1, slug)


def test_update_secret_fields_refuses_traversal_slug(calls):
    out = tools.update_secret_fields(1, {"x/../password": "v"})
    assert not [c for c in calls if c[0] == "PUT"]
    assert "Invalid field slug" in str(out)


@pytest.mark.parametrize("name", ["..", ".", ""])
def test_platform_names_cannot_change_the_path(perm, name):
    seen, _ = perm
    assert "error" in tools_guarded(user_platform_tools.get_platform_role_members, name)
    assert seen == []


def tools_guarded(func, *args):
    from delinea_mcp.tool_guard import guard_tool

    return guard_tool(func)(*args)


def test_role_member_batch_keeps_going_past_a_bad_id(perm):
    seen, _ = perm
    for func in (
        user_platform_tools.add_platform_role_members,
        user_platform_tools.remove_platform_role_members,
    ):
        out = func("r", ["u1", "..", "u3"])
        assert "error" in out["results"][".."]
        assert (
            "error" not in out["results"]["u1"] and "error" not in out["results"]["u3"]
        )
    assert not any(".." in c[1] for c in seen)


def test_role_search_reads_every_page(monkeypatch):
    pages = [
        {"records": [{"id": i, "name": f"r{i}"} for i in range(500)], "hasNext": True},
        {"records": [{"id": 500, "name": "Ops Admin"}], "hasNext": False},
    ]
    asked = []

    def fake(action, params=None, **kw):
        asked.append(params["skip"])
        return pages[len(asked) - 1]

    monkeypatch.setattr(tools, "role_management", fake)
    assert tools._roles_named("ops") == {"records": [{"id": 500, "name": "Ops Admin"}]}
    assert asked == [0, 500]
