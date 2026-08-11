import logging
from typing import Iterable

from fastapi import HTTPException, Request

from . import as_config

logger = logging.getLogger(__name__)

PRM_PATH = "/.well-known/oauth-protected-resource"


def require_scopes(
    required: Iterable[str],
    audience: str | None = None,
    chatgpt_no_scope_check: bool = False,
):
    """Return a dependency that enforces OAuth scope requirements.

    If ``chatgpt_no_scope_check`` is True, scope validation is skipped. This
    provides compatibility with ChatGPT which may omit scopes entirely.

    Failures carry RFC 9728 / RFC 6750 ``WWW-Authenticate`` headers pointing
    at the protected-resource metadata so spec-compliant clients can discover
    the authorization server from a bare 401.
    """

    def _unauthorized(request: Request, description: str) -> HTTPException:
        prm = str(request.base_url).rstrip("/") + PRM_PATH
        return HTTPException(
            status_code=401,
            detail=description,
            headers={
                "WWW-Authenticate": (
                    f'Bearer error="invalid_token", '
                    f'error_description="{description}", '
                    f'resource_metadata="{prm}"'
                )
            },
        )

    async def dependency(request: Request):
        logger.debug("validating scopes %s", required)
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.lower().startswith("bearer "):
            raise _unauthorized(request, "Missing bearer token")
        token = auth_header.split(" ", 1)[1]
        try:
            claims = as_config.verify_token(token, audience=audience)
        except Exception:
            raise _unauthorized(request, "Invalid token")
        token_scopes = set(claims.get("scope", "").split())
        if not chatgpt_no_scope_check and not set(required).intersection(token_scopes):
            prm = str(request.base_url).rstrip("/") + PRM_PATH
            raise HTTPException(
                status_code=403,
                detail="Insufficient scope",
                headers={
                    "WWW-Authenticate": (
                        f'Bearer error="insufficient_scope", '
                        f'scope="{" ".join(required)}", '
                        f'resource_metadata="{prm}"'
                    )
                },
            )
        logger.debug("scope validation succeeded for %s", claims.get("client_id"))
        return claims

    return dependency
