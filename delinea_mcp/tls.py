"""Use the operating system's certificate store for outbound TLS.

``requests`` verifies servers against Python's bundled certifi list by
default. On networks that inspect TLS (Cloudflare Gateway, Zscaler, Netskope
and similar), every certificate is re-signed by a corporate root that the OS
trusts but certifi doesn't, so sign-in to Secret Server or the Platform fails
with ``CERTIFICATE_VERIFY_FAILED``. The same applies to on-premises Secret
Servers whose certificate comes from an internal CA.

``truststore`` (already used by the MCP SDK's HTTP client) makes Python's
``ssl`` module verify through the OS store instead, as pip and uv can.
Set ``DELINEA_TLS_TRUST=bundled`` to keep the certifi list.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_applied = False


def use_system_trust_store() -> bool:
    """Verify TLS against the OS certificate store; return True if active."""
    global _applied
    if _applied:
        return True
    choice = os.getenv("DELINEA_TLS_TRUST", "system").strip().lower()
    if choice in {"bundled", "certifi"}:
        logger.info("Using Python's bundled CA certificates (DELINEA_TLS_TRUST)")
        return False
    try:
        import truststore
    except ImportError:  # pragma: no cover - declared dependency
        logger.warning("truststore unavailable; using bundled CA certificates")
        return False
    truststore.inject_into_ssl()
    _applied = True
    logger.debug("Verifying TLS with the operating system's certificate store")
    return True
