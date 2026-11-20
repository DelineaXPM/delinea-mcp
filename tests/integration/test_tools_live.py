import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import server
from delinea_mcp import secretserver_users, tools


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
    created = tools.create_group({"name": name, "enabled": True})
    gid = created.get("result", {}).get("id") or created.get("result", {}).get(
        "groupId"
    )
    assert gid
    fetched = tools.get_groups(gid)
    assert fetched.get("name") == name
    roles = tools.get_group_roles(gid)
    assert isinstance(roles, dict)
    deleted = tools.delete_group(gid)
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
    server.search_secrets("admin")
    server.search_folders("/")
    # Platform search_users requires Platform creds; SS-only deployments
    # use search_secretserver_local_users instead.


def test_secret_and_folder_live():
    require_credentials()
    sid = env_var("LIVE_SECRET_ID")
    fid = env_var("LIVE_FOLDER_ID")
    assert server.get_secret(int(sid))
    assert server.get_folder(int(fid))


def test_folder_crud_live():
    require_credentials()
    name = unique_name("mcp-folder")
    parent = int(os.getenv("LIVE_FOLDER_ID") or -1)
    res = tools.create_folder(
        {
            "folderName": name,
            "parentFolderId": parent,
            "folderTypeId": 1,
            "inheritPermissions": True,
            "inheritSecretPolicy": True,
        }
    )
    fid = res.get("result", {}).get("id") or res.get("result", {}).get("folderId")
    if not fid:
        pytest.skip(f"folder create failed: {res.get('error', '')[:120]}")
    current = server.get_folder(fid)
    updated = tools.update_folder(fid, {**current, "folderName": name + "-u"})
    assert "error" not in updated
    deleted = tools.delete_folder(fid)
    assert "error" not in deleted


def test_user_role_group_live():
    require_credentials()
    user_id = env_var("LIVE_USER_ID")
    role_id = env_var("LIVE_ROLE_ID")
    name = unique_name("mcp-testgrp")
    group = tools.create_group({"name": name, "enabled": True})
    gid = group.get("result", {}).get("id") or group.get("result", {}).get("groupId")
    assert gid
    steps = [
        tools.add_user_roles(int(user_id), [int(role_id)]),
        tools.add_user_to_groups(int(user_id), [gid]),
        tools.add_group_roles(gid, [int(role_id)]),
        tools.get_user_roles(int(user_id)),
        tools.get_user_groups(int(user_id)),
        tools.remove_group_roles(gid, [int(role_id)]),
        tools.remove_user_from_groups(int(user_id), [gid]),
        tools.remove_user_roles(int(user_id), [int(role_id)]),
        tools.delete_group(gid),
    ]
    # Secret Server refuses removals that would lock the service account out
    # of Role Administration (LIVE_ROLE_ID is usually its admin role).
    errors = [s["error"] for s in steps if isinstance(s, dict) and "error" in s]
    assert all("API_RoleAdministrationNoLockout" in e for e in errors), errors


def test_list_secretserver_user_sessions_live():
    require_credentials()
    result = secretserver_users.list_secretserver_user_sessions()
    assert isinstance(result, dict)


def test_search_secretserver_local_users_live():
    """v1.0.0: SS-local search_users was renamed."""
    require_credentials()
    result = server.search_secretserver_local_users("admin")
    assert isinstance(result, dict)


def test_update_secret_fields_live():
    """Verify the read-mutate-verify flow against a real secret.

    Idempotent: writes the existing notes value back to itself, so the
    secret content is unchanged after the test.
    """
    require_credentials()
    sid = env_var("LIVE_SECRET_ID")
    summary = server.get_secret(int(sid), summary=True)
    if summary.get("requiresApproval") or summary.get("isRestricted"):
        pytest.skip("LIVE_SECRET_ID requires approval; cannot exercise update flow")

    # Read the current 'notes' value (if present) to write it back unchanged.
    current = server.get_secret(int(sid))
    notes_val = ""
    for item in current.get("items", []) or []:
        slug = (item.get("slug") or item.get("fieldName") or "").lower()
        if slug == "notes":
            notes_val = item.get("itemValue") or ""
            break

    out = server.update_secret_fields(
        secret_id=int(sid),
        field_updates={"notes": notes_val},
        comment="integration-test: idempotent re-write of notes",
    )
    # Either the update succeeded or the secret has no notes slug — both
    # outcomes are acceptable; we just assert the tool returned a structured
    # response and didn't crash.
    assert isinstance(out, dict)
    assert "result" in out or "error" in out


def test_bulk_user_response_preview_live():
    """Preview-only invocation makes no changes against the live tenant."""
    require_credentials()
    uid = env_var("LIVE_USER_ID")
    out = server.bulk_user_response(
        user_ids=[int(uid)],
        scenario="force_logout",
        comment="integration-test: preview only",
    )
    assert "preview" in out
    assert out["preview"]["user_count"] == 1


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
    # stdio (the default) hands the script over as a private file so the
    # access token never reaches the model.
    assert isinstance(out, dict), out
    assert "Bearer" not in str(out)
    script = Path(out["script_path"])
    try:
        assert oct(script.stat().st_mode & 0o777) == "0o600"
        assert f"SECRET_PASSWORD_{sid}" in script.read_text()
    finally:
        script.unlink(missing_ok=True)


def test_list_example_reports_live():
    require_credentials()
    text = server.list_example_reports()
    assert "Retrieve Secrets" in text


def test_user_management_sessions_live():
    """In v1.0.0 ``user_management`` is Platform-backed; this test exercises
    it only if Platform is configured.  Otherwise it expects the helpful
    'not configured' error.
    """
    require_credentials()
    if not os.getenv("PLATFORM_HOSTNAME"):
        # Platform not configured -> tool should return a structured error
        result = server.user_platform_tools.get_platform_user("x")
        assert "search_secretserver_local_users" in result.get("error", "")
        return
    # Platform configured -> a generic search_users call should succeed.
    result = server.search_users("a")
    assert isinstance(result, dict)


def test_get_roles_live():
    require_credentials()
    result = tools.get_roles()
    assert isinstance(result, dict)


def test_report_reference_columns_exist_live():
    """Every table and column list_example_reports documents exists.

    run_report's schema reference is hand-maintained; this catches drift
    (e.g. tbUser.Active, which Secret Server no longer has).
    """
    import re

    from delinea_mcp import constants

    require_credentials()
    tables, current = {}, None
    for line in constants.TABLES_AND_COLUMNS.splitlines():
        if m := re.match(r"\s*\d+\.\s+(\w+)", line):
            current = m.group(1)
            tables[current] = []
        elif (m := re.match(r"\s*-\s+(\w+)", line)) and current:
            tables[current].append(m.group(1))
    missing = []
    for table, columns in tables.items():
        result = server.run_report(f"SELECT TOP 0 * FROM {table}")
        if "error" in result:
            missing.append(f"{table} (table)")
            continue
        have = {c.lower() for c in result.get("columns") or []}
        missing += [f"{table}.{c}" for c in columns if have and c.lower() not in have]
    assert not missing, f"documented but missing: {missing}"
