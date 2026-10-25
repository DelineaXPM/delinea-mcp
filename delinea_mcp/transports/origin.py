"""``Origin``-header validation for the MCP HTTP endpoints (DNS-rebinding guard).

The Streamable HTTP transport spec (2026-07-28, "Security & Endpoint") says
servers MUST validate the ``Origin`` header on all incoming connections and
MUST answer HTTP 403 when it is present and invalid. Without that check a web
page on an attacker-controlled domain that resolves to this server's address
(DNS rebinding) can drive the MCP endpoints from the victim's browser. Bearer
tokens are not ambient, so ``auth_mode: oauth`` deployments are not exposed;
``auth_mode: none`` deployments reachable from a browser are.

Only ``Origin`` is checked, never ``Host``: the SDK's own
``TransportSecuritySettings`` validates both and would answer 421 to remote
connectors behind reverse proxies, which is why the transports here are built
without it. Non-browser MCP clients (Claude Desktop, ChatGPT connectors, the
Inspector proxy) send no ``Origin`` header and are never affected.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Iterable, Sequence

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "[::1]")


class OriginNotAllowed(Exception):
    """Raised by the origin guard; turned into the 403 JSON-RPC error."""

    def __init__(self, origin: str) -> None:
        super().__init__(origin)
        self.origin = origin


def allowed_origins_for(cfg: dict[str, Any]) -> list[str]:
    """Origins the MCP HTTP endpoints accept from browsers.

    Always: loopback on any port (both schemes) and, when configured,
    ``external_hostname`` on any port and scheme (TLS may terminate at a
    proxy, so the browser's scheme and port need not match ours). Plus the
    config's ``allowed_origins`` list, which uses the same ``scheme://host``
    or ``scheme://host:*`` syntax.
    """
    hosts = list(LOOPBACK_HOSTS)
    external = cfg.get("external_hostname")
    if external:
        hosts.append(str(external))
    patterns = [
        f"{scheme}://{host}:*" for host in hosts for scheme in ("http", "https")
    ]
    patterns.extend(str(origin) for origin in cfg.get("allowed_origins") or [])
    return patterns


def origin_allowed(origin: str, patterns: Iterable[str]) -> bool:
    """True if ``origin`` matches a pattern exactly or by ``scheme://host:*``."""
    value = origin.strip().lower().rstrip("/")
    for pattern in patterns:
        pattern = pattern.strip().lower().rstrip("/")
        if pattern.endswith(":*"):
            base = pattern[:-2]
            if value == base:
                return True
            # Only a numeric port may follow; "http://localhost:80.evil" must
            # not pass as a prefix match on the host.
            if value.startswith(base + ":") and value[len(base) + 1 :].isdigit():
                return True
        elif value == pattern:
            return True
    return False


def install_origin_guard(
    app: FastAPI, allowed: Iterable[str]
) -> Callable[[Request], Awaitable[None]]:
    """Register the 403 handler on ``app`` and return the route dependency.

    Pass the returned callable as ``origin_guard=`` to the transport mount
    functions; it runs before the bearer guard on every MCP route and is not
    attached to the OAuth routes, which browsers legitimately call from the
    client's own origin.
    """
    patterns: Sequence[str] = tuple(allowed)

    async def _forbidden(request: Request, exc: Exception) -> JSONResponse:
        # Spec: the 403 body MAY be a JSON-RPC error response without an id.
        return JSONResponse(
            status_code=403,
            content={
                "jsonrpc": "2.0",
                "error": {"code": -32600, "message": "Origin not allowed"},
            },
        )

    app.add_exception_handler(OriginNotAllowed, _forbidden)

    async def require_allowed_origin(request: Request) -> None:
        origin = request.headers.get("origin")
        if origin is None:
            return  # not a browser request; nothing to validate
        if not origin_allowed(origin, patterns):
            logger.warning(
                "Rejected %s %s: Origin %r is not allowed",
                request.method,
                request.url.path,
                origin,
            )
            raise OriginNotAllowed(origin)

    return require_allowed_origin
