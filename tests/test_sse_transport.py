from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from httpx import ASGITransport, AsyncClient

from delinea_mcp.transports.sse import mount_sse_routes


async def _guard():
    raise HTTPException(status_code=401, detail="no token")


def _app_with_guard():
    app = FastAPI()
    mount_sse_routes(app, MagicMock(), _guard)
    return app


@pytest.mark.asyncio
async def test_sse_stream_requires_auth():
    async with AsyncClient(
        transport=ASGITransport(app=_app_with_guard()), base_url="http://t"
    ) as client:
        resp = await client.get("/mcp/sse")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_messages_post_channel_requires_auth():
    # The POST channel carries every JSON-RPC tools/call. It must be behind
    # the same dependency as the SSE stream; registering it via app.mount()
    # would bypass FastAPI dependency injection entirely.
    async with AsyncClient(
        transport=ASGITransport(app=_app_with_guard()), base_url="http://t"
    ) as client:
        resp = await client.post("/messages/?session_id=abc", content=b"{}")
    assert resp.status_code == 401
