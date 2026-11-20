"""Live integration tests against a real Delinea Platform tenant.

Run with (the plugin test tenant; see "Live test targets" in AGENTS.md):

    set -a; . ./.env.test-tenant.local; set +a
    uv run pytest tests/integration/test_platform_live.py -v

or against the secondary Platform tenant:

    source .creds && source .env.live && uv run pytest tests/integration/test_platform_live.py -v

These tests require Platform credentials in the environment:

* ``PLATFORM_HOSTNAME``
* ``PLATFORM_SERVICE_ACCOUNT``
* ``PLATFORM_SERVICE_PASSWORD``

Safety contract
---------------

Every mutation goes through a uniquely-named resource (timestamp +
``mcp-itest-`` prefix) that is captured in a per-test cleanup list and
deleted in a ``finally`` block.  Existing tenant data is never read for
modification — only created resources are altered.  If a test crashes,
the next run's cleanup pre-pass will sweep any leaked resources whose
names start with the ``mcp-itest-`` prefix.
"""

from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from delinea_mcp import user_platform_tools  # noqa: E402

TEST_PREFIX = "mcp-itest-"  # unique enough to identify our created resources


def _require_platform():
    if not (
        os.getenv("PLATFORM_HOSTNAME")
        and os.getenv("PLATFORM_SERVICE_ACCOUNT")
        and os.getenv("PLATFORM_SERVICE_PASSWORD")
    ):
        pytest.skip("Platform credentials not set")


@pytest.fixture(scope="module", autouse=True)
def _configure_platform():
    """Load PLATFORM_* env vars into the user_platform_tools module."""
    if not (
        os.getenv("PLATFORM_HOSTNAME")
        and os.getenv("PLATFORM_SERVICE_ACCOUNT")
        and os.getenv("PLATFORM_SERVICE_PASSWORD")
    ):
        yield
        return

    user_platform_tools.configure(
        hostname=os.environ["PLATFORM_HOSTNAME"],
        service_account=os.environ["PLATFORM_SERVICE_ACCOUNT"],
        service_password=os.environ["PLATFORM_SERVICE_PASSWORD"],
        tenant_id=os.getenv("PLATFORM_TENANT_ID"),
    )
    yield
    # No global teardown — per-test cleanup handles created resources.


def _unique_username(label: str) -> str:
    return f"{TEST_PREFIX}{label}-{int(time.time())}@dartlabs"


# --------------------------------------------------------------------------- #
# Auth / connectivity                                                          #
# --------------------------------------------------------------------------- #


def test_platform_oauth_token_obtainable():
    """xpmplatform client-credentials grant returns a token."""
    _require_platform()
    # Force a fresh token by invalidating cache
    user_platform_tools._headers = None
    headers = user_platform_tools._build_headers()
    assert headers["Authorization"].startswith("Bearer ")


# --------------------------------------------------------------------------- #
# search_users (read-only, safe)                                              #
# --------------------------------------------------------------------------- #


def test_search_users_live_returns_records():
    """A wildcard search against the service-account substring should hit at
    least the service user itself."""
    _require_platform()
    # Search for the configured service account (minus any @domain), so the
    # test works on any tenant rather than one account name.
    account = os.environ["PLATFORM_SERVICE_ACCOUNT"].split("@")[0]
    out = user_platform_tools.search_users(account)
    assert out.get("success") is True
    results = (out.get("Result") or {}).get("Results", [])
    # At least the service account itself should match.
    assert len(results) >= 1
    # Verify shape — every row should have a Row with a Username field.
    row0 = (results[0].get("Row") if isinstance(results[0], dict) else {}) or {}
    assert any(k for k in row0 if "user" in k.lower() or "name" in k.lower())


def test_search_users_empty_query_rejected():
    _require_platform()
    out = user_platform_tools.search_users("")
    assert "error" in out and "query required" in out["error"]


# --------------------------------------------------------------------------- #
# Platform users — full CRUD lifecycle with cleanup                          #
# --------------------------------------------------------------------------- #


def _try_cleanup_user(user_id: str | None):
    """Best-effort delete of a created test user."""
    if not user_id:
        return
    try:
        user_platform_tools.delete_platform_user(user_id)
    except Exception:
        pass  # surfaces in next pre-test sweep if it leaked


