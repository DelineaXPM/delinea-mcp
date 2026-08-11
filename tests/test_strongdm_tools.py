"""Unit tests for delinea_mcp.strongdm_tools.

The strongdm SDK is an optional extra and is NOT installed for the unit
suite: a fake client is injected at the module seam (``_client``) and a
fake ``strongdm`` module supplies the model classes the mutating tools
construct. That the suite passes without the SDK is itself part of the
contract under test.
"""

import fnmatch
import os
import sys
import types
from dataclasses import dataclass

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from delinea_mcp import strongdm_tools


@dataclass
class FakeModel:
    def to_dict(self):
        return {k: v for k, v in vars(self).items()}


@dataclass
class FakeUser(FakeModel):
    id: str = ""
    email: str = ""
    first_name: str = ""
    last_name: str = ""
    permission_level: str = ""
    suspended: bool = False


@dataclass
class FakeResource(FakeModel):
    id: str = ""
    name: str = ""


@dataclass
class FakeRole(FakeModel):
    id: str = ""
    name: str = ""


@dataclass
class FakeGrant(FakeModel):
    id: str = ""
    account_id: str = ""
    resource_id: str = ""
    valid_until: object = None


@dataclass
class FakeAttachment(FakeModel):
    id: str = ""
    account_id: str = ""
    role_id: str = ""


@dataclass
class FakeAccountResource(FakeModel):
    account_id: str = ""
    resource_id: str = ""
    role_id: str = ""


@dataclass
class FakeHealthcheck(FakeModel):
    id: str = ""
    resource_id: str = ""
    node_name: str = ""
    healthy: bool = True


@dataclass
class FakeNode(FakeModel):
    id: str = ""
    name: str = ""
    state: str = "started"


def _matches(item, flt, args):
    """Minimal SDM filter emulation: 'field:?' with ? bound to args[0]."""
    if not flt:
        return True
    checks = flt.split()
    values = list(args)
    for check in checks:
        fieldname, _, placeholder = check.partition(":")
        want = values.pop(0) if placeholder == "?" else placeholder
        # the SDK filter key for Healthcheck resources is 'resourceid'
        attr = {"resourceid": "resource_id"}.get(fieldname, fieldname)
        have = str(getattr(item, attr, ""))
        if "*" in str(want):
            if not fnmatch.fnmatch(have.lower(), str(want).lower()):
                return False
        elif have != str(want):
            return False
    return True


class FakeService:
    def __init__(self, items=None, wrap=None):
        self.items = list(items or [])
        self.wrap = wrap  # response attribute name for create/get/update
        self.created = []
        self.deleted = []
        self.updated = []
        self.healthchecked = []

    def list(self, flt="", *args, **kwargs):
        return iter([i for i in self.items if _matches(i, flt, args)])

    def _resp(self, obj):
        return types.SimpleNamespace(**{self.wrap: obj})

    def get(self, id, **kwargs):
        for i in self.items:
            if i.id == id:
                return self._resp(i)
        raise KeyError(id)

    def create(self, obj, **kwargs):
        obj.id = obj.id or f"{self.wrap}-{len(self.items) + 1}"
        self.items.append(obj)
        self.created.append(obj)
        return self._resp(obj)

    def update(self, obj, **kwargs):
        self.updated.append(obj)
        return self._resp(obj)

    def delete(self, id, **kwargs):
        self.deleted.append(id)
        self.items = [i for i in self.items if i.id != id]

    def healthcheck(self, id, **kwargs):
        self.healthchecked.append(id)


class EntitlementService:
    def __init__(self, items=None):
        self.items = list(items or [])

    def list(self, subject_id, flt="", *args, **kwargs):
        return iter(self.items)


class FakeClient:
    def __init__(self):
        self.accounts = FakeService(wrap="account")
        self.resources = FakeService(wrap="resource")
        self.roles = FakeService(wrap="role")
        self.account_grants = FakeService(wrap="account_grant")
        self.account_attachments = FakeService(wrap="account_attachment")
        self.account_resources = FakeService()
        self.granted_account_entitlements = EntitlementService()
        self.requestable_account_entitlements = EntitlementService()
        self.granted_resource_entitlements = EntitlementService()
        self.requestable_resource_entitlements = EntitlementService()
        self.granted_role_entitlements = EntitlementService()
        self.health_checks = FakeService()
        self.access_requests = FakeService()
        self.queries = FakeService()
        self.activities = FakeService()
        self.nodes = FakeService()


