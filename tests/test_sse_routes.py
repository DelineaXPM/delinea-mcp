import types

from fastapi import FastAPI

from delinea_mcp.transports.sse import mount_sse_routes


class DummyMCP:
    def __init__(self):
        self._mcp_server = types.SimpleNamespace(
            run=lambda *a, **k: None,
            create_initialization_options=lambda: None,
        )


def test_post_routes_mounted():
    app = FastAPI()
    mount_sse_routes(app, DummyMCP())
    routes = {r.path: r for r in app.router.routes}
    assert type(routes["/mcp/sse"]).__name__ == "APIRoute"
    assert "GET" in getattr(routes["/mcp/sse"], "methods", set())
    assert type(routes["/messages"]).__name__ == "Mount"
