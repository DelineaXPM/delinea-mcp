from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
import pytest

from delinea_mcp.auth.validators import require_scopes
from delinea_mcp.auth import as_config


def test_require_scopes_missing_header():
    app = FastAPI()

    @app.get("/p")
    async def p(claims=Depends(require_scopes(["mcp.read"], audience="aud"))):
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/p")
    assert r.status_code == 401


def test_require_scopes_invalid_token():
    app = FastAPI()

    @app.get("/p")
    async def p(claims=Depends(require_scopes(["mcp.read"], audience="aud"))):
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/p", headers={"Authorization": "Bearer bad"})
    assert r.status_code == 401

