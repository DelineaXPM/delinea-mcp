import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

from delinea_mcp.transports.sse import mount_sse_routes


class DummyMCP:
    def __init__(self):
        async def run(*a, **k):
            return None

        self._mcp_server = types.SimpleNamespace(
            run=run,
            create_initialization_options=lambda: None,
        )


def test_routes_mounted_and_post_accessible():
    app = FastAPI()
    mount_sse_routes(app, DummyMCP())
    routes = {r.path: getattr(r, "methods", set()) for r in app.router.routes}
    assert "/messages" in routes
    assert "GET" in routes.get("/mcp/sse", set())
    client = TestClient(app)
    r = client.post("/messages")
    assert r.status_code == 400
