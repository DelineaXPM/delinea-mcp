from __future__ import annotations

import argparse
import logging
import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from delinea_mcp import (
    secretserver_users,
    strongdm_tools,
    tool_guard,
    tools,
    user_platform_tools,
)
from delinea_mcp.annotations import TOOL_ANNOTATIONS
from delinea_mcp.api import DelineaSession, platform_host
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
from delinea_mcp.tls import use_system_trust_store
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


# Connection settings may come from config.json or, for env-only launches
# such as the Claude Code plugin (``uvx delinea-mcp``), from the environment.
_ENV_FALLBACKS = {
    "delinea_username": "DELINEA_USERNAME",
    "delinea_base_url": "DELINEA_BASE_URL",
    "platform_hostname": "PLATFORM_HOSTNAME",
    "platform_service_account": "PLATFORM_SERVICE_ACCOUNT",
    "platform_tenant_id": "PLATFORM_TENANT_ID",
}


def _with_env_fallbacks(cfg: dict[str, Any]) -> dict[str, Any]:
    """Fill unset (or ``<placeholder>``) connection settings from env vars."""
    merged = dict(cfg)
    for key, env_name in _ENV_FALLBACKS.items():
        value = merged.get(key)
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("<") and value.endswith(">"):
                value = ""
        if not value and os.getenv(env_name):
            merged[key] = os.environ[env_name]
    return merged


# Tools in the read-only preset besides those annotated read-only. Neither
# changes vault data: the handoff only reads the secret (with an audited
# checkout when a comment is required) and a report is a temporary SELECT
# that is deleted afterwards. The plugin's skills are built around both.
# reveal_secret_field stays behind its own opt-in (secret_reveal_mode).
READ_ONLY_EXTRA_TOOLS = frozenset(
    {"get_secret_environment_variable", "run_report", "reveal_secret_field"}
)


def read_only_tools() -> set[str]:
    """Return the tool names of the ``read-only`` preset."""
    names = {name for name, hints in TOOL_ANNOTATIONS.items() if hints.read_only_hint}
    return names | READ_ONLY_EXTRA_TOOLS


_PRESET_PREFIXES = (("readonly", "read-only"), ("all", "all"), ("custom", "custom"))


def _tool_preset(raw: str) -> str | None:
    """Map a preset value to ``read-only``, ``all`` or ``custom``.

    Accepts the plugin picker's labels ("Read-only", "All tools", "Custom")
    and the short forms, in any case. Blank gives None; anything else gives
    ``read-only``, so a mistyped preset never widens access.
    """
    value = "".join(ch for ch in raw.lower() if ch.isalnum())
    if not value:
        return None
    for prefix, preset in _PRESET_PREFIXES:
        if value.startswith(prefix):
            return preset
    logger.warning("Unknown tool preset %r; using read-only", raw)
    return "read-only"


def _env_tool_list() -> set[str]:
    raw = os.getenv("DELINEA_ENABLED_TOOLS", "")
    return {n.strip() for n in raw.split(",") if n.strip()}


def _select_tools(cfg: dict[str, Any]) -> set[str]:
    """Return the tool allowlist; an empty set means every tool.

    Precedence: ``enabled_tools`` in config.json, then the tool preset
    (``tool_preset`` in config.json, or ``DELINEA_TOOL_PRESET``, the plugin's
    "Tool access" setting):

    - ``read-only``: :func:`read_only_tools`.
    - ``all``: every tool.
    - ``custom``: the comma-separated ``DELINEA_ENABLED_TOOLS`` list (the
      plugin's "Custom tool list"); an empty list falls back to read-only.

    With no preset, ``DELINEA_ENABLED_TOOLS`` alone narrows the set, and blank
    or ``all`` means every tool.
    """
    enabled = {str(n) for n in cfg.get("enabled_tools", []) if str(n).strip()}
    if enabled:
        return enabled
    names = _env_tool_list()
    preset = _tool_preset(
        str(cfg.get("tool_preset") or os.getenv("DELINEA_TOOL_PRESET", ""))
    )
    if preset in ("read-only", "all") and names:
        logger.warning(
            "Tool preset is %s; ignoring the custom tool list (choose the "
            "Custom preset to use it)",
            preset,
        )
    if preset == "read-only":
        return read_only_tools()
    if preset == "custom" and not names:
        logger.warning("Custom tool preset with an empty tool list; using read-only")
        return read_only_tools()
    if "all" in {n.lower() for n in names} or preset == "all":
        return set()
    return names


