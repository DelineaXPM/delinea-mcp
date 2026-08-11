import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from delinea_mcp.auth import as_config
from delinea_mcp.auth.validators import require_scopes


def test_require_scopes_missing_header():
    app = FastAPI()

    @app.get("/p")
    async def p(
        claims=Depends(require_scopes(["mcp.read"], audience="aud")),  # noqa: B008
    ):
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/p")
    assert r.status_code == 401


def test_require_scopes_invalid_token():
    app = FastAPI()

    @app.get("/p")
    async def p(
        claims=Depends(require_scopes(["mcp.read"], audience="aud")),  # noqa: B008
    ):
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/p", headers={"Authorization": "Bearer bad"})
    assert r.status_code == 401


def test_401_carries_resource_metadata_header():
    app = FastAPI()

    @app.get("/p")
    async def p(
        claims=Depends(require_scopes(["mcp.read"], audience="aud")),  # noqa: B008
    ):
        return {"ok": True}

    client = TestClient(app)
    for headers in ({}, {"Authorization": "Bearer bad"}):
        r = client.get("/p", headers=headers)
        assert r.status_code == 401
        www = r.headers["WWW-Authenticate"]
        assert 'error="invalid_token"' in www
        assert (
            'resource_metadata="http://testserver'
            '/.well-known/oauth-protected-resource"' in www
        )


def test_403_insufficient_scope_header():
    token = as_config.issue_token("cid", ["mcp.other"], "aud")
    app = FastAPI()

    @app.get("/p")
    async def p(
        claims=Depends(require_scopes(["mcp.read"], audience="aud")),  # noqa: B008
    ):
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/p", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
    www = r.headers["WWW-Authenticate"]
    assert 'error="insufficient_scope"' in www
    assert 'scope="mcp.read"' in www
    assert "resource_metadata=" in www
