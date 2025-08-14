import json
import sys
import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
import html
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from delinea_mcp.auth import as_config
from delinea_mcp.auth.routes import mount_oauth_routes
from delinea_mcp.auth.validators import require_scopes


def test_token_sign_verify():
    token = as_config.issue_token("cid", ["mcp.read"], "http://host")
    claims = as_config.verify_token(token, audience="http://host")
    assert claims["client_id"] == "cid"
    assert "mcp.read" in claims["scope"]


def test_registration_psk():
    as_config.reset_state()
    app = FastAPI()
    mount_oauth_routes(app, {"registration_psk": "sekret", "oauth_db_path": ":memory:"})
    client = TestClient(app)
    r = client.post("/oauth/register", json={"client_name": "t"})
    assert r.status_code == 200
    data = r.json()
    assert "client_id" in data and "client_secret" in data


def test_scope_enforcement(monkeypatch):
    token = as_config.issue_token("cid", ["mcp.read"], "http://host")
    app = FastAPI()

    @app.get("/protected")
    async def protected(claims=Depends(require_scopes(["mcp.read"], audience="http://host"))):
        return {"client": claims["client_id"]}

    client = TestClient(app)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    bad = as_config.issue_token("cid", ["other"], "http://host")
    resp = client.get("/protected", headers={"Authorization": f"Bearer {bad}"})
    assert resp.status_code == 403


def test_chatgpt_scope_flag_allows_empty_scope():
    token = as_config.issue_token("cid", [], "http://host")
    app = FastAPI()

    @app.get("/protected")
    async def protected(
        claims=Depends(
            require_scopes(
                ["mcp.read"], audience="http://host", chatgpt_no_scope_check=True
            )
        )
    ):
        return {"client": claims["client_id"]}

    client = TestClient(app)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_registration_persistence(tmp_path):
    db = tmp_path / "oauth.db"
    as_config.init_db(db)
    as_config.reset_state()
    info = as_config.register_client("t")
    cid = info["client_id"]
    # simulate restart
    as_config.init_db(db)
    assert cid in as_config.CLIENTS


def test_jwt_key_persistence(tmp_path):
    key = tmp_path / "jwt.json"
    as_config.init_keys(key)
    token = as_config.issue_token("cid", ["mcp.read"], "http://host")
    # simulate restart
    as_config.init_keys(key)
    claims = as_config.verify_token(token, audience="http://host")
    assert claims["client_id"] == "cid"


def test_authorize_form_escapes_html():
    as_config.reset_state()
    app = FastAPI()
    mount_oauth_routes(app, {"registration_psk": "psk", "oauth_db_path": ":memory:"})
    client = TestClient(app)

    malicious_cid = "<cid>"
    as_config.CLIENTS[malicious_cid] = {
        "client_secret": as_config._hash_secret("s"),
        "name": "bad",
    }

    params = {
        "client_id": malicious_cid,
        "redirect_uri": "http://host/cb?x=<script>",
        "scope": "mcp.read <tag>",
        "state": "evil<&>",
    }

    r = client.get("/oauth/authorize", params=params)
    assert r.status_code == 200
    text = r.text

    assert html.escape(malicious_cid) in text
    assert html.escape(params["redirect_uri"]) in text
    assert html.escape(params["scope"]) in text
    assert html.escape(params["state"]) in text