def _init_from_config(cfg: dict[str, Any]) -> None:
    """Initialise sessions and tool registration from a config dict."""
    cfg = _with_env_fallbacks(cfg)
    # Accept a pasted Platform URL; every Platform client wants the bare host.
    if cfg.get("platform_hostname"):
        cfg["platform_hostname"] = platform_host(cfg["platform_hostname"])
    tools.configure(cfg)
    tool_guard.configure(cfg.get("max_result_bytes"))
    global _debug
    _debug = bool(cfg.get("debug", False))
    if _debug and not logging.getLogger().handlers:
        logging.basicConfig(level=logging.DEBUG)
    elif _debug:
        logging.getLogger().setLevel(logging.DEBUG)
    username = cfg.get("delinea_username")
    password = os.getenv("DELINEA_PASSWORD")
    base_url = cfg.get("delinea_base_url")
    platform_hostname = cfg.get("platform_hostname") or ""
    if username and password:
        if _plugin_mode() and not (base_url or platform_hostname):
            # The standalone server's https://localhost/SecretServer default
            # would send the keychain password to whatever listens there.
            raise ValueError(
                "Set the Delinea Platform URL in the plugin settings (or, for "
                "a standalone Secret Server, the Secret Server URL)."
            )
        session = DelineaSession(
            base_url=base_url or "",
            username=username,
            platform_hostname=platform_hostname,
        )
        SessionManager.init(session)
    enabled = _select_tools(cfg)
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
        # With a Platform hostname, the main account is already a Platform
        # service account (the vault session signs in through the Platform),
        # so the Platform tools reuse it unless a separate one is given.
        service_account = cfg.get("platform_service_account")
        service_password = os.getenv("PLATFORM_SERVICE_PASSWORD")
        if not service_account and not service_password:
            service_account, service_password = username, password
        user_platform_tools.configure(
            hostname=cfg.get("platform_hostname"),
            service_account=service_account,
            service_password=service_password,
            tenant_id=cfg.get("platform_tenant_id"),
        )
        logger.debug("Configured user_platform_tools from config")
    else:
        logger.info(
            "Platform not configured; user_management/search_users will return "
            "a helpful error pointing at secretserver_local_* tools."
        )
    user_platform_tools.register(mcp, enabled)

    # StrongDM (a Delinea company) support is experimental and not part of
    # the 2.0 release surface: its tools register only when explicitly
    # enabled. The SDK comes from the delinea-mcp[strongdm] extra; tools
    # return a guidance error when the SDK or credentials are absent.
    if not cfg.get("strongdm_enabled"):
        logger.info("StrongDM tools not registered (set strongdm_enabled=true)")
        return
    if cfg.get("strongdm_api_host") or os.getenv("SDM_API_ACCESS_KEY"):
        strongdm_tools.configure(
            api_host=cfg.get("strongdm_api_host"),
            access_key=os.getenv("SDM_API_ACCESS_KEY"),
            secret_key=os.getenv("SDM_API_SECRET_KEY"),
        )
        logger.debug("Configured strongdm_tools from config/env")
    strongdm_tools.register(mcp, enabled)