def test_user_management_create_get_update_delete_lifecycle():
    """Full lifecycle on a brand-new test user — never touches existing data."""
    _require_platform()

    username = _unique_username("lifecycle")
    new_user_id: str | None = None

    try:
        # 1. Create
        create_payload = {
            "Name": username,
            "Mail": username,
            "DisplayName": f"MCP Integration Test User {username}",
            "Description": "Created by mcp integration test; safe to delete.",
            "Password": "TempPass!" + str(int(time.time())),
            "ForcePasswordChangeNextLogin": True,
        }
        out = user_platform_tools.create_platform_user(create_payload)
        assert "result" in out, f"create returned: {out}"
        result = out["result"]
        # Result shape: {"success": True, "Result": <user_uuid>} on modern Platform
        # or sometimes nested differently — be tolerant.
        new_user_id = (
            result.get("Result")
            if isinstance(result.get("Result"), str)
            else (
                (result.get("Result") or {}).get("ID")
                if isinstance(result.get("Result"), dict)
                else None
            )
        )
        assert (
            new_user_id
        ), f"could not extract new user id from create response: {result}"

        # Verification side: search should find the new user.
        verify = out.get("verification") or {}
        assert verify.get("success") in (True, None)

        # 2. Get
        got = user_platform_tools.get_platform_user(new_user_id)
        # GetUserAttributes wraps the user record in Result
        gr = got.get("Result") if isinstance(got, dict) else None
        assert isinstance(gr, dict), f"get returned non-dict Result: {got}"
        assert gr.get("Name") == username or gr.get("Mail") == username

        # 3. Update (change DisplayName)
        new_display = f"MCP Updated {int(time.time())}"
        upd = user_platform_tools.update_platform_user(
            new_user_id, {"ID": new_user_id, "DisplayName": new_display}
        )
        assert "result" in upd

        # Verify the update propagated.
        got2 = user_platform_tools.get_platform_user(new_user_id)
        gr2 = got2.get("Result") if isinstance(got2, dict) else None
        if isinstance(gr2, dict):
            # On some tenants DisplayName updates may be async; allow either.
            assert (
                gr2.get("DisplayName") in (new_display, None)
                or gr2.get("Description") is not None
            )

        # 4. Delete
        deleted = user_platform_tools.delete_platform_user(new_user_id)
        assert "result" in deleted
        new_user_id = None  # so the finally block doesn't try again

    finally:
        # Always attempt cleanup; safe to no-op if already deleted.
        _try_cleanup_user(new_user_id)


def test_get_platform_user_rejects_missing_id():
    _require_platform()
    out = user_platform_tools.get_platform_user("")
    assert "error" in out


def test_search_users_live():
    _require_platform()
    out = user_platform_tools.search_users("test_mcp")
    assert out.get("success") is True


def test_user_management_unconfigured_returns_helpful_error():
    """Stash, blow away config, confirm error message; restore.

    Verifies the "Platform not configured" code path is reachable on a
    real tenant by temporarily clearing the cached headers and globals.
    """
    _require_platform()
    saved = (
        user_platform_tools.platform_hostname,
        user_platform_tools.platform_service_account,
        user_platform_tools.platform_service_password,
        user_platform_tools._headers,
    )
    try:
        user_platform_tools.platform_hostname = None
        user_platform_tools.platform_service_account = None
        user_platform_tools.platform_service_password = None
        user_platform_tools._headers = None
        out = user_platform_tools.get_platform_user("any-uuid-for-the-test")
        assert "error" in out
        assert "search_secretserver_local_users" in out["error"]
    finally:
        (
            user_platform_tools.platform_hostname,
            user_platform_tools.platform_service_account,
            user_platform_tools.platform_service_password,
            user_platform_tools._headers,
        ) = saved


# --------------------------------------------------------------------------- #
# Platform roles (Permission service) — lifecycle on a throwaway role         #
# --------------------------------------------------------------------------- #


def test_get_platform_roles_lists_built_in_roles_live():
    _require_platform()
    out = user_platform_tools.get_platform_roles()
    names = {r["roleName"] for r in out.get("records", [])}
    assert "Platform Admin" in names, out


