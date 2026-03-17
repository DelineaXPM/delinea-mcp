"""Tests for delinea_mcp.transports.streamable_http module."""

import types
from http import HTTPStatus
from unittest.mock import AsyncMock, patch

import pytest

from delinea_mcp.transports.streamable_http import (
    OAuthASGIMiddleware,
    mount_streamable_http_routes,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class DummyMCP:
    """Minimal stand-in for FastMCP with an _mcp_server attribute."""

    def __init__(self):
        self._mcp_server = types.SimpleNamespace(
            run=AsyncMock(),
            create_initialization_options=lambda: {},
        )


def _make_scope(method="POST", path="/mcp", headers=None):
    """Build a minimal ASGI HTTP scope dict."""
    if headers is None:
        headers = []
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [
            (
                k.encode() if isinstance(k, str) else k,
                v.encode() if isinstance(v, str) else v,
            )
            for k, v in headers
        ],
        "query_string": b"",
    }


async def _collect_response(app, scope):
    """Call an ASGI app and collect the response status + body."""
    status = None
    body_parts = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]
        elif message["type"] == "http.response.body":
            body_parts.append(message.get("body", b""))

    await app(scope, receive, send)
    return status, b"".join(body_parts)


# ---------------------------------------------------------------------------
# OAuthASGIMiddleware — init validation [DA-002]
# ---------------------------------------------------------------------------


class TestOAuthASGIMiddlewareInit:
    def test_raises_if_audience_missing(self):
        inner = AsyncMock()
        with pytest.raises(ValueError, match="audience"):
            OAuthASGIMiddleware(inner, {"scopes": ["mcp.read"]})

    def test_raises_if_scopes_missing(self):
        inner = AsyncMock()
        with pytest.raises(ValueError, match="scopes"):
            OAuthASGIMiddleware(inner, {"audience": "https://localhost:8000"})

    def test_accepts_valid_config(self):
        inner = AsyncMock()
        mw = OAuthASGIMiddleware(
            inner,
            {"audience": "https://localhost:8000", "scopes": ["mcp.read", "mcp.write"]},
        )
        assert mw is not None

    def test_chatgpt_no_scope_check_defaults_false(self):
        inner = AsyncMock()
        mw = OAuthASGIMiddleware(
            inner,
            {"audience": "https://localhost:8000", "scopes": ["mcp.read"]},
        )
        assert mw._chatgpt_no_scope_check is False


# ---------------------------------------------------------------------------
# OAuthASGIMiddleware — auth enforcement
# ---------------------------------------------------------------------------


