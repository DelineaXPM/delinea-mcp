import logging
from typing import Iterable

from fastapi import HTTPException, Request

from . import as_config

logger = logging.getLogger(__name__)


def require_scopes(
    required: Iterable[str],
    audience: str | None = None,
    chatgpt_no_scope_check: bool = False,
):
    """Return a dependency that enforces OAuth scope requirements.

    If ``chatgpt_no_scope_check`` is True, scope validation is skipped. This
    provides compatibility with ChatGPT which may omit scopes entirely.
    """

    async def dependency(request: Request):
        logger.debug("validating scopes %s", required)
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        token = auth_header.split(" ", 1)[1]
        try:
            claims = as_config.verify_token(token, audience=audience)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")
        token_scopes = set(claims.get("scope", "").split())
        if not chatgpt_no_scope_check and not set(required).intersection(token_scopes):
            raise HTTPException(status_code=403, detail="Insufficient scope")
        logger.debug("scope validation succeeded for %s", claims.get("client_id"))
        return claims

    return dependency
