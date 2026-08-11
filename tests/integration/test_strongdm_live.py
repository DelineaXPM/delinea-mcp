"""Live StrongDM integration tests.

Requires real SDM API credentials (Admin UI > Principals > Tokens):

    export SDM_API_ACCESS_KEY=... SDM_API_SECRET_KEY=...
    PYTHONPATH=. uv run pytest tests/integration/test_strongdm_live.py -v

Skipped entirely when the credentials (or the strongdm SDK) are absent.
Read-only: no mutations are performed against the live org.
"""

import importlib.util
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from delinea_mcp import strongdm_tools

pytestmark = pytest.mark.skipif(
    not (os.getenv("SDM_API_ACCESS_KEY") and os.getenv("SDM_API_SECRET_KEY"))
    or importlib.util.find_spec("strongdm") is None,
    reason="SDM_API_ACCESS_KEY/SDM_API_SECRET_KEY not set or strongdm not installed",
)


@pytest.fixture(scope="module", autouse=True)
def _configure():
    strongdm_tools.configure(
        api_host=os.getenv("SDM_API_HOST"),
        access_key=os.getenv("SDM_API_ACCESS_KEY"),
        secret_key=os.getenv("SDM_API_SECRET_KEY"),
    )
    yield
    strongdm_tools.configure()  # drop the cached client


def test_search_resources_live():
    out = strongdm_tools.sdm_search("resources", "", limit=5)
    assert "error" not in out
    assert isinstance(out["results"], list)


def test_search_accounts_live():
    out = strongdm_tools.sdm_search("accounts", "", limit=5)
    assert "error" not in out


def test_network_status_live():
    out = strongdm_tools.sdm_network_status()
    assert "error" not in out
    assert "summary" in out


def test_access_requests_live():
    out = strongdm_tools.sdm_access_requests("list", limit=5)
    assert "error" not in out


def test_grant_preview_is_safe_live():
    # confirm=False must never mutate; harmless even against production.
    accounts = strongdm_tools.sdm_search("accounts", "", limit=1)
    resources = strongdm_tools.sdm_search("resources", "", limit=1)
    if not accounts.get("results") or not resources.get("results"):
        pytest.skip("org has no accounts/resources to preview against")
    out = strongdm_tools.sdm_grant_access(
        accounts["results"][0]["email"], resources["results"][0]["name"]
    )
    assert "preview" in out or "candidates" in out or "error" in out
