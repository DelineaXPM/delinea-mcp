from __future__ import annotations

import argparse
import logging
import os
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from delinea_api import DelineaSession
from delinea_mcp import secretserver_users, strongdm_tools, tools, user_platform_tools
from delinea_mcp.config import load_config
from delinea_mcp.secretserver_users import (
    search_secretserver_local_users,
    secretserver_local_user_management,
)
from delinea_mcp.session import SessionManager
from delinea_mcp.strongdm_tools import (
    sdm_access_requests,
    sdm_activity_report,
    sdm_audit_access,
    sdm_grant_access,
    sdm_network_status,
    sdm_resource_health,
    sdm_revoke_access,
    sdm_role_management,
    sdm_search,
    sdm_user_management,
)
from delinea_mcp.tools import (
    bulk_user_response,
    check_secret_template,
    check_secret_template_field,
    create_secret_with_generated_password,
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
    set_secret_field_environment_variable,
    update_secret_fields,
    update_secret_generated_password,
    user_group_management,
    user_role_management,
)
from delinea_mcp.user_platform_tools import (
    platform_role_management,
    platform_user_role_management,
    search_users,
    user_management,
)

logger = logging.getLogger(__name__)
_debug = False

try:
    _VERSION = version("delinea-mcp")
except PackageNotFoundError:  # running from a source checkout
    _VERSION = "0.0.0-dev"

mcp = MCPServer("DelineaMCP", version=_VERSION)
CURRENT_CONFIG: dict[str, Any] = {}


def _init_from_config(cfg: dict[str, Any]) -> None:
    """Initialise sessions and tool registration from a config dict."""
    tools.configure(cfg)
    global _debug
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

    platform_hostname = cfg.get("platform_hostname") or os.getenv(
        "PLATFORM_HOSTNAME", ""
    )
    if username and password:
        session = DelineaSession(
            base_url=base_url or "",
            username=username,
            platform_hostname=platform_hostname,
        )
        SessionManager.init(session)
    enabled = set(cfg.get("enabled_tools", []))
    tools.register(mcp, enabled)

    # Register the legacy SS-local user tools under the same enabled_tools
    # allowlist so SS-only deployments keep a fallback without bypassing a
    # restricted ChatGPT/connector allowlist (empty = all tools).
    secretserver_users.register(mcp, enabled)

    # Configure Platform tools. Register under the same enabled_tools
    # allowlist so the canonical user_management / search_users names are
    # available when selected (or when the allowlist is empty). When
    # Platform is not configured the tools return a clear error directing
    # the caller to either configure Platform or use secretserver_local_*.
    if cfg.get("platform_hostname"):
        user_platform_tools.configure(
            hostname=cfg.get("platform_hostname"),
            service_account=cfg.get("platform_service_account"),
            service_password=os.getenv("PLATFORM_SERVICE_PASSWORD"),
            tenant_id=cfg.get("platform_tenant_id"),
        )
        logger.debug("Configured user_platform_tools from config")
    else:
        logger.info(
            "Platform not configured; user_management/search_users will return "
            "a helpful error pointing at secretserver_local_* tools."
        )
    user_platform_tools.register(mcp, enabled)

    # Configure StrongDM tools (optional third backend; SDK installed via
    # the delinea-mcp[strongdm] extra). Tools register under the same
    # allowlist and return a guidance error when the SDK or credentials
    # are absent.
    if cfg.get("strongdm_api_host") or os.getenv("SDM_API_ACCESS_KEY"):
        strongdm_tools.configure(
            api_host=cfg.get("strongdm_api_host"),
            access_key=os.getenv("SDM_API_ACCESS_KEY"),
            secret_key=os.getenv("SDM_API_SECRET_KEY"),
        )
        logger.debug("Configured strongdm_tools from config/env")
    strongdm_tools.register(mcp, enabled)


