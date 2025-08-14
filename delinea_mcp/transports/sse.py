from fastapi import FastAPI, Request, Depends
from fastapi.responses import Response
from mcp.server.sse import SseServerTransport
from mcp.server.fastmcp import FastMCP
from typing import Callable, Awaitable


def mount_sse_routes(app: FastAPI, mcp: FastMCP, dependency: Callable[..., Awaitable] | None = None) -> None:
    transport = SseServerTransport("/messages")

    async def sse_endpoint(request: Request, auth=Depends(dependency) if dependency else None):
        async with transport.connect_sse(request.scope, request.receive, request._send) as streams:
            await mcp._mcp_server.run(streams[0], streams[1], mcp._mcp_server.create_initialization_options())
        return
        #return Response()

    async def post_message(request: Request, auth=Depends(dependency) if dependency else None):
        await transport.handle_post_message(request.scope, request.receive, request._send)
        return

    app.add_api_route("/mcp/sse", sse_endpoint, methods=["GET"])
    app.mount("/messages", transport.handle_post_message)