class TestOAuthASGIMiddlewareAuth:
    @pytest.fixture()
    def inner_app(self):
        return AsyncMock()

    @pytest.fixture()
    def auth_config(self):
        return {
            "audience": "https://localhost:8000",
            "scopes": ["mcp.read", "mcp.write"],
        }

    @pytest.fixture()
    def middleware(self, inner_app, auth_config):
        return OAuthASGIMiddleware(inner_app, auth_config)

    @pytest.mark.asyncio
    async def test_missing_bearer_returns_401(self, middleware):
        scope = _make_scope(headers=[])
        status, _ = await _collect_response(middleware, scope)
        assert status == 401

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self, middleware):
        scope = _make_scope(headers=[("authorization", "Bearer bad-token")])
        with patch(
            "delinea_mcp.transports.streamable_http.as_config.verify_token",
            side_effect=Exception("invalid"),
        ):
            status, _ = await _collect_response(middleware, scope)
        assert status == 401

    @pytest.mark.asyncio
    async def test_insufficient_scopes_returns_403(self, middleware):
        scope = _make_scope(headers=[("authorization", "Bearer good-token")])
        with patch(
            "delinea_mcp.transports.streamable_http.as_config.verify_token",
            return_value={"scope": "other.scope", "client_id": "test"},
        ):
            status, _ = await _collect_response(middleware, scope)
        assert status == 403

    @pytest.mark.asyncio
    async def test_valid_token_passes_through_post(self, middleware, inner_app):
        scope = _make_scope(method="POST", headers=[("authorization", "Bearer good")])
        with patch(
            "delinea_mcp.transports.streamable_http.as_config.verify_token",
            return_value={"scope": "mcp.read mcp.write", "client_id": "test"},
        ):
            await middleware(scope, AsyncMock(), AsyncMock())
        inner_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_valid_token_passes_through_get(self, middleware, inner_app):
        scope = _make_scope(method="GET", headers=[("authorization", "Bearer good")])
        with patch(
            "delinea_mcp.transports.streamable_http.as_config.verify_token",
            return_value={"scope": "mcp.read mcp.write", "client_id": "test"},
        ):
            await middleware(scope, AsyncMock(), AsyncMock())
        inner_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_valid_token_passes_through_delete(self, middleware, inner_app):
        """DELETE (session termination) requires auth [DA-006]."""
        scope = _make_scope(method="DELETE", headers=[("authorization", "Bearer good")])
        with patch(
            "delinea_mcp.transports.streamable_http.as_config.verify_token",
            return_value={"scope": "mcp.read mcp.write", "client_id": "test"},
        ):
            await middleware(scope, AsyncMock(), AsyncMock())
        inner_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_missing_token_returns_401(self, middleware):
        """DELETE without token is rejected [DA-006]."""
        scope = _make_scope(method="DELETE", headers=[])
        status, _ = await _collect_response(middleware, scope)
        assert status == 401

    @pytest.mark.asyncio
    async def test_lowercase_authorization_header(self, middleware, inner_app):
        """ASGI headers may be lowercase (HTTP/2) [DA-009]."""
        scope = _make_scope(headers=[(b"authorization", b"Bearer good")])
        with patch(
            "delinea_mcp.transports.streamable_http.as_config.verify_token",
            return_value={"scope": "mcp.read mcp.write", "client_id": "test"},
        ):
            await middleware(scope, AsyncMock(), AsyncMock())
        inner_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_capitalized_authorization_header(self, middleware, inner_app):
        """ASGI headers may be capitalized (HTTP/1.1) [DA-009]."""
        scope = _make_scope(headers=[(b"Authorization", b"Bearer good")])
        with patch(
            "delinea_mcp.transports.streamable_http.as_config.verify_token",
            return_value={"scope": "mcp.read mcp.write", "client_id": "test"},
        ):
            await middleware(scope, AsyncMock(), AsyncMock())
        inner_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_chatgpt_no_scope_check_skips_scope_validation(self, inner_app):
        config = {
            "audience": "https://localhost:8000",
            "scopes": ["mcp.read", "mcp.write"],
            "chatgpt_no_scope_check": True,
        }
        mw = OAuthASGIMiddleware(inner_app, config)
        scope = _make_scope(headers=[("authorization", "Bearer good")])
        with patch(
            "delinea_mcp.transports.streamable_http.as_config.verify_token",
            return_value={"scope": "", "client_id": "chatgpt"},
        ):
            await mw(scope, AsyncMock(), AsyncMock())
        inner_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_scope_wiring_reaches_middleware(self):
        """Verify auth_config['scopes'] is actually used for checking [DA-002]."""
        inner = AsyncMock()
        config = {
            "audience": "https://localhost:8000",
            "scopes": ["custom.scope"],
        }
        mw = OAuthASGIMiddleware(inner, config)
        # Token has mcp.read but not custom.scope — should fail
        scope = _make_scope(headers=[("authorization", "Bearer good")])
        with patch(
            "delinea_mcp.transports.streamable_http.as_config.verify_token",
            return_value={"scope": "mcp.read", "client_id": "test"},
        ):
            status, _ = await _collect_response(mw, scope)
        assert status == 403

    @pytest.mark.asyncio
    async def test_logs_rejection_at_warning(self, middleware, caplog):
        """Rejected auth must log at WARNING [CC-006]."""
        import logging

        scope = _make_scope(headers=[])
        with caplog.at_level(logging.WARNING):
            await _collect_response(middleware, scope)
        assert any("Missing bearer token" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_non_http_scope_passes_through_without_auth(
        self, middleware, inner_app
    ):
        """Non-HTTP scopes (e.g., lifespan) bypass auth entirely."""
        scope = {"type": "lifespan"}
        receive = AsyncMock()
        send = AsyncMock()
        await middleware(scope, receive, send)
        inner_app.assert_called_once_with(scope, receive, send)


# ---------------------------------------------------------------------------
# Startup-window guard — passthrough when ready [DA-001]
# ---------------------------------------------------------------------------


class TestStartupGuardPassthrough:
    @pytest.mark.asyncio
    async def test_passes_through_when_session_manager_ready(self):
        """When _task_group is set, requests pass through to inner app."""
        from delinea_mcp.transports.streamable_http import _StartupGuard

        inner = AsyncMock()
        manager = types.SimpleNamespace(_task_group="not-none")
        guard = _StartupGuard(inner, manager)

        scope = _make_scope()
        receive = AsyncMock()
        send = AsyncMock()
        await guard(scope, receive, send)
        inner.assert_called_once_with(scope, receive, send)


# ---------------------------------------------------------------------------
# mount_streamable_http_routes — mounting and config passthrough
# ---------------------------------------------------------------------------


class TestMountStreamableHTTPRoutes:
    def test_mount_adds_mcp_route(self):
        from fastapi import FastAPI

        mcp = DummyMCP()
        lifespan, mount_fn = mount_streamable_http_routes(mcp)
        app = FastAPI(lifespan=lifespan)
        mount_fn(app)
        mount_paths = [r.path for r in app.router.routes if hasattr(r, "path")]
        assert "/mcp" in mount_paths

    def test_no_auth_config_skips_middleware(self):
        mcp = DummyMCP()
        lifespan, mount_fn = mount_streamable_http_routes(mcp, auth_config=None)
        assert lifespan is not None
        assert mount_fn is not None

    def test_auth_config_wraps_with_middleware(self):
        mcp = DummyMCP()
        auth_config = {
            "audience": "https://localhost:8000",
            "scopes": ["mcp.read", "mcp.write"],
        }
        lifespan, mount_fn = mount_streamable_http_routes(mcp, auth_config=auth_config)
        assert lifespan is not None
        assert mount_fn is not None

    def test_stateless_passed_to_session_manager(self):
        mcp = DummyMCP()
        with patch(
            "delinea_mcp.transports.streamable_http.StreamableHTTPSessionManager"
        ) as MockMgr:
            mount_streamable_http_routes(mcp, stateless=True)
            MockMgr.assert_called_once()
            assert MockMgr.call_args.kwargs.get("stateless") is True

    def test_json_response_passed_to_session_manager(self):
        mcp = DummyMCP()
        with patch(
            "delinea_mcp.transports.streamable_http.StreamableHTTPSessionManager"
        ) as MockMgr:
            mount_streamable_http_routes(mcp, json_response=True)
            MockMgr.assert_called_once()
            assert MockMgr.call_args.kwargs.get("json_response") is True

    def test_stateless_defaults_false(self):
        mcp = DummyMCP()
        with patch(
            "delinea_mcp.transports.streamable_http.StreamableHTTPSessionManager"
        ) as MockMgr:
            mount_streamable_http_routes(mcp)
            assert MockMgr.call_args.kwargs.get("stateless") is False

    def test_json_response_defaults_false(self):
        mcp = DummyMCP()
        with patch(
            "delinea_mcp.transports.streamable_http.StreamableHTTPSessionManager"
        ) as MockMgr:
            mount_streamable_http_routes(mcp)
            assert MockMgr.call_args.kwargs.get("json_response") is False


# ---------------------------------------------------------------------------
# Startup-window guard [DA-001]
# ---------------------------------------------------------------------------


class TestStartupWindowGuard:
    @pytest.mark.asyncio
    async def test_returns_503_before_session_manager_ready(self):
        """Requests before lifespan completes should get 503 [DA-001]."""
        mcp = DummyMCP()
        lifespan, mount_fn = mount_streamable_http_routes(mcp)

        from fastapi import FastAPI

        app = FastAPI(lifespan=lifespan)
        mount_fn(app)

        # Simulate a request WITHOUT entering lifespan (session manager not started)
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=True
        ) as client:
            resp = await client.post(
                "/mcp/",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == HTTPStatus.SERVICE_UNAVAILABLE
