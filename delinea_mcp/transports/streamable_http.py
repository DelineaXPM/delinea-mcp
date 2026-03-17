"""Streamable HTTP transport for DelineaMCP.

Provides ``mount_streamable_http_routes`` which wires an upstream
``StreamableHTTPSessionManager`` into a FastAPI application, and
``OAuthASGIMiddleware`` for Bearer-token authentication on the raw
ASGI callable.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from http import HTTPStatus
from typing import Any

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from delinea_mcp.auth import as_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ASGI OAuth Middleware
# ---------------------------------------------------------------------------


class OAuthASGIMiddleware:
    """ASGI middleware that validates Bearer tokens on every request.

    This replaces FastAPI's ``require_scopes()`` dependency for raw ASGI
    sub-applications (like ``StreamableHTTPSessionManager.handle_request``)
    where FastAPI's ``Request`` / ``HTTPException`` lifecycle does not apply.
    """

    def __init__(self, app: ASGIApp, auth_config: dict[str, Any]) -> None:
        if "audience" not in auth_config:
            raise ValueError("auth_config must contain 'audience' key")
        if "scopes" not in auth_config:
            raise ValueError("auth_config must contain 'scopes' key")

        self._app = app
        self._audience: str = auth_config["audience"]
        self._scopes: set[str] = set(auth_config["scopes"])
        self._chatgpt_no_scope_check: bool = auth_config.get(
            "chatgpt_no_scope_check", False
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        # Starlette Headers expects lowercase ASGI header names per spec,
        # but HTTP/1.1 headers may arrive with mixed case from non-compliant
        # ASGI servers.  Normalise to lowercase before wrapping. [DA-009]
        raw_headers = scope.get("headers", [])
        scope = dict(scope, headers=[(k.lower(), v) for k, v in raw_headers])
        headers = Headers(scope=scope)
        auth_header = headers.get("authorization", "")

        if not auth_header.lower().startswith("bearer "):
            logger.warning("Missing bearer token from %s", scope.get("path"))
            resp = PlainTextResponse(
                "Missing bearer token", status_code=HTTPStatus.UNAUTHORIZED
            )
            await resp(scope, receive, send)
            return

        token = auth_header.split(" ", 1)[1]
        try:
            claims = as_config.verify_token(token, audience=self._audience)
        except Exception:
            logger.warning("Invalid token for %s", scope.get("path"))
            resp = PlainTextResponse(
                "Invalid token", status_code=HTTPStatus.UNAUTHORIZED
            )
            await resp(scope, receive, send)
            return

        if not self._chatgpt_no_scope_check:
            token_scopes = set(claims.get("scope", "").split())
            if not self._scopes.intersection(token_scopes):
                logger.warning(
                    "Insufficient scope for %s (have=%s, need=%s)",
                    scope.get("path"),
                    token_scopes,
                    self._scopes,
                )
                resp = PlainTextResponse(
                    "Insufficient scope", status_code=HTTPStatus.FORBIDDEN
                )
                await resp(scope, receive, send)
                return

        await self._app(scope, receive, send)


# ---------------------------------------------------------------------------
# Startup-window guard [DA-001]
# ---------------------------------------------------------------------------


class _StartupGuard:
    """Wraps an ASGI app to return 503 when the session manager is not ready."""

    def __init__(self, app: ASGIApp, session_manager: StreamableHTTPSessionManager):
        self._app = app
        self._session_manager = session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self._session_manager._task_group is None:
            resp = PlainTextResponse(
                "Service starting up", status_code=HTTPStatus.SERVICE_UNAVAILABLE
            )
            await resp(scope, receive, send)
            return
        await self._app(scope, receive, send)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def mount_streamable_http_routes(
    mcp: FastMCP,
    auth_config: dict[str, Any] | None = None,
    stateless: bool = False,
    json_response: bool = False,
) -> tuple[Callable, Callable]:
    """Create a Streamable HTTP transport and return (lifespan, mount_fn).

    The caller is responsible for passing ``lifespan`` to
    ``FastAPI(lifespan=...)`` at construction time and then calling
    ``mount_fn(app)`` to attach the transport routes.

    Parameters
    ----------
    mcp:
        The FastMCP server instance.
    auth_config:
        Dict with required keys ``audience`` (str) and ``scopes``
        (list[str]), plus optional ``chatgpt_no_scope_check`` (bool).
        ``None`` disables auth.
    stateless:
        If True, creates a fresh transport per request with no session
        tracking.
    json_response:
        If True, uses JSON responses instead of SSE streams.

    Returns
    -------
    tuple[lifespan, mount_fn]
        ``lifespan`` — async context manager for FastAPI.
        ``mount_fn(app)`` — call with the FastAPI app to mount routes.
    """
    session_manager = StreamableHTTPSessionManager(
        app=mcp._mcp_server,
        event_store=None,
        json_response=json_response,
        stateless=stateless,
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: Any) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    def mount(app: Any) -> None:
        handler: ASGIApp = session_manager.handle_request
        handler = _StartupGuard(handler, session_manager)
        if auth_config is not None:
            handler = OAuthASGIMiddleware(handler, auth_config)
        app.mount("/mcp", handler)

    return lifespan, mount