def _fake_strongdm_module():
    mod = types.ModuleType("strongdm")
    mod.User = FakeUser
    mod.Role = FakeRole
    mod.AccountGrant = FakeGrant
    mod.AccountAttachment = FakeAttachment
    mod.Client = lambda *a, **k: FakeClient()
    return mod


@pytest.fixture
def client(monkeypatch):
    fake = FakeClient()
    fake.accounts.items = [FakeUser(id="a-1", email="alice@corp.com")]
    fake.resources.items = [FakeResource(id="r-1", name="prod-db")]
    fake.roles.items = [FakeRole(id="ro-1", name="engineering")]
    monkeypatch.setattr(strongdm_tools, "_client", fake)
    monkeypatch.setitem(sys.modules, "strongdm", _fake_strongdm_module())
    return fake


def test_sdk_missing_returns_guidance(monkeypatch):
    monkeypatch.setattr(strongdm_tools, "_client", None)
    monkeypatch.setitem(sys.modules, "strongdm", None)  # force ImportError
    out = strongdm_tools.sdm_search("resources", "x")
    assert "strongdm SDK is not installed" in out["error"]


def test_unconfigured_returns_guidance(monkeypatch):
    monkeypatch.setattr(strongdm_tools, "_client", None)
    monkeypatch.setattr(strongdm_tools, "sdm_access_key", None)
    monkeypatch.setattr(strongdm_tools, "sdm_secret_key", None)
    monkeypatch.setitem(sys.modules, "strongdm", _fake_strongdm_module())
    out = strongdm_tools.sdm_search("resources", "x")
    assert "SDM_API_ACCESS_KEY" in out["error"]


def test_search_accounts_wildcards_plain_text(client):
    out = strongdm_tools.sdm_search("accounts", "alice")
    assert out["count"] == 1
    assert out["results"][0]["email"] == "alice@corp.com"


def test_search_unknown_kind(client):
    out = strongdm_tools.sdm_search("nope", "x")
    assert "Unknown kind" in out["error"]


def test_grant_access_preview_makes_no_call(client):
    out = strongdm_tools.sdm_grant_access("alice@corp.com", "prod-db")
    assert "preview" in out
    assert client.account_grants.created == []


def test_grant_access_requires_comment(client):
    out = strongdm_tools.sdm_grant_access("alice@corp.com", "prod-db", confirm=True)
    assert "comment" in out["error"]
    assert client.account_grants.created == []


def test_grant_access_timeboxed(client):
    out = strongdm_tools.sdm_grant_access(
        "alice@corp.com",
        "prod-db",
        duration_hours=4,
        confirm=True,
        comment="incident 123",
    )
    (grant,) = client.account_grants.created
    assert grant.account_id == "a-1" and grant.resource_id == "r-1"
    assert grant.valid_until is not None
    assert out["result"]["account_id"] == "a-1"
    assert out["verification"]["id"] == grant.id


def test_grant_access_via_role(client):
    out = strongdm_tools.sdm_grant_access(
        "alice@corp.com", role_name="engineering", confirm=True, comment="c"
    )
    (att,) = client.account_attachments.created
    assert att.role_id == "ro-1"
    assert out["verification"]["account_id"] == "a-1"


def test_grant_access_ambiguous_returns_candidates(client):
    client.accounts.items.append(FakeUser(id="a-2", email="alice2@corp.com"))
    out = strongdm_tools.sdm_grant_access(
        "*alice*", "prod-db", confirm=True, comment="c"
    )
    assert "candidates" in out
    assert client.account_grants.created == []


def test_grant_access_needs_exactly_one_target(client):
    out = strongdm_tools.sdm_grant_access("alice@corp.com")
    assert "exactly one" in out["error"]


def test_revoke_access_deletes_and_reports_role_paths(client):
    client.account_grants.items = [
        FakeGrant(id="g-1", account_id="a-1", resource_id="r-1")
    ]
    client.account_resources.items = [
        FakeAccountResource(account_id="a-1", resource_id="r-1", role_id="ro-1")
    ]
    out = strongdm_tools.sdm_revoke_access(
        "alice@corp.com", "prod-db", confirm=True, comment="offboarding"
    )
    assert client.account_grants.deleted == ["g-1"]
    assert out["result"]["deleted_grant_ids"] == ["g-1"]
    assert out["role_derived_access"][0]["role_id"] == "ro-1"
    assert "detach the role" in out["note"]