def _plugin_mode() -> bool:
    """Return True when launched by the Claude Code plugin manifest.

    The manifest sets ``DELINEA_MCP_PLUGIN=1``. Claude Code starts the server
    with the user's project as the working directory, so in this mode no
    config file is read implicitly: a ``config.json`` committed to a cloned
    repository could otherwise set ``delinea_base_url`` and receive the
    password the plugin passes from the OS keychain. Settings then come only
    from the environment the manifest provides.
    """
    return os.getenv("DELINEA_MCP_PLUGIN") == "1"


# Load default config on import using the config module's default resolution.
# Store the loaded config so run_server can reuse it when --config is not passed.
# NOTE: Do not call _init_from_config here - initialization happens in run_server()
# to avoid duplicate tool registration warnings.
CURRENT_CONFIG = {} if _plugin_mode() else load_config()


def run_report(sql_query: str, report_name: str | None = None) -> dict:
    logger.debug("run_report(%s)", sql_query)
    return tools.run_report(sql_query, report_name)


def list_example_reports() -> str:
    logger.debug("list_example_reports")
    return tools.list_example_reports()


def run_server(argv: list[str] | None = None) -> None:
    # Before any session signs in: verify TLS against the OS store so
    # TLS-inspecting networks and internal CAs work (see delinea_mcp.tls).
    use_system_trust_store()
    plugin_mode = _plugin_mode()
    # Plugin mode rejects abbreviated options (e.g. ``--conf``) so only the
    # exact flags the manifest passes are accepted.
    parser = argparse.ArgumentParser(allow_abbrev=not plugin_mode)
    # --config is optional; when omitted we use the module-level CURRENT_CONFIG.
    # In plugin mode $DELINEA_MCP_CONFIG (which may be inherited from the
    # user's shell for a separate server) and ./config.json are ignored; only
    # an explicit --config from the manifest is honoured.
    parser.add_argument(
        "--config",
        default=None if plugin_mode else (os.getenv("DELINEA_MCP_CONFIG") or None),
        help="Path to config.json (default: $DELINEA_MCP_CONFIG, then ./config.json)",
    )
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
    elif plugin_mode:
        if Path("config.json").exists():
            logger.warning(
                "Plugin mode: ignoring config.json in %s; settings come from the "
                "plugin configuration only.",
                os.getcwd(),
            )
        cfg = {}
        _init_from_config(cfg)
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
            # Use the already-loaded config from import-time loading; settings
            # missing there fall back to environment variables.
            cfg = CURRENT_CONFIG
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
    host = cfg.get("external_hostname", "0.0.0.0")  # nosec B104 - audience only
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

            from delinea_mcp.transports.origin import (
                allowed_origins_for,
                install_origin_guard,
            )
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

            origin_guard = install_origin_guard(app, allowed_origins_for(cfg))
            mount_sse_routes(app, mcp, origin_guard=origin_guard)
            mount_streamable_http_routes(
                app, manager, stateless=stateless, origin_guard=origin_guard
            )
            # HTTP transports serve remote clients (containers, connectors).
            uvicorn.run(app, host="0.0.0.0", port=port, **uvicorn_kwargs)  # nosec B104
        case ("oauth", "sse"):
            import uvicorn
            from fastapi import FastAPI, Request

            from delinea_mcp.auth.routes import mount_oauth_routes
            from delinea_mcp.auth.validators import require_scopes
            from delinea_mcp.transports.origin import (
                allowed_origins_for,
                install_origin_guard,
            )
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
            origin_guard = install_origin_guard(app, allowed_origins_for(cfg))
            mount_sse_routes(app, mcp, guard, origin_guard=origin_guard)
            mount_streamable_http_routes(
                app, manager, guard, stateless=stateless, origin_guard=origin_guard
            )
            # HTTP transports serve remote clients (containers, connectors).
            uvicorn.run(app, host="0.0.0.0", port=port, **uvicorn_kwargs)  # nosec B104
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
    "main",
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
    "run_report",
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


def main() -> None:
    """Console-script entry point (``delinea-mcp`` / ``uvx delinea-mcp``)."""
    run_server()


if __name__ == "__main__":
    main()
