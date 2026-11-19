"""The Secret Server URL is found from the Platform tenant unless overridden."""

from __future__ import annotations

import os

import pytest
from mcp.server.mcpserver import MCPServer

from delinea_mcp import api, server
from delinea_mcp.session import SessionManager

VAULT = "https://acme.secretservercloud.com"


def _vault(url=VAULT, **extra):
    entry = {
        "name": "Provisioned Secret Server",
        "type": "SecretServerCloud",
        "isDefault": False,
        "isGlobalDefault": False,
        "isActive": True,
        "connection": {"url": url, "oAuthProfileId": "secretserver"},
    }
    entry.update(extra)
    return entry


# --------------------------------------------------------------------------- #
# platform_host                                                               #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value",
    [
        "acme.delinea.app",
        "https://acme.delinea.app",
        "https://acme.delinea.app/",
        "  https://acme.delinea.app/identity/somewhere  ",
        "http://acme.delinea.app",
        "acme.delinea.app/",
    ],
)
def test_platform_host_accepts_urls(value):
    assert api.platform_host(value) == "acme.delinea.app"


def test_platform_host_keeps_port_and_blank():
    assert api.platform_host("https://acme.example:8443/x") == "acme.example:8443"
    assert api.platform_host("") == ""
    assert api.platform_host(None) == ""


# --------------------------------------------------------------------------- #
# select_vault_url                                                            #
# --------------------------------------------------------------------------- #


def test_select_picks_tenant_default():
    vaults = [
        _vault("https://other.example", isGlobalDefault=True),
        _vault(VAULT + "/", isDefault=True),
    ]
    assert api.select_vault_url(vaults, "acme") == VAULT


def test_select_falls_back_to_global_default_then_single():
    assert (
        api.select_vault_url(
            [_vault("https://a.example"), _vault(VAULT, isGlobalDefault=True)], "acme"
        )
        == VAULT
    )
    assert api.select_vault_url([_vault()], "acme") == VAULT


def test_select_skips_inactive_non_secret_server_and_plain_http():
    vaults = [
        _vault("https://inactive.example", isDefault=True, isActive=False),
        _vault("https://dsv.example", isDefault=True, type="DevOpsSecretsVault"),
        _vault("http://plain.example", isDefault=True),
        _vault(),
    ]
    assert api.select_vault_url(vaults, "acme") == VAULT


def test_select_without_vault_says_to_set_override():
    with pytest.raises(ValueError, match="no active Secret Server vault.*override"):
        api.select_vault_url([_vault(isActive=False)], "acme.delinea.app")


def test_select_ambiguous_lists_vaults():
    vaults = [_vault("https://a.example"), _vault("https://b.example")]
    with pytest.raises(ValueError, match="https://a.example, https://b.example"):
        api.select_vault_url(vaults, "acme.delinea.app")


# --------------------------------------------------------------------------- #
# DelineaSession                                                              #
# --------------------------------------------------------------------------- #


class _Resp:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code
        self.reason = ""
        self.text = ""

    def json(self):
        return self._data


class _FakeRequests:
    def __init__(self, vaults_resp):
        self.vaults_resp = vaults_resp
        self.headers = {}
        self.posts = []
        self.gets = []

    def Session(self):
        return self

    def post(self, url, data=None, headers=None):
        self.posts.append(url)
        return _Resp({"access_token": "tok"})

    def get(self, url, timeout=None):
        self.gets.append(url)
        return self.vaults_resp


@pytest.fixture
def fake(monkeypatch):
    for var in ("DELINEA_BASE_URL", "PLATFORM_HOSTNAME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DELINEA_USERNAME", "client")
    monkeypatch.setenv("DELINEA_PASSWORD", "secret")

    def make(vaults_resp=None):
        fake_requests = _FakeRequests(
            vaults_resp or _Resp({"vaults": [_vault(isDefault=True)]})
        )
        monkeypatch.setattr(api, "requests", fake_requests)
        return fake_requests

    return make


def test_session_discovers_vault_from_platform(fake):
    calls = fake()
    session = api.DelineaSession(platform_hostname="https://acme.delinea.app/")
    assert calls.posts == [
        "https://acme.delinea.app/identity/api/oauth2/token/xpmplatform"
    ]
    assert calls.gets == ["https://acme.delinea.app/vaultbroker/api/vaults"]
    assert session.base_url == VAULT
    assert session.platform_hostname == "acme.delinea.app"


