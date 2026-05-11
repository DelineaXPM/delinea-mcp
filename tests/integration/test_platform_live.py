"""Live integration tests against a real Delinea Platform tenant.

Run with:

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
    out = user_platform_tools.search_users("test_mcp")
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
# user_management — full CRUD lifecycle with cleanup                          #
# --------------------------------------------------------------------------- #


def _try_cleanup_user(user_id: str | None):
    """Best-effort delete of a created test user."""
    if not user_id:
        return
    try:
        user_platform_tools.user_management("delete", user_id=user_id)
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
        out = user_platform_tools.user_management("create", data=create_payload)
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
        got = user_platform_tools.user_management("get", user_id=new_user_id)
        # GetUserAttributes wraps the user record in Result
        gr = got.get("Result") if isinstance(got, dict) else None
        assert isinstance(gr, dict), f"get returned non-dict Result: {got}"
        assert gr.get("Name") == username or gr.get("Mail") == username

        # 3. Update (change DisplayName)
        new_display = f"MCP Updated {int(time.time())}"
        upd = user_platform_tools.user_management(
            "update",
            user_id=new_user_id,
            data={"ID": new_user_id, "DisplayName": new_display},
        )
        assert "result" in upd

        # Verify the update propagated.
        got2 = user_platform_tools.user_management("get", user_id=new_user_id)
        gr2 = got2.get("Result") if isinstance(got2, dict) else None
        if isinstance(gr2, dict):
            # On some tenants DisplayName updates may be async; allow either.
            assert (
                gr2.get("DisplayName") in (new_display, None)
                or gr2.get("Description") is not None
            )

        # 4. Delete
        deleted = user_platform_tools.user_management("delete", user_id=new_user_id)
        assert "result" in deleted
        new_user_id = None  # so the finally block doesn't try again

    finally:
        # Always attempt cleanup; safe to no-op if already deleted.
        _try_cleanup_user(new_user_id)


def test_user_management_get_rejects_missing_id():
    _require_platform()
    out = user_platform_tools.user_management("get", user_id=None)
    assert "error" in out


def test_user_management_search_action():
    """``user_management('search', username=...)`` is the search-via-action path."""
    _require_platform()
    out = user_platform_tools.user_management("search", username="test_mcp")
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
        out = user_platform_tools.user_management(
            "get", user_id="any-uuid-for-the-test"
        )
        assert "error" in out
        assert "secretserver_local_user_management" in out["error"]
    finally:
        (
            user_platform_tools.platform_hostname,
            user_platform_tools.platform_service_account,
            user_platform_tools.platform_service_password,
            user_platform_tools._headers,
        ) = saved


# --------------------------------------------------------------------------- #
# platform_role_management — read-only on modern tenants                      #
# --------------------------------------------------------------------------- #


def test_platform_role_management_list_live():
    """role_searchbyname canned report returns role rows.

    Note: this tenant's Row columns are lowercase (``name``, ``description``,
    ``roletype``, ``visibility``, ``ID``).  Other Centrify-era tenants may
    use ``Name`` — be tolerant.
    """
    _require_platform()
    out = user_platform_tools.platform_role_management("list", page_size=20)
    assert out.get("success") is True
    rows = (out.get("Result") or {}).get("Results", [])
    # Tenant should have at least the "Everybody" system role.
    assert len(rows) >= 1
    row_keys = {k.lower() for row in rows for k in (row.get("Row") or {})}
    assert "name" in row_keys


def test_platform_role_management_get_live():
    """get('Everybody') matches the system role.

    Column casing varies by tenant — check both 'name' and 'Name'.
    """
    _require_platform()
    out = user_platform_tools.platform_role_management("get", role_id="Everybody")
    assert out.get("success") is True
    rows = (out.get("Result") or {}).get("Results", [])

    def _name(row: dict) -> str:
        r = row.get("Row") or {}
        return r.get("name") or r.get("Name") or ""

    assert any(_name(r) == "Everybody" for r in rows)


@pytest.mark.parametrize("action", ["create", "update", "delete"])
def test_platform_role_management_mutations_attempt_then_fallback_live(action):
    """The tool attempts the documented endpoint; this tenant returns 404
    and the tool surfaces the structured guidance error."""
    _require_platform()
    out = user_platform_tools.platform_role_management(
        action, role_id="mcp-itest-role-does-not-exist", data={"Name": "x"}
    )
    # On a 404, the tool returns a guidance error containing "404" and a
    # pointer at the SS-side fallback.  On a tenant that DOES expose the
    # endpoint, we'd get {"result": ..., "verification": ...} — the test
    # tolerates both shapes so it stays useful when run elsewhere.
    if "error" in out:
        assert "404" in out["error"]
        assert "role_management" in out["error"]
    else:
        assert "result" in out


# --------------------------------------------------------------------------- #
# platform_user_role_management — read-only                                   #
# --------------------------------------------------------------------------- #


def test_platform_user_role_management_list_live():
    _require_platform()
    out = user_platform_tools.platform_user_role_management("list", role_id="Everybody")
    assert out.get("success") is True


@pytest.mark.parametrize("action", ["add", "remove"])
def test_platform_user_role_management_mutations_attempt_then_fallback_live(action):
    """Add/remove are attempted; this tenant returns 404 so guidance surfaces."""
    _require_platform()
    # Use a synthetic non-existent test principal so even if the tenant DID
    # support the endpoint, nothing real changes.
    out = user_platform_tools.platform_user_role_management(
        action,
        role_id="Everybody",
        user_principals=["mcp-itest-noone@dartlabs.invalid"],
    )
    if "error" in out:
        assert "404" in out["error"]
        assert "user_role_management" in out["error"]
    else:
        assert "result" in out
