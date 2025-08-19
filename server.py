from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from delinea_api import DelineaSession
from delinea_mcp import tools, user_platform_tools
from delinea_mcp.config import load_config
from delinea_mcp.tools import (
    check_secret_template,
    check_secret_template_field,
    fetch,
    folder_management,
    get_folder,
    get_secret,
    get_secret_environment_variable,
    get_secret_template_field,
    group_management,
    group_role_management,
    health_check,
    role_management,
    search,
    search_folders,
    search_secrets,
    search_users,
    user_group_management,
    user_management,
    user_role_management,
)

logger = logging.getLogger(__name__)
_debug = False

mcp = FastMCP("DelineaMCP")
delinea = None


def _init_from_config(cfg: dict[str, Any]) -> None:
    """Initialise sessions and tool registration from a config dict."""
    tools.configure(cfg)
    global delinea, _debug
    _debug = bool(cfg.get("debug", False))
    if _debug and not logging.getLogger().handlers:
        logging.basicConfig(level=logging.DEBUG)
    elif _debug:
        logging.getLogger().setLevel(logging.DEBUG)
    if not cfg.get("delinea_username"):
        os.environ.pop("DELINEA_USERNAME", None)
    username = cfg.get("delinea_username")
    password = os.getenv("DELINEA_PASSWORD")
    base_url = cfg.get("delinea_base_url") or os.getenv("DELINEA_BASE_URL")

    if username and password:
        delinea = DelineaSession(base_url=base_url or "", username=username)
    else:

        class DummySession:
            def request(self, *a, **k):
                raise RuntimeError("Delinea session not initialised")

        delinea = DummySession()

    tools.init(delinea)
    enabled = set(cfg.get("enabled_tools", []))
    tools.register(mcp, enabled)

    if cfg.get("platform_hostname"):
        user_platform_tools.configure(
            hostname=cfg.get("platform_hostname"),
            service_account=cfg.get("platform_service_account"),
            service_password=os.getenv("PLATFORM_SERVICE_PASSWORD"),
            tenant_id=cfg.get("platform_tenant_id"),
        )
        user_platform_tools.register(mcp)
        logger.debug("Registered user platform tools from config")
    else:
        logger.info("Platform tools disabled; no hostname in config")


# Load default config on import
_init_from_config(load_config(Path("config.json")))


def generate_sql_query(user_query: str) -> str:
    logger.debug("generate_sql_query(%s)", user_query)
    return tools.generate_sql_query(user_query)


def run_report(sql_query: str, report_name: str | None = None) -> dict:
    logger.debug("run_report(%s)", sql_query)
    return tools.run_report(sql_query, report_name)


def ai_generate_and_run_report(description: str) -> dict:
    logger.debug("ai_generate_and_run_report(%s)", description)
    sql = generate_sql_query(description)
    result = run_report(sql, report_name=f"AI Generated: {int(time.time())}")
    result["generated_sql"] = sql
    return result


def list_example_reports() -> str:
    logger.debug("list_example_reports")
    return tools.list_example_reports()


def run_server(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args(argv)

    # Validate and sanitize the config path
    config_path = os.path.abspath(args.config)
    if not os.path.isfile(config_path):
        raise ValueError(f"Invalid config file path: {config_path}")

    cfg = load_config(Path(config_path))
    _init_from_config(cfg)

    auth_mode = cfg.get("auth_mode", "none").lower()
    transport_mode = cfg.get("transport_mode", "stdio").lower()
    port = int(cfg.get("port", 8000))
    ssl_keyfile = cfg.get("ssl_keyfile")
    ssl_certfile = cfg.get("ssl_certfile")

    if transport_mode == "sse" or auth_mode == "oauth":
        try:
            import fastapi  # noqa: F401
            import uvicorn  # noqa: F401
        except Exception as exc:
            raise RuntimeError("fastapi and uvicorn are required for SSE mode") from exc

    if auth_mode == "oauth" and transport_mode != "sse":
        raise ValueError("OAuth mode requires TRANSPORT_MODE=sse")

    uvicorn_kwargs = {}
    if ssl_keyfile and ssl_certfile:
        uvicorn_kwargs["ssl_keyfile"] = ssl_keyfile
        uvicorn_kwargs["ssl_certfile"] = ssl_certfile

    scheme = "https" if ssl_keyfile and ssl_certfile else "http"
    host = cfg.get("external_hostname", "0.0.0.0")
    audience = f"{scheme}://{host}:{port}"

    match auth_mode, transport_mode:
        case ("none", "stdio"):
            mcp.run(transport="stdio")
        case ("none", "sse"):
            import uvicorn
            from fastapi import FastAPI, Request

            from delinea_mcp.transports.sse import mount_sse_routes

            app = FastAPI(title="Delinea MCP")
            if _debug:

                @app.middleware("http")
                async def log_requests(request: Request, call_next):
                    body = await request.body()
                    logger.debug(
                        "Request from %s to %s headers=%s body=%s",
                        request.client.host if request.client else "unknown",
                        request.url.path,
                        dict(request.headers),
                        body.decode("utf-8", "replace"),
                    )
                    return await call_next(request)

            mount_sse_routes(app, mcp)
            uvicorn.run(app, host="0.0.0.0", port=port, **uvicorn_kwargs)
        case ("oauth", "sse"):
            import uvicorn
            from fastapi import FastAPI, Request

            from delinea_mcp.auth.routes import mount_oauth_routes
            from delinea_mcp.auth.validators import require_scopes
            from delinea_mcp.transports.sse import mount_sse_routes

            app = FastAPI(title="Delinea MCP (OAuth)")
            if _debug:

                @app.middleware("http")
                async def log_requests(request: Request, call_next):
                    body = await request.body()
                    logger.debug(
                        "Request from %s to %s headers=%s body=%s",
                        request.client.host if request.client else "unknown",
                        request.url.path,
                        dict(request.headers),
                        body.decode("utf-8", "replace"),
                    )
                    return await call_next(request)

            mount_oauth_routes(app, cfg)
            mount_sse_routes(
                app,
                mcp,
                require_scopes(
                    ["mcp.read", "mcp.write"],
                    audience=audience,
                    chatgpt_no_scope_check=bool(
                        cfg.get("chatgpt_disable_scope_checks")
                    ),
                ),
            )
            uvicorn.run(app, host="0.0.0.0", port=port, **uvicorn_kwargs)
        case ("passthrough", _):
            raise NotImplementedError(
                "Passthrough auth is slated for a future release."
            )
        case _:
            raise ValueError(
                f"Invalid AUTH_MODE '{auth_mode}' or TRANSPORT_MODE '{transport_mode}'"
            )


__all__ = [
    "mcp",
    "run_server",
    "tools",
    "user_platform_tools",
    "get_secret",
    "get_folder",
    "user_management",
    "role_management",
    "user_role_management",
    "group_management",
    "user_group_management",
    "group_role_management",
    "folder_management",
    "health_check",
    "search",
    "fetch",
    "search_users",
    "search_secrets",
    "search_folders",
    "generate_sql_query",
    "run_report",
    "ai_generate_and_run_report",
    "list_example_reports",
    "get_secret_environment_variable",
    "check_secret_template",
    "check_secret_template_field",
    "get_secret_template_field",
]

if __name__ == "__main__":
    run_server()
