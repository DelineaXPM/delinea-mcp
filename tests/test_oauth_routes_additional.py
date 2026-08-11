import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

from delinea_mcp.auth import as_config
from delinea_mcp.auth.routes import mount_oauth_routes


def make_client(psk="psk"):
    as_config.reset_state()
    app = FastAPI()
    mount_oauth_routes(app, {"registration_psk": psk, "oauth_db_path": ":memory:"})
    return TestClient(app)


def test_well_known_and_jwks_endpoints():
    client = make_client()
    r = client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    assert r.json()["issuer"] == "http://testserver"

    r = client.get("/jwks.json")
    assert r.status_code == 200
    assert "keys" in r.json()


def test_registration_disabled():
    client = make_client(psk=None)
    r = client.post("/oauth/register", json={"client_name": "c"})
    assert r.status_code == 400


def test_authorize_invalid_client():
    client = make_client()
    r = client.get(
        "/oauth/authorize",
        params={"client_id": "bad", "redirect_uri": "http://x", "scope": "mcp.read"},
    )
    assert r.status_code == 400


def test_token_unsupported_content_type(monkeypatch):
    client = make_client()
    r = client.post("/oauth/token", content="x", headers={"content-type": "text/plain"})
    assert r.status_code == 415


def test_token_unsupported_grant(monkeypatch):
    client = make_client()
    # register and create code
    data = client.post(
        "/oauth/register",
        json={
            "client_name": "c",
            "redirect_uris": ["http://localhost/callback"],
            "secret": "psk",
        },
    ).json()
    code = as_config.create_code(data["client_id"], ["mcp.read"])
    r = client.post(
        "/oauth/token",
        json={"grant_type": "other", "code": code},
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400


def test_protected_resource_metadata():
    client = make_client()
    for path in (
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource/mcp",
    ):
        r = client.get(path)
        assert r.status_code == 200
        data = r.json()
        # "resource" must equal the JWT audience (the origin) so RFC 8707
        # resource-indicator semantics stay coherent.
        assert data["resource"] == "http://testserver"
        assert data["authorization_servers"] == ["http://testserver"]
        assert data["bearer_methods_supported"] == ["header"]
        assert set(data["scopes_supported"]) == {"mcp.read", "mcp.write"}
