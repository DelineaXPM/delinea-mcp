import os

import pytest
import requests


def test_live_secret_request():
    secret_id = os.getenv("LIVE_SECRET_ID")
    if not secret_id:
        pytest.skip("LIVE_SECRET_ID not set")
    password_env_var = f"SECRET_PASSWORD_{secret_id}"
    username_env_var = f"SECRET_USERNAME_{secret_id}"
    client_secret = os.getenv(password_env_var)
    client_id = os.getenv(username_env_var)
    if not client_secret or not client_id:
        pytest.skip(f"{password_env_var} and {username_env_var} not set")
    base_url = os.getenv("DELINEA_BASE_URL", "https://localhost")
    oauth_url = base_url.rstrip("/") + "/oauth2/token"
    resp = requests.post(
        oauth_url,
        data={
            "username": client_id,
            "password": client_secret,
            "grant_type": "password",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert "access_token" in payload or "generatedToken" in payload
