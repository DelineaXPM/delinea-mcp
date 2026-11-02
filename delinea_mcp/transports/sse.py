from typing import Awaitable, Callable

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response
from mcp.server.mcpserver import MCPServer
from mcp.server.sse import SseServerTransport

# Advertised verbatim to SSE clients (plus ?session_id=...) AND used as the
# guarded POST route path. These must be the same string: MCP clients POST to
# the advertised path without following redirects, so "/messages" vs
# "/messages/" would break every tool call with a 307.
MESSAGES_PATH = "/messages/"


class _ResponseAlreadySent(Response):
    """Returned by handlers whose response the MCP transport already sent
    via the raw ASGI send channel; stops FastAPI from starting a second
    response for the same request."""

    async def __call__(self, scope, receive, send) -> None:
        return


def mount_sse_routes(
    app: FastAPI,
    mcp: MCPServer,
    dependency: Callable[..., Awaitable] | None = None,
    *,
    origin_guard: Callable[..., Awaitable] | None = None,
) -> None:
    transport = SseServerTransport(MESSAGES_PATH)
    # The Origin check (DNS-rebinding guard, see transports/origin.py) is a
    # route-level dependency so it covers both channels and runs before the
    # bearer check, without touching the OAuth routes.
    route_dependencies = [Depends(origin_guard)] if origin_guard else None

    async def sse_endpoint(
        request: Request, auth=Depends(dependency) if dependency else None
    ):
        async with transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp._lowlevel_server.run(
                streams[0],
                streams[1],
                mcp._lowlevel_server.create_initialization_options(),
            )
        return _ResponseAlreadySent()

    async def post_message(
        request: Request, auth=Depends(dependency) if dependency else None
    ):
        await transport.handle_post_message(
            request.scope, request.receive, request._send
        )
        return _ResponseAlreadySent()

    app.add_api_route(
        "/mcp/sse", sse_endpoint, methods=["GET"], dependencies=route_dependencies
    )
    # Register the POST channel through FastAPI instead of app.mount():
    # Depends() does not apply to mounted ASGI sub-apps, so mounting
    # transport.handle_post_message directly leaves every tool call
    # (get_secret, update_secret_fields, ...) without the bearer-token
    # check. post_message above exists for exactly this route.
    app.add_api_route(
        MESSAGES_PATH, post_message, methods=["POST"], dependencies=route_dependencies
    )
