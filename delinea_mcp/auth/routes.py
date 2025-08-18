import html
import logging
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from . import as_config

logger = logging.getLogger(__name__)


def mount_oauth_routes(app: FastAPI, cfg: dict | None = None) -> None:
    registration_psk = cfg.get("registration_psk") if cfg else None
    db_path = cfg.get("oauth_db_path", "oauth.db") if cfg else "oauth.db"
    key_path = cfg.get("jwt_key_path") if cfg else None
    as_config.init_keys(key_path)
    as_config.init_db(db_path)

    @app.get("/.well-known/oauth-authorization-server")
    async def well_known(request: Request):
        base = str(request.base_url).rstrip("/")
        logger.debug(
            "well_known from %s", request.client.host if request.client else "unknown"
        )
        return {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register",
            "jwks_uri": f"{base}/jwks.json",
            "scopes_supported": ["mcp.read", "mcp.write"],
        }

    @app.get("/jwks.json")
    async def jwks():
        logger.debug("jwks")
        return {"keys": [as_config.public_jwk()]}

    @app.post("/oauth/register")
    async def register(request: Request):
        if registration_psk is None:
            raise HTTPException(status_code=400, detail="Registration disabled")
        data = await request.json()
        logger.debug("register client %s", data.get("client_name"))
        return as_config.register_client(data.get("client_name"))

    @app.get("/oauth/authorize")
    async def authorize_form(
        client_id: str, redirect_uri: str, scope: str, state: str | None = None
    ):
        logger.debug("authorize_form %s", client_id)
        if client_id not in as_config.CLIENTS:
            raise HTTPException(status_code=400, detail="invalid client")

        escaped_client_id = html.escape(client_id)
        escaped_uri = html.escape(redirect_uri)
        escaped_scope = html.escape(scope)
        escaped_state = html.escape(state) if state else None

        html_content = (
            '<form method="post">'
            '<input type="password" name="secret" placeholder="Enter approval secret"/>'
            f'<input type="hidden" name="client_id" value="{escaped_client_id}"/>'
            f'<input type="hidden" name="redirect_uri" value="{escaped_uri}"/>'
            f'<input type="hidden" name="scope" value="{escaped_scope}"/>'
            + (
                f'<input type="hidden" name="state" value="{escaped_state}"/>'
                if state
                else ""
            )
            + '<button type="submit">Approve</button></form>'
        )
        return Response(content=html_content, media_type="text/html")

    @app.post("/oauth/authorize")
    async def authorize_submit(
        secret: str = Form(...),
        client_id: str = Form(...),
        redirect_uri: str = Form(...),
        scope: str = Form(...),
        state: str | None = Form(None),
    ):
        logger.debug("authorize_submit for %s", client_id)
        if secret != registration_psk:
            return Response(
                content="Invalid secret", status_code=401, media_type="text/html"
            )
        if client_id not in as_config.CLIENTS:
            raise HTTPException(status_code=400, detail="invalid client")
        code = as_config.create_code(client_id, scope.split())
        params = {"code": code}
        if state:
            params["state"] = state
        url = f"{redirect_uri}?" + urlencode(params)
        logger.debug("redirect to %s", url)
        return RedirectResponse(url, status_code=302)

    @app.post("/oauth/token")
    async def token(request: Request):
        logger.debug("token request")
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            data = await request.json()
        elif "application/x-www-form-urlencoded" in content_type:
            data = await request.form()
        else:
            raise HTTPException(status_code=415, detail="Unsupported content type")

        grant_type = data.get("grant_type")
        code = data.get("code")
        client_id = data.get("client_id")
        client_secret = data.get("client_secret")

        if grant_type != "authorization_code":
            raise HTTPException(status_code=400, detail="unsupported grant")

        auth = as_config.AUTH_CODES.pop(code, None)
        if not auth:
            raise HTTPException(status_code=400, detail="invalid code")

        if not client_id or not client_secret:
            raise HTTPException(status_code=400, detail="missing client credentials")
        if client_id != auth["client_id"] or not as_config.verify_client_secret(
            client_id, client_secret
        ):
            raise HTTPException(status_code=401, detail="invalid client credentials")

        audience = str(request.base_url).rstrip("/")
        access = as_config.issue_token(auth["client_id"], auth["scopes"], audience)
        logger.debug("issued token for %s", auth["client_id"])
        return {
            "access_token": access,
            "token_type": "bearer",
            "expires_in": 3600,
            "scope": " ".join(auth["scopes"]),
        }
