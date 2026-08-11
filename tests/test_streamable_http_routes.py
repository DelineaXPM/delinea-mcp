import json

import pytest
from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from mcp.server.mcpserver import MCPServer

from delinea_mcp.transports.streamable_http import (
    MCP_PATH,
    build_session_manager,
    make_lifespan,
    mount_streamable_http_routes,
)

ACCEPT_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}

MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}

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


def _make_app(dependency=None, stateless=True):
    mcp = MCPServer("test-server", version="0.0.1")

    @mcp.tool()
    def ping() -> dict:
        return {"pong": True}

    manager = build_session_manager(mcp, stateless=stateless)
    app = FastAPI(lifespan=make_lifespan(manager))
    mount_streamable_http_routes(app, manager, dependency, stateless=stateless)
    return app


async def _guard():
    raise HTTPException(status_code=401, detail="no token")


@pytest.mark.asyncio
async def test_mcp_route_requires_auth():
    # /mcp carries every JSON-RPC call; it must be a real route so the
    # FastAPI dependency runs (app.mount would bypass it entirely).
    async with AsyncClient(
        transport=ASGITransport(app=_make_app(_guard)), base_url="http://t"
    ) as client:
        resp = await client.post(MCP_PATH, json=INITIALIZE, headers=ACCEPT_HEADERS)
    assert resp.status_code == 401


def test_handshake_era_initialize():
    # 2025-11-25 handshake clients still initialize against the same route.
    with TestClient(_make_app()) as client:  # context manager runs the lifespan
        resp = client.post(MCP_PATH, json=INITIALIZE, headers=ACCEPT_HEADERS)
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["protocolVersion"]
    assert result["serverInfo"]["name"] == "test-server"


def test_modern_era_stateless_request():
    # 2026-07-28 clients skip initialize: per-request _meta envelope,
    # Mcp-Protocol-Version and Mcp-Method headers, no session.
    headers = dict(ACCEPT_HEADERS)
    headers["Mcp-Protocol-Version"] = "2026-07-28"
    headers["Mcp-Method"] = "server/discover"
    body = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "server/discover",
        "params": {"_meta": MODERN_META},
    }
    with TestClient(_make_app()) as client:
        resp = client.post(MCP_PATH, json=body, headers=headers)
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert "2026-07-28" in result["supportedVersions"]
    assert result["resultType"] == "complete"


def test_modern_era_tool_call():
    headers = dict(ACCEPT_HEADERS)
    headers["Mcp-Protocol-Version"] = "2026-07-28"
    headers["Mcp-Method"] = "tools/call"
    headers["Mcp-Name"] = "ping"
    body = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"_meta": MODERN_META, "name": "ping", "arguments": {}},
    }
    with TestClient(_make_app()) as client:
        resp = client.post(MCP_PATH, json=body, headers=headers)
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"]) == {"pong": True}


def test_stateless_mode_rejects_get_and_delete():
    # No session exists in stateless mode: the legacy standalone GET stream
    # would be held open forever and DELETE has nothing to terminate, so
    # neither method is registered.
    with TestClient(_make_app()) as client:
        assert client.get(MCP_PATH, headers=ACCEPT_HEADERS).status_code == 405
        assert client.delete(MCP_PATH, headers=ACCEPT_HEADERS).status_code == 405


def test_stateful_mode_registers_get_and_delete():
    app = _make_app(stateless=False)
    (route,) = [r for r in app.router.routes if r.path == MCP_PATH]
    assert route.methods == {"GET", "POST", "DELETE"}


def test_oversized_body_rejected():
    with TestClient(_make_app()) as client:
        resp = client.post(
            MCP_PATH,
            content=b"x" * (4 * 1024 * 1024 + 10),
            headers=ACCEPT_HEADERS,
        )
    assert resp.status_code == 413