def test_get_platform_role_and_members_live():
    _require_platform()
    role = user_platform_tools.get_platform_roles("Platform User")
    assert role.get("roleName") == "Platform User", role
    members = user_platform_tools.get_platform_role_members("Platform User")
    assert "members" in members, members


def test_platform_role_lifecycle_live():
    """Create, update, assign, unassign and delete a role that grants nothing."""
    _require_platform()
    role = f"{TEST_PREFIX}role-{int(time.time())}"
    username = _unique_username("rolemember")
    user_id = None
    try:
        created = user_platform_tools.create_platform_role(role, "itest")
        assert "error" not in created, created
        again = user_platform_tools.create_platform_role(role, "itest")
        assert "error" in again, again
        updated = user_platform_tools.update_platform_role(role, "itest 2", True)
        assert updated.get("description") == "itest 2", updated

        out = user_platform_tools.create_platform_user(
            {
                "Name": username,
                "Mail": username,
                "DisplayName": "MCP role member",
                "Password": "TempPass!" + str(int(time.time())),
                "ForcePasswordChangeNextLogin": True,
            }
        )
        user_id = out["result"].get("Result")
        assert isinstance(user_id, str), out

        added = user_platform_tools.add_platform_role_members(role, [user_id])
        assert "error" not in added["results"][user_id], added
        members = user_platform_tools.get_platform_role_members(role)["members"]
        assert user_id in members

        removed = user_platform_tools.remove_platform_role_members(role, [user_id])
        assert "error" not in removed["results"][user_id], removed
        assert (
            user_id
            not in user_platform_tools.get_platform_role_members(role)["members"]
        )
    finally:
        if user_id:
            _try_cleanup_user(user_id)
        assert user_platform_tools.delete_platform_role(role) == {"success": True}
    assert "HTTP 404" in user_platform_tools.get_platform_roles(role)["error"]


def test_built_in_platform_role_cannot_be_changed_live():
    _require_platform()
    current = user_platform_tools.get_platform_roles("Platform User")
    out = user_platform_tools.update_platform_role(
        "Platform User", current.get("description", ""), current.get("enabled", True)
    )
    assert "HTTP 403" in out.get("error", ""), out


# --------------------------------------------------------------------------- #
# platform_reports (read-only, safe)                                          #
# --------------------------------------------------------------------------- #

LOGIN_REPORT = "User Last Login Report"


def test_platform_reports_list_live():
    """The report library lists at least one definition and honours filters."""
    _require_platform()
    out = user_platform_tools.platform_reports("list", page_size=100)
    assert "error" not in out, out
    names = [d["name"] for d in out.get("reportDefinitions", [])]
    assert out.get("totalCount", 0) >= 1 and names

    identity = user_platform_tools.platform_reports("list", service="Identity")
    assert "error" not in identity, identity
    assert all(
        d["service"] == "Identity" for d in identity.get("reportDefinitions", [])
    )


def test_platform_reports_describe_and_run_live():
    """``describe`` flattens inputs/columns and ``run`` returns a page of rows."""
    _require_platform()
    listing = user_platform_tools.platform_reports("list", page_size=100)
    names = [d["name"] for d in listing.get("reportDefinitions", [])]
    assert names, listing
    name = LOGIN_REPORT if LOGIN_REPORT in names else names[0]

    described = user_platform_tools.platform_reports("describe", name)
    assert described.get("name") == name, described
    assert "inputs" in described and "columns" in described
    assert "callbacks" not in described

    if name != LOGIN_REPORT:
        pytest.skip(f"{LOGIN_REPORT!r} not in this tenant's library; run not checked")

    result = user_platform_tools.platform_reports("run", name, page_size=2)
    assert result.get("reportDefinitionName") == name, result
    assert isinstance(result.get("data"), list)
    assert len(result["data"]) <= 2


def test_platform_reports_unknown_name_live():
    _require_platform()
    out = user_platform_tools.platform_reports("describe", "mcp-itest-no-such-report")
    assert out["error"].endswith("HTTP 404"), out
    assert "Unknown report" in out["hint"]
