import hashlib
import json
import logging
import os
import secrets
import sqlite3
import time
from pathlib import Path

from authlib.jose import JsonWebKey, jwt

logger = logging.getLogger(__name__)

_PRIVATE_KEY: JsonWebKey | None = None
_PUBLIC_JWK: dict | None = None
_PUBLIC_KEY: JsonWebKey | None = None
_KEY_FILE: Path | None = None

CLIENTS: dict[str, dict] = {}
AUTH_CODES: dict[str, dict] = {}
_DB_CONN: sqlite3.Connection | None = None


def _hash_secret(secret: str) -> str:
    """Return a SHA-256 hash of the provided secret."""
    return hashlib.sha256(secret.encode()).hexdigest()


def init_keys(path: str | Path | None) -> None:
    """Initialise or load the RSA key pair used for JWT signing."""
    global _PRIVATE_KEY, _PUBLIC_JWK, _PUBLIC_KEY, _KEY_FILE
    if path is None or str(path) == ":memory:":
        _KEY_FILE = None
        _PRIVATE_KEY = JsonWebKey.generate_key("RSA", 2048, is_private=True)
        _PUBLIC_JWK = _PRIVATE_KEY.as_dict(is_private=False)
        _PUBLIC_KEY = JsonWebKey.import_key(_PUBLIC_JWK)
        logger.debug("Generated ephemeral OAuth keys")
        return

    _KEY_FILE = Path(path)
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _KEY_FILE.exists():
        try:
            data = json.loads(_KEY_FILE.read_text())
            _PRIVATE_KEY = JsonWebKey.import_key(data)
            _PUBLIC_JWK = _PRIVATE_KEY.as_dict(is_private=False)
            _PUBLIC_KEY = JsonWebKey.import_key(_PUBLIC_JWK)
            logger.debug("Loaded OAuth keys from %s", _KEY_FILE)
            return
        except Exception:
            logger.exception("Failed to load JWT keys from %s", _KEY_FILE)

    _PRIVATE_KEY = JsonWebKey.generate_key("RSA", 2048, is_private=True)
    _PUBLIC_JWK = _PRIVATE_KEY.as_dict(is_private=False)
    _PUBLIC_KEY = JsonWebKey.import_key(_PUBLIC_JWK)
    try:
        _KEY_FILE.write_text(json.dumps(_PRIVATE_KEY.as_dict()))
        logger.debug("Generated new OAuth keys at %s", _KEY_FILE)
    except Exception:
        logger.exception("Failed to write JWT keys to %s", _KEY_FILE)


def init_db(path: str | Path) -> None:
    """Initialise the client database from the given path."""
    global _DB_CONN
    if _DB_CONN:
        _DB_CONN.close()
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    _DB_CONN = sqlite3.connect(str(path), check_same_thread=False)
    with _DB_CONN:
        _DB_CONN.execute(
            "CREATE TABLE IF NOT EXISTS clients (client_id TEXT PRIMARY KEY, client_secret TEXT, name TEXT, redirect_uris TEXT)"
        )
        # Add redirect_uris column to existing tables if it doesn't exist
        try:
            _DB_CONN.execute("ALTER TABLE clients ADD COLUMN redirect_uris TEXT")
        except sqlite3.OperationalError:
            # Column already exists
            pass
    if str(path) != ":memory:":
        try:
            os.chmod(path, 0o600)
        except Exception:
            logger.exception("Failed to set permissions on %s", path)
    CLIENTS.clear()
    for row in _DB_CONN.execute(
        "SELECT client_id, client_secret, name, redirect_uris FROM clients"
    ):
        cid, secret, name, redirect_uris = row
        redirect_uri_list = json.loads(redirect_uris) if redirect_uris else []
        CLIENTS[cid] = {
            "client_secret": secret,
            "name": name,
            "redirect_uris": redirect_uri_list,
        }
    logger.debug("OAuth DB initialised at %s", path)


def reset_state() -> None:
    CLIENTS.clear()
    AUTH_CODES.clear()
    if _DB_CONN:
        with _DB_CONN:
            _DB_CONN.execute("DELETE FROM clients")
    logger.debug("OAuth state reset")


def register_client(
    client_name: str | None = None, redirect_uris: list[str] | None = None
) -> dict:
    logger.debug("register_client(%s)", client_name)

    # Validate redirect URIs
    if not redirect_uris:
        raise ValueError("At least one redirect URI must be provided")

    for uri in redirect_uris:
        if not uri or not uri.startswith(("http://", "https://")):
            raise ValueError(f"Invalid redirect URI: {uri}")

    client_id = secrets.token_urlsafe(8)
    client_secret = secrets.token_urlsafe(16)
    hashed = _hash_secret(client_secret)
    redirect_uris_json = json.dumps(redirect_uris)

    CLIENTS[client_id] = {
        "client_secret": hashed,
        "name": client_name or "",
        "redirect_uris": redirect_uris,
    }

    if _DB_CONN:
        with _DB_CONN:
            _DB_CONN.execute(
                "INSERT INTO clients (client_id, client_secret, name, redirect_uris) VALUES (?, ?, ?, ?)",
                (client_id, hashed, client_name or "", redirect_uris_json),
            )
    logger.debug("registered %s", client_id)
    return {"client_id": client_id, "client_secret": client_secret}


def create_code(client_id: str, scopes: list[str]) -> str:
    code = secrets.token_urlsafe(8)
    AUTH_CODES[code] = {"client_id": client_id, "scopes": scopes}
    logger.debug("created code for %s", client_id)
    return code


def verify_client_secret(client_id: str, secret: str) -> bool:
    """Validate a client secret against the stored hash."""
    entry = CLIENTS.get(client_id)
    if not entry:
        return False
    return entry.get("client_secret") == _hash_secret(secret)


def validate_redirect_uri(client_id: str, redirect_uri: str) -> bool:
    """Validate that the redirect URI is registered for the given client."""
    entry = CLIENTS.get(client_id)
    if not entry:
        return False

    allowed_uris = entry.get("redirect_uris", [])
    return redirect_uri in allowed_uris


def issue_token(
    client_id: str, scopes: list[str], audience: str, expires_in: int = 3600
) -> str:
    header = {"alg": "RS256"}
    payload = {
        "aud": audience,
        "scope": " ".join(scopes),
        "exp": int(time.time()) + expires_in,
        "client_id": client_id,
    }
    token = jwt.encode(header, payload, _PRIVATE_KEY).decode()
    logger.debug("issued token for %s", client_id)
    return token


def public_jwk() -> dict:
    logger.debug("public_jwk requested")
    return _PUBLIC_JWK


def verify_token(token: str, audience: str | None = None) -> dict:
    logger.debug("verifying token")
    claims = jwt.decode(token, _PUBLIC_KEY)
    if audience and claims.get("aud") != audience:
        raise ValueError("audience mismatch")
    if claims.get("exp") and int(claims["exp"]) < int(time.time()):
        raise ValueError("token expired")
    logger.debug("token verified for %s", claims.get("client_id"))
    return claims


# Initialise with ephemeral keys by default
init_keys(None)
