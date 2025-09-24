"""Test redirect URI validation security fixes."""

import pytest
from fastapi import HTTPException
from delinea_mcp.auth import as_config


def test_register_client_requires_redirect_uris():
    """Test that client registration requires redirect URIs."""
    as_config.init_db(":memory:")
    as_config.reset_state()

    # Should fail without redirect URIs
    with pytest.raises(ValueError, match="At least one redirect URI must be provided"):
        as_config.register_client("test_client")

    # Should fail with empty redirect URIs
    with pytest.raises(ValueError, match="At least one redirect URI must be provided"):
        as_config.register_client("test_client", [])


def test_register_client_validates_redirect_uri_format():
    """Test that client registration validates redirect URI format."""
    as_config.init_db(":memory:")
    as_config.reset_state()

    # Should fail with invalid schemes
    with pytest.raises(ValueError, match="Invalid redirect URI"):
        as_config.register_client("test_client", ["ftp://example.com"])

    with pytest.raises(ValueError, match="Invalid redirect URI"):
        as_config.register_client("test_client", ["javascript:alert(1)"])

    with pytest.raises(ValueError, match="Invalid redirect URI"):
        as_config.register_client("test_client", [""])

    # Should succeed with valid URIs
    result = as_config.register_client("test_client", ["https://example.com/callback"])
    assert "client_id" in result
    assert "client_secret" in result


def test_validate_redirect_uri():
    """Test redirect URI validation function."""
    as_config.init_db(":memory:")
    as_config.reset_state()

    # Register client with specific redirect URIs
    result = as_config.register_client("test_client", [
        "https://app.example.com/callback",
        "http://localhost:8080/callback"
    ])
    client_id = result["client_id"]

    # Valid URIs should pass
    assert as_config.validate_redirect_uri(client_id, "https://app.example.com/callback")
    assert as_config.validate_redirect_uri(client_id, "http://localhost:8080/callback")

    # Invalid URIs should fail
    assert not as_config.validate_redirect_uri(client_id, "https://evil.com/steal")
    assert not as_config.validate_redirect_uri(client_id, "https://app.example.com/different")
    assert not as_config.validate_redirect_uri(client_id, "http://app.example.com/callback")  # Different scheme

    # Non-existent client should fail
    assert not as_config.validate_redirect_uri("fake_client", "https://example.com")


def test_redirect_uri_exact_match():
    """Test that redirect URI validation requires exact matches."""
    as_config.init_db(":memory:")
    as_config.reset_state()

    result = as_config.register_client("test_client", ["https://app.example.com/callback"])
    client_id = result["client_id"]

    # Exact match should work
    assert as_config.validate_redirect_uri(client_id, "https://app.example.com/callback")

    # Partial matches should fail
    assert not as_config.validate_redirect_uri(client_id, "https://app.example.com/callback/extra")
    assert not as_config.validate_redirect_uri(client_id, "https://app.example.com")
    assert not as_config.validate_redirect_uri(client_id, "https://sub.app.example.com/callback")


def test_database_persistence():
    """Test that redirect URIs are persisted in database."""
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
        db_path = tmp.name

    try:
        # Register client with redirect URIs
        as_config.init_db(db_path)
        as_config.reset_state()
        result = as_config.register_client("test_client", ["https://example.com/callback"])
        client_id = result["client_id"]

        # Verify validation works
        assert as_config.validate_redirect_uri(client_id, "https://example.com/callback")

        # Restart (simulate server restart)
        as_config.init_db(db_path)

        # Should still work after restart
        assert as_config.validate_redirect_uri(client_id, "https://example.com/callback")
        assert not as_config.validate_redirect_uri(client_id, "https://evil.com")

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)