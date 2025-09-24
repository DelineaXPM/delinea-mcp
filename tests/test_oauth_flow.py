import asyncio
import json
import os
import sys
import types

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from httpx_sse import aconnect_sse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import importlib

from delinea_mcp.auth import as_config
from delinea_mcp.auth.routes import mount_oauth_routes
from delinea_mcp.auth.validators import require_scopes
from delinea_mcp.transports.sse import mount_sse_routes


class DummySession:
    def authenticate(self, *a, **k):
        pass

    def request(self, *a, **k):
        raise AssertionError("no network")


def setup_server(monkeypatch):
    monkeypatch.setattr("delinea_api.DelineaSession", lambda *a, **k: DummySession())
    import server

    importlib.reload(server)
    as_config.reset_state()
    app = FastAPI()
    mount_oauth_routes(app, {"registration_psk": "psk", "oauth_db_path": ":memory:"})
    mount_sse_routes(
        app, server.mcp, require_scopes(["mcp.read"], audience="http://testserver")
    )
    return app


@pytest.mark.asyncio
async def test_full_oauth_flow(monkeypatch):
    app = setup_server(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post("/oauth/register", json={
            "client_name": "c",
            "redirect_uris": ["http://testserver/cb"]
        })
        data = r.json()
        cid = data["client_id"]
        cs = data["client_secret"]
        r = await client.get(
            "/oauth/authorize",
            params={
                "client_id": cid,
                "redirect_uri": "http://testserver/cb",
                "scope": "mcp.read",
            },
        )
        assert r.status_code == 200
        assert "<form" in r.text

        r = await client.post(
            "/oauth/authorize",
            data={
                "secret": "bad",
                "client_id": cid,
                "redirect_uri": "http://testserver/cb",
                "scope": "mcp.read",
            },
        )
        assert r.status_code == 401

        r = await client.post(
            "/oauth/authorize",
            data={
                "secret": "psk",
                "client_id": cid,
                "redirect_uri": "http://testserver/cb",
                "scope": "mcp.read",
            },
        )
        assert r.status_code == 302
        code = r.headers["location"].split("code=")[1]
        r = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": cid,
                "client_secret": cs,
            },
        )
        tok = r.json()["access_token"]
        assert tok


@pytest.mark.asyncio
async def test_token_invalid_secret(monkeypatch):
    app = setup_server(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post("/oauth/register", json={"client_name": "c"})
        data = r.json()
        cid = data["client_id"]
        code = as_config.create_code(cid, ["mcp.read"])
        r = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": cid,
                "client_secret": "wrong",
            },
        )
        assert r.status_code == 401
