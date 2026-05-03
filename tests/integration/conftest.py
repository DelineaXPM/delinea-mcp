"""Initialise a real Delinea session before integration tests run.

Without this, the SessionManager singleton is unconfigured and every
``server.<tool>`` call raises ``RuntimeError: Delinea session not
initialised``.  The unit tests don't need this because they patch the
session manager directly.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


@pytest.fixture(scope="session", autouse=True)
def _init_live_session():
    """Initialise the global SessionManager from env vars if available."""
    if not os.getenv("DELINEA_USERNAME") or not os.getenv("DELINEA_PASSWORD"):
        # Tests will skip individually via require_credentials().
        return

    from delinea_api import DelineaSession  # noqa: WPS433
    from delinea_mcp.session import SessionManager  # noqa: WPS433

    base_url = os.getenv("DELINEA_BASE_URL", "https://localhost/SecretServer")
    session = DelineaSession(
        base_url=base_url,
        username=os.environ["DELINEA_USERNAME"],
        platform_hostname=os.getenv("PLATFORM_HOSTNAME", ""),
    )
    SessionManager.init(session)
    yield
    # No teardown needed — sessions are cheap and the next test run will
    # construct a fresh one.