def test_session_override_skips_lookup(fake):
    calls = fake()
    session = api.DelineaSession(
        platform_hostname="acme.delinea.app", base_url="https://override.example"
    )
    assert calls.gets == []
    assert session.base_url == "https://override.example"


def test_session_lookup_failure_points_at_override(fake):
    fake(_Resp({"message": "Not found"}, status_code=404))
    with pytest.raises(api.DelineaAPIError, match="Secret Server URL override"):
        api.DelineaSession(platform_hostname="acme.delinea.app")


def test_standalone_session_keeps_localhost_default(fake):
    calls = fake()
    session = api.DelineaSession()
    assert session.base_url == "https://localhost/SecretServer"
    assert calls.posts == ["https://localhost/SecretServer/oauth2/token"]
    assert calls.gets == []


# --------------------------------------------------------------------------- #
# Server wiring                                                               #
# --------------------------------------------------------------------------- #


@pytest.fixture
def init(monkeypatch):
    monkeypatch.setattr(server, "mcp", MCPServer("t"))
    monkeypatch.setattr(SessionManager, "_session", None)
    for var in (
        "DELINEA_MCP_PLUGIN",
        "DELINEA_BASE_URL",
        "PLATFORM_HOSTNAME",
        "PLATFORM_SERVICE_ACCOUNT",
        "PLATFORM_SERVICE_PASSWORD",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DELINEA_USERNAME", "client")
    monkeypatch.setenv("DELINEA_PASSWORD", "secret")
    return server._init_from_config


def test_plugin_without_any_url_refuses_localhost(init, monkeypatch):
    created = []
    monkeypatch.setattr(server, "DelineaSession", lambda **kw: created.append(kw))
    monkeypatch.setenv("DELINEA_MCP_PLUGIN", "1")
    with pytest.raises(ValueError, match="Delinea Platform URL"):
        init({})
    assert created == []


def test_pasted_platform_url_reaches_platform_tools_as_host(init, monkeypatch):
    from delinea_mcp import user_platform_tools

    seen, created = {}, {}
    monkeypatch.setattr(
        user_platform_tools, "configure", lambda **kw: seen.update(kw) or None
    )
    monkeypatch.setattr(
        server, "DelineaSession", lambda **kw: created.update(kw) or object()
    )
    monkeypatch.setenv("DELINEA_MCP_PLUGIN", "1")
    monkeypatch.setenv("PLATFORM_HOSTNAME", "https://acme.delinea.app/")
    init({})
    assert seen["hostname"] == "acme.delinea.app"
    assert created["platform_hostname"] == "acme.delinea.app"
    assert created["base_url"] == ""  # found from the Platform at sign-in


@pytest.mark.parametrize("via_platform", ["", "1"])
def test_seed_script_signs_in_where_asked(monkeypatch, via_platform):
    """Without LIVE_SS_VIA_PLATFORM the vault password must not go to the Platform."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "seed_test_tenant.py"
    spec = importlib.util.spec_from_file_location("seed_test_tenant", path)
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    monkeypatch.setenv("DELINEA_BASE_URL", "https://ss.example")
    monkeypatch.setenv("DELINEA_USERNAME", "svc")
    monkeypatch.setenv("PLATFORM_HOSTNAME", "acme.delinea.app")
    monkeypatch.setenv("LIVE_SS_VIA_PLATFORM", via_platform)
    seen = {}

    def fake_session(**kwargs):
        seen.update(kwargs, env_platform=os.getenv("PLATFORM_HOSTNAME"))

    monkeypatch.setattr(seed, "DelineaSession", fake_session)
    seed.session()
    if via_platform:
        assert seen["platform_hostname"] == "acme.delinea.app"
    else:
        assert seen["platform_hostname"] == "" and seen["env_platform"] is None


def test_platform_tools_configure_accepts_a_pasted_url(monkeypatch):
    from delinea_mcp import user_platform_tools

    monkeypatch.setattr(user_platform_tools, "platform_hostname", None)
    user_platform_tools.configure(hostname="https://acme.delinea.app/")
    assert user_platform_tools.platform_hostname == "acme.delinea.app"
