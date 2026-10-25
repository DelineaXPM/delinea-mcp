"""``Origin`` validation on the MCP HTTP endpoints (DNS-rebinding guard).

Spec (Streamable HTTP, Security & Endpoint): servers MUST validate ``Origin``
and MUST answer 403 when it is present and invalid; absent means a
non-browser client and passes.
"""

import types

from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.testclient import TestClient
from mcp.server.mcpserver import MCPServer

from delinea_mcp.transports.origin import (
    allowed_origins_for,
    install_origin_guard,
    origin_allowed,
)
from delinea_mcp.transports.sse import mount_sse_routes
from delinea_mcp.transports.streamable_http import (
    MCP_PATH,
    build_session_manager,
    make_lifespan,
    mount_streamable_http_routes,
)

HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
FOREIGN = {**HEADERS, "Origin": "https://evil.example"}
LOCAL = {**HEADERS, "Origin": "http://localhost:5173"}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
ALLOWED = ["http://localhost:*", "https://mcp.example.com:*"]


def test_origin_allowed_exact_and_wildcard_port():
    assert origin_allowed("https://mcp.example.com", ALLOWED)
    assert origin_allowed("https://mcp.example.com:8443", ALLOWED)
    assert origin_allowed("HTTP://LOCALHOST:3000", ALLOWED)
    assert origin_allowed("http://localhost", ["http://localhost"])
    assert not origin_allowed("http://localhost:3000", ["http://localhost"])


def test_origin_allowed_rejects_lookalikes_and_null():
    # A wildcard port must not degrade into a prefix match on the host.
    assert not origin_allowed("http://localhost.evil.example", ALLOWED)
    assert not origin_allowed("http://localhost:3000.evil.example", ALLOWED)
    assert not origin_allowed("http://mcp.example.com", ALLOWED)  # wrong scheme
    assert not origin_allowed("null", ALLOWED)  # sandboxed iframes, file:// pages
    assert not origin_allowed("https://evil.example", ALLOWED)


def test_allowed_origins_for_defaults_external_hostname_and_config():
    defaults = allowed_origins_for({})
    assert "http://localhost:*" in defaults
    assert "https://127.0.0.1:*" in defaults
    assert "http://[::1]:*" in defaults

    derived = allowed_origins_for(
        {
            "external_hostname": "mcp.example.com",
            "allowed_origins": ["https://app.example.com"],
        }
    )
    assert set(defaults) < set(derived)
    # TLS may terminate at a proxy, so both schemes and any port are accepted.
    assert "http://mcp.example.com:*" in derived
    assert "https://mcp.example.com:*" in derived
    assert derived[-1] == "https://app.example.com"


def _streamable_app(dependency=None):
    mcp = MCPServer("test-server", version="0.0.1")

    @mcp.tool()
    def ping() -> dict:
        return {"pong": True}

    manager = build_session_manager(mcp)
    app = FastAPI(lifespan=make_lifespan(manager))
    guard = install_origin_guard(app, ALLOWED)
    mount_streamable_http_routes(app, manager, dependency, origin_guard=guard)
    return app


def test_mcp_route_rejects_foreign_origin_with_jsonrpc_error():
    with TestClient(_streamable_app()) as client:
        resp = client.post(MCP_PATH, json=INITIALIZE, headers=FOREIGN)
    assert resp.status_code == 403
    body = resp.json()
    assert body["jsonrpc"] == "2.0"
    assert body["error"]["code"] == -32600
    assert "id" not in body  # spec: an id-less JSON-RPC error response


def test_mcp_route_accepts_allowed_or_absent_origin():
    with TestClient(_streamable_app()) as client:
        allowed = client.post(MCP_PATH, json=INITIALIZE, headers=LOCAL)
        absent = client.post(MCP_PATH, json=INITIALIZE, headers=HEADERS)
    assert allowed.status_code == 200
    assert absent.status_code == 200  # non-browser MCP clients send no Origin


async def _bearer_guard():
    raise HTTPException(status_code=401, detail="no token")


def test_origin_check_runs_before_bearer_guard():
    with TestClient(_streamable_app(_bearer_guard)) as client:
        foreign = client.post(MCP_PATH, json=INITIALIZE, headers=FOREIGN)
        local = client.post(MCP_PATH, json=INITIALIZE, headers=LOCAL)
    assert foreign.status_code == 403
    assert local.status_code == 401  # the bearer guard still applies afterwards


class _DummyMCP:
    def __init__(self):
        async def run(*a, **k):
            return None

        self._lowlevel_server = types.SimpleNamespace(
            run=run, create_initialization_options=lambda: None
        )


def test_sse_channels_reject_foreign_origin():
    app = FastAPI()
    mount_sse_routes(app, _DummyMCP(), origin_guard=install_origin_guard(app, ALLOWED))
    client = TestClient(app)
    foreign = {"Origin": "https://evil.example"}
    assert client.get("/mcp/sse", headers=foreign).status_code == 403
    assert client.post("/messages/", headers=foreign).status_code == 403
    # An allowed origin reaches the transport, which then wants a session_id.
    local = {"Origin": "http://localhost:8000"}
    assert client.post("/messages/", headers=local).status_code == 400


def test_mount_without_origin_guard_is_unchanged():
    app = FastAPI()
    mount_sse_routes(app, _DummyMCP())
    foreign = {"Origin": "https://evil.example"}
    resp = TestClient(app).post("/messages/", headers=foreign)
    assert resp.status_code == 400  # no guard installed: the transport answers
