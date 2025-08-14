import os
import sys
import time
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import server


def require_credentials():
    if not os.getenv("DELINEA_USERNAME") or not os.getenv("DELINEA_PASSWORD"):
        pytest.skip("DELINEA credentials not set")


def unique_name(prefix: str) -> str:
    return f"{prefix}-{int(time.time())}"


def test_health_check_live():
    require_credentials()
    data = server.health_check()
    assert "status" in data or data.get("error") is None


def test_group_crud_live():
    require_credentials()
    name = unique_name("mcp-group")
    created = server.group_management("create", data={"name": name, "enabled": True})
    gid = created.get("result", {}).get("id") or created.get("result", {}).get("groupId")
    assert gid
    fetched = server.group_management("get", group_id=gid)
    assert fetched.get("name") == name
    roles = server.group_role_management("list", gid)
    assert isinstance(roles, dict)
    deleted = server.group_management("delete", group_id=gid)
    assert "error" not in deleted


def env_var(name: str):
    val = os.getenv(name)
    if not val:
        pytest.skip(f"{name} not set")
    return val


def test_run_report_live():
    require_credentials()
    result = server.run_report("SELECT 1")
    assert "error" not in result


def test_search_live():
    require_credentials()
    server.search_users("admin")
    server.search_secrets("admin")
    server.search_folders("/")


def test_secret_and_folder_live():
    require_credentials()
    sid = env_var("LIVE_SECRET_ID")
    fid = env_var("LIVE_FOLDER_ID")
    assert server.get_secret(int(sid))
    assert server.get_folder(int(fid))


def test_folder_crud_live():
    require_credentials()
    name = unique_name("mcp-folder")
    res = server.folder_management("create", data={"name": name})
    fid = res.get("result", {}).get("id") or res.get("result", {}).get("folderId")
    if not fid:
        pytest.skip("folder create failed")
    updated = server.folder_management("update", folder_id=fid, data={"name": name + "-u"})
    assert "error" not in updated
    deleted = server.folder_management("delete", folder_id=fid)
    assert "error" not in deleted


def test_user_role_group_live():
    require_credentials()
    user_id = env_var("LIVE_USER_ID")
    role_id = env_var("LIVE_ROLE_ID")
    name = unique_name("mcp-testgrp")
    group = server.group_management("create", data={"name": name, "enabled": True})
    gid = group.get("result", {}).get("id") or group.get("result", {}).get("groupId")
    assert gid
    server.user_role_management("add", int(user_id), [int(role_id)])
    server.user_group_management("add", int(user_id), [gid])
    server.group_role_management("add", gid, [int(role_id)])
    server.group_role_management("remove", gid, [int(role_id)])
    server.user_group_management("remove", int(user_id), [gid])
    server.user_role_management("remove", int(user_id), [int(role_id)])
    server.group_management("delete", group_id=gid)


def test_inbox_live():
    require_credentials()
    messages = server.tools.get_inbox_messages()
    ids = [m.get("id") for m in messages.get("data", []) if m.get("id")]
    server.tools.mark_inbox_messages_read(ids, read=True)


def test_pending_access_requests_live():
    require_credentials()
    pending = server.tools.get_pending_access_requests()
    if pending.get("total", 0):
        req = pending.get("items", [])[0]
        rid = req.get("id") or req.get("secretAccessRequestId")
        if rid:
            server.tools.handle_access_request(rid, "Denied", "test")

def test_templates_live():
    require_credentials()
    tid = env_var("LIVE_TEMPLATE_ID")
    server.check_secret_template(int(tid))
    fid = env_var("LIVE_TEMPLATE_FIELD_ID")
    server.check_secret_template_field(int(tid), fid)
    server.get_secret_template_field(int(fid))


def test_get_secret_env_var_live():
    require_credentials()
    sid = env_var("LIVE_SECRET_ID")
    out = server.get_secret_environment_variable(int(sid), "bash")
    assert str(sid) in out


def test_ai_report_live():
    if not os.getenv("AZURE_OPENAI_ENDPOINT"):
        pytest.skip("AI env not set")
    require_credentials()
    result = server.ai_generate_and_run_report("select one user")
    assert "error" not in result


def test_list_example_reports_live():
    require_credentials()
    text = server.list_example_reports()
    assert "Retrieve Secrets" in text


def test_user_management_sessions_live():
    require_credentials()
    result = server.user_management("list_sessions")
    assert isinstance(result, dict)


def test_role_management_live():
    require_credentials()
    result = server.role_management("list")
    assert isinstance(result, dict)
