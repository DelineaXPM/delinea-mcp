"""Streamable HTTP transport mounted into the existing FastAPI app.

The session manager is constructed directly (rather than via
``mcp.streamable_http_app()``) for two reasons:

- Starlette never runs the lifespan of a mounted sub-app, so the manager's
  mandatory ``run()`` must execute inside the *outer* FastAPI app's lifespan
  or every request fails with "Task group is not initialized".
- The SDK's app builder enables DNS-rebinding protection pinned to
  localhost Hosts, which would reject remote-connector requests with 421.
  The endpoint is bearer-guarded instead, matching the SSE transport.
"""

from __future__ import annotations

import contextlib
from typing import Awaitable, Callable

from fastapi import Depends, FastAPI, Request
from mcp.server.mcpserver import MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from delinea_mcp.transports.sse import _ResponseAlreadySent

MCP_PATH = "/mcp"


def build_session_manager(
    mcp: MCPServer, *, stateless: bool = True, json_response: bool = True
) -> StreamableHTTPSessionManager:
    """Create the session manager serving both protocol eras on one route.

    The manager era-routes on the ``MCP-Protocol-Version`` header:
    sessionless 2026-07-28 requests and 2024-11-05..2025-11-25 handshake
    clients are handled transparently. In stateless mode no session
    bookkeeping or event store is needed.
    """
    return StreamableHTTPSessionManager(
        app=mcp._lowlevel_server,
        json_response=json_response,
        stateless=stateless,
        security_settings=None,
    )


def mount_streamable_http_routes(
    app: FastAPI,
    manager: StreamableHTTPSessionManager,
    dependency: Callable[..., Awaitable] | None = None,
    *,
    stateless: bool = True,
) -> None:
    """Register the /mcp endpoint as a real FastAPI route.

    A route (not ``app.mount``) so the auth ``dependency`` actually runs —
    Depends() is skipped entirely for mounted ASGI sub-apps.

    In stateless mode only POST is registered: there is no session for the
    legacy standalone GET stream to serve (the transport would hold it open
    forever) and nothing for DELETE to terminate, so FastAPI's 405 is the
    honest answer for both.
    """

    async def mcp_endpoint(
        request: Request,
        auth=Depends(dependency) if dependency else None,  # noqa: B008 - FastAPI idiom
    ):
        await manager.handle_request(request.scope, request.receive, request._send)
        return _ResponseAlreadySent()

    app.add_api_route(
        MCP_PATH,
        mcp_endpoint,
        methods=["POST"] if stateless else ["GET", "POST", "DELETE"],
        include_in_schema=False,
    )


def make_lifespan(manager: StreamableHTTPSessionManager):
    """FastAPI lifespan that runs the session manager's task group.

    ``manager.run()`` is single-use; build one manager per app/process.
    """

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        async with manager.run():
            yield

    return lifespan