# Load default config on import using the config module's default resolution.
# Store the loaded config so run_server can reuse it when --config is not passed.
# NOTE: Do not call _init_from_config here - initialization happens in run_server()
# to avoid duplicate tool registration warnings.
CURRENT_CONFIG = load_config()


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
    # --config is optional; when omitted we use the module-level CURRENT_CONFIG
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)

    if args.config:
        # Validate and sanitize the provided config path
        config_path = os.path.abspath(args.config)
        if not os.path.isfile(config_path):
            raise ValueError(f"Invalid config file path: {config_path}")

        cfg = load_config(Path(config_path))
        # Re-initialize runtime from the provided config
        _init_from_config(cfg)
        # Update module-level current config
        globals()["CURRENT_CONFIG"] = cfg
    else:
        # Try to read config from current directory, fallback to cached config
        current_dir_config = Path("config.json")
        if current_dir_config.exists():
            cfg = load_config(current_dir_config)
            # Re-initialize runtime from the current directory config
            _init_from_config(cfg)
            # Update module-level current config
            globals()["CURRENT_CONFIG"] = cfg
        else:
            # Use the already-loaded config from import-time initialization
            cfg = CURRENT_CONFIG

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
    if scheme == "http" and port == 80:
        audience = f"{scheme}://{host}"
    elif scheme == "https" and port == 443:
        audience = f"{scheme}://{host}"
    else:
        audience = f"{scheme}://{host}:{port}"

    match auth_mode, transport_mode:
        case ("none", "stdio"):
            mcp.run(transport="stdio")
        case ("none", "sse"):
            import uvicorn
            from fastapi import FastAPI, Request

            from delinea_mcp.transports.sse import mount_sse_routes
            from delinea_mcp.transports.streamable_http import (
                build_session_manager,
                make_lifespan,
                mount_streamable_http_routes,
            )

            stateless = bool(cfg.get("streamable_http_stateless", True))
            manager = build_session_manager(
                mcp,
                stateless=stateless,
                json_response=bool(cfg.get("streamable_http_json_response", True)),
            )
            app = FastAPI(title="Delinea MCP", lifespan=make_lifespan(manager))
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
            mount_streamable_http_routes(app, manager, stateless=stateless)
            uvicorn.run(app, host="0.0.0.0", port=port, **uvicorn_kwargs)
        case ("oauth", "sse"):
            import uvicorn
            from fastapi import FastAPI, Request

            from delinea_mcp.auth.routes import mount_oauth_routes
            from delinea_mcp.auth.validators import require_scopes
            from delinea_mcp.transports.sse import mount_sse_routes
            from delinea_mcp.transports.streamable_http import (
                build_session_manager,
                make_lifespan,
                mount_streamable_http_routes,
            )

            stateless = bool(cfg.get("streamable_http_stateless", True))
            manager = build_session_manager(
                mcp,
                stateless=stateless,
                json_response=bool(cfg.get("streamable_http_json_response", True)),
            )
            app = FastAPI(title="Delinea MCP (OAuth)", lifespan=make_lifespan(manager))
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
            guard = require_scopes(
                ["mcp.read", "mcp.write"],
                audience=audience,
                chatgpt_no_scope_check=bool(cfg.get("chatgpt_disable_scope_checks")),
            )
            mount_sse_routes(app, mcp, guard)
            mount_streamable_http_routes(app, manager, guard, stateless=stateless)
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
    "secretserver_users",
    "strongdm_tools",
    # StrongDM tools — optional third backend (delinea-mcp[strongdm])
    "sdm_search",
    "sdm_audit_access",
    "sdm_grant_access",
    "sdm_revoke_access",
    "sdm_user_management",
    "sdm_role_management",
    "sdm_resource_health",
    "sdm_access_requests",
    "sdm_activity_report",
    "sdm_network_status",
    "get_secret",
    "get_folder",
    # Canonical (Platform-backed) user tools — v1.0.0+
    "user_management",
    "search_users",
    "platform_role_management",
    "platform_user_role_management",
    # Legacy SS-local user tools — for SS-only deployments
    "secretserver_local_user_management",
    "search_secretserver_local_users",
    "role_management",
    "user_role_management",
    "group_management",
    "user_group_management",
    "group_role_management",
    "folder_management",
    "health_check",
    "search",
    "fetch",
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
    "create_secret_with_generated_password",
    "set_secret_field_environment_variable",
    "update_secret_generated_password",
    "update_secret_fields",
    "bulk_user_response",
]

if __name__ == "__main__":
    run_server()