def test_user_management_onboard(client):
    out = strongdm_tools.sdm_user_management(
        "onboard",
        email="bob@corp.com",
        data={"first_name": "Bob", "last_name": "B"},
        roles=["engineering"],
        confirm=True,
        comment="new hire",
    )
    assert out["result"]["email"] == "bob@corp.com"
    (att,) = client.account_attachments.created
    assert att.role_id == "ro-1"
    assert out["verification"]["email"] == "bob@corp.com"


def test_user_management_offboard(client):
    client.account_grants.items = [
        FakeGrant(id="g-1", account_id="a-1", resource_id="r-1")
    ]
    out = strongdm_tools.sdm_user_management(
        "offboard", email="alice@corp.com", confirm=True, comment="left company"
    )
    assert client.accounts.updated[0].suspended is True
    assert out["standing_grants"][0]["id"] == "g-1"


def test_user_management_preview(client):
    out = strongdm_tools.sdm_user_management("delete", email="alice@corp.com")
    assert "preview" in out
    assert client.accounts.deleted == []


def test_role_management_members(client):
    client.account_attachments.items = [
        FakeAttachment(id="at-1", account_id="a-1", role_id="ro-1")
    ]
    out = strongdm_tools.sdm_role_management("list_members", role_name="engineering")
    assert out["members"][0]["email"] == "alice@corp.com"


def test_role_management_remove_user(client):
    client.account_attachments.items = [
        FakeAttachment(id="at-1", account_id="a-1", role_id="ro-1")
    ]
    out = strongdm_tools.sdm_role_management(
        "remove_user",
        role_name="engineering",
        user_email="alice@corp.com",
        confirm=True,
        comment="c",
    )
    assert client.account_attachments.deleted == ["at-1"]
    assert out["verification"]["still_attached"] is False


def test_resource_health(client):
    client.health_checks.items = [
        FakeHealthcheck(id="h-1", resource_id="r-1", node_name="gw-1", healthy=True),
        FakeHealthcheck(id="h-2", resource_id="r-1", node_name="gw-2", healthy=False),
    ]
    out = strongdm_tools.sdm_resource_health("prod-db")
    assert client.resources.healthchecked == ["r-1"]
    assert out["healthy_nodes"] == 1 and out["unhealthy_nodes"] == 1


def test_access_requests_carry_approval_caveat(client):
    out = strongdm_tools.sdm_access_requests("list")
    assert "not available via the admin API" in out["note"]


def test_network_status_groups_by_state(client):
    client.nodes.items = [
        FakeNode(id="n-1", name="gw-1", state="started"),
        FakeNode(id="n-2", name="gw-2", state="dead"),
    ]
    out = strongdm_tools.sdm_network_status()
    assert out["summary"]["FakeNode"] == {"started": 1, "dead": 1}
    assert out["problem_nodes"][0]["name"] == "gw-2"


def test_audit_access_user(client):
    client.account_attachments.items = [
        FakeAttachment(id="at-1", account_id="a-1", role_id="ro-1")
    ]
    out = strongdm_tools.sdm_audit_access("user", "alice@corp.com")
    assert out["account"]["email"] == "alice@corp.com"
    assert out["roles"][0]["name"] == "engineering"


def test_register_respects_enabled_allowlist():
    class DummyMCP:
        def __init__(self):
            self.registered = []

        def tool(self, **kwargs):
            def deco(f):
                self.registered.append(f.__name__)
                return f

            return deco

    dummy = DummyMCP()
    strongdm_tools.register(dummy, {"search", "get_secret"})
    assert dummy.registered == []
    dummy = DummyMCP()
    strongdm_tools.register(dummy, set())
    assert "sdm_grant_access" in dummy.registered
    assert len(dummy.registered) == len(strongdm_tools.TOOLS)


def test_configure_resets_client(monkeypatch):
    monkeypatch.setattr(strongdm_tools, "_client", object())
    strongdm_tools.configure(api_host="app.eu.strongdm.com:443")
    assert strongdm_tools._client is None
    assert strongdm_tools.sdm_api_host == "app.eu.strongdm.com:443"
