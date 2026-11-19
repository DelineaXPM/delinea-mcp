"""Reporting helper functions and MCP tools."""

from __future__ import annotations

import atexit
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Annotated, Any, Iterable

import anyio.to_thread
from mcp.server.elicitation import AcceptedElicitation, ElicitationResult
from mcp.server.mcpserver import Context, Elicit, Resolve
from mcp.types import ClientCapabilities, ElicitationCapability
from pydantic import BaseModel, ConfigDict, Field

from delinea_mcp.annotations import tool_metadata
from delinea_mcp.api import redact

from . import constants
from .session import SessionManager
from .tool_guard import guard_tool

logger = logging.getLogger(__name__)
if os.getenv("DELINEA_DEBUG") and not logging.getLogger().handlers:
    logging.basicConfig(level=logging.DEBUG)  # pragma: no cover - config

_CFG: dict[str, Any] = {}
# Allowed object types for the generic search and fetch helpers. By default only
# secrets are enabled. ``configure`` may override these values via the
# ``search_objects`` and ``fetch_objects`` keys.  All other known types are
# supported when enabled: users, folders, groups and roles.
_SEARCH_ALLOWED: set[str] = {"secret"}
_FETCH_ALLOWED: set[str] = {"secret"}


def configure(cfg: dict[str, Any]) -> None:
    """Store configuration values for later use and update allowed types."""
    _CFG.update(cfg)
    global _SEARCH_ALLOWED, _FETCH_ALLOWED
    if "search_objects" in cfg:
        _SEARCH_ALLOWED = {str(o).lower() for o in cfg["search_objects"]}
    if "fetch_objects" in cfg:
        _FETCH_ALLOWED = {str(o).lower() for o in cfg["fetch_objects"]}


def _cfg_or_env(key: str) -> str | None:
    """Return a config value with placeholder-aware fallback to environment."""

    cfg_val = _CFG.get(key.lower())
    if isinstance(cfg_val, str):
        stripped = cfg_val.strip()
        if not stripped or (stripped.startswith("<") and stripped.endswith(">")):
            cfg_val = None
    if cfg_val is not None:
        return cfg_val
    return os.getenv(key)


def _api_base_url() -> str:
    """Return the full API base URL including `/api` if configured."""
    base = _cfg_or_env("DELINEA_BASE_URL")
    try:
        session = SessionManager.get()
        if getattr(session, "base_url", None):
            base = session.base_url
    except RuntimeError:
        pass  # Session not initialized yet, use config
    if not base:
        return ""
    return base.rstrip("/") + "/api"


def _parse_json_data(data: dict | str | None) -> dict | None:
    """Return a dict from ``data`` when given a JSON string."""
    if isinstance(data, str):
        try:
            return json.loads(data)
        except Exception:
            logger.exception("Failed to parse JSON string")
            raise ValueError("Invalid JSON data")
    return data


DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500
DEFAULT_REPORT_ROWS = 200
MAX_REPORT_ROWS = 5000


def _clamp(value: int | None, default: int, maximum: int) -> int:
    try:
        value = int(value) if value is not None else default
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


def _paged(params: dict | None, take: int | None = None, skip: int = 0) -> dict:
    """Return list-endpoint query params with a bounded page size.

    Explicit ``take``/``skip`` keys already in *params* win, but ``take`` is
    still capped so one call cannot return an unbounded result set.
    """
    merged = dict(params or {})
    merged["take"] = _clamp(merged.get("take", take), DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
    merged.setdefault("skip", max(0, int(skip or 0)))
    return merged


def create_report(report_name: str, sql_query: str) -> int:
    """Create a temporary report and return its numeric identifier.

    Parameters
    ----------
    report_name:
        Name assigned to the temporary report.
    sql_query:
        The SQL query to execute.

    Returns
    -------
    int
        Identifier of the newly created report.
    """
    logger.debug("create_report(%s)", report_name)
    session = SessionManager.get()
    try:
        response = session.request(
            "POST",
            "/v1/reports",
            json={
                "name": report_name,
                "description": f"Auto-generated report for {report_name}",
                "categoryId": 1,
                "reportSql": sql_query,
            },
        )
        return response.json()["id"]
    except Exception:  # pragma: no cover - network failures
        logger.exception("Failed to create report '%s'", report_name)
        raise


def execute_report(report_id: int) -> dict:
    """Execute the specified report and return the raw JSON result.

    Parameters
    ----------
    report_id:
        Identifier of the report to run.

    Returns
    -------
    dict
        Raw execution result from the API.
    """
    logger.debug("execute_report(%s)", report_id)
    session = SessionManager.get()
    try:
        response = session.request(
            "POST",
            "/v1/reports/execute",
            json={"id": report_id, "useDefaultParameters": True},
        )
        return response.json()
    except Exception:  # pragma: no cover - network failures
        logger.exception("Failed to execute report %s", report_id)
        raise


def run_report(
    sql_query: str, report_name: str | None = None, max_rows: int = DEFAULT_REPORT_ROWS
) -> dict:
    """Run a read-only SQL report on Secret Server and return its rows.

    Call ``list_example_reports`` first: it is the reference for this tool
    and lists the Secret Server database tables, columns, special fields and
    tested example queries to build *sql_query* from. The query runs through
    the Secret Server REST API reports endpoints (``POST /api/v1/reports``,
    ``POST /api/v1/reports/execute``, then ``DELETE /api/v1/reports/{id}``;
    see https://docs.delinea.com/online-help/secret-server/api-scripting/rest-api/index.htm),
    as a temporary report that is deleted after it runs. Secret Server only
    executes ``SELECT`` statements and applies the configured account's
    report permissions.

    Parameters
    ----------
    sql_query:
        The SQL query to run. Secret Server only accepts a single read-only
        SELECT statement as custom report SQL (no IF, WHILE, BEGIN ... END,
        TRY/CATCH, PRINT, temporary tables or database-qualified names); call
        ``list_example_reports`` for the rules, table list and sample queries.
    report_name:
        Optional name for the temporary report.
    max_rows:
        Maximum rows to return (default 200, capped at 5000). Add
        aggregation or a ``WHERE`` clause rather than raising this.

    Returns
    -------
    dict
        ``columns``, ``rows``, ``total_rows`` and ``truncated``, or an
        ``error`` key on failure.
    """
    logger.debug("run_report(%s)", sql_query)
    session = SessionManager.get()
    name = report_name or "MCP Generated Report"
    limit = _clamp(max_rows, DEFAULT_REPORT_ROWS, MAX_REPORT_ROWS)
    try:
        report_id = create_report(name, sql_query)
        result = execute_report(report_id)
    except Exception as exc:
        logger.exception("Failed to run report '%s'", name)
        return {"error": f"Report '{name}' failed: {exc}"}

    try:
        session.request("DELETE", f"/v1/reports/{report_id}")
    except Exception:
        logger.exception("Failed to delete report %s", report_id)

    rows = result.get("rows", []) or []
    out = {
        "columns": result.get("columns", []),
        "rows": rows[:limit],
        "total_rows": len(rows),
        "truncated": len(rows) > limit,
    }
    return out


def check_secret_template(template_id: int) -> dict:  # pragma: no cover
    """Returns the template details for the given ID."""
    logger.debug("check_secret_template(%s)", template_id)
    session = SessionManager.get()
    try:
        return session.request("GET", f"/v1/secret-templates/{template_id}").json()
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to retrieve secret template %s", template_id)
        return {"error": f"Failed to retrieve secret template {template_id}: {exc}"}


def _check_secret_approval(
    session: Any, secret_id: int, comment: str | None
) -> dict | None:
    """Return an error dict if *secret_id* requires approval or a comment."""
    try:
        summary = session.request("GET", f"/v1/secrets/{secret_id}/summary").json()
    except Exception:
        return None  # can't check — let the actual call surface the error
    # requiresApproval may be None even when approval is enforced;
    # isRestricted is a more reliable indicator of access-controlled secrets.
    needs_approval = summary.get("requiresApproval") or summary.get("isRestricted")
    if needs_approval and not comment:
        return {
            "error": (
                f"Secret {secret_id} requires approval. "
                "Check approval status with get_secret(id, summary=True), "
                "then if needed request access via get_pending_access_requests() "
                "and handle_access_request(). Provide a comment explaining why "
                "this secret is needed and reference any related ticket or "
                "change request."
            )
        }
    if summary.get("requiresComment") and not comment:
        return {
            "error": (
                f"Secret {secret_id} requires a comment. "
                "Provide the comment parameter explaining why this secret is "
                "being accessed and reference any related ticket or change request."
            )
        }
    return None


# --------------------------------------------------------------------------- #
# Credential handoff                                                          #
# --------------------------------------------------------------------------- #
#
# The environment-variable tools get a credential into (or out of) the
# user's shell without the value passing through the model.
#
# * Local server (stdio, the default): the server runs on the user's
#   machine, so it does the API work itself. ``get_secret_environment_variable``
#   fetches the secret and writes a tiny env file of plain shell assignments;
#   ``set_secret_field_environment_variable`` reads a ``file:`` source
#   directly, or hands over a one-line command that runs this package's own
#   Python (``delinea_mcp.field_push``) to read the value and upload it. No
#   curl, jq or other tools are needed on the machine. Files are 0600 in a
#   0700 directory, delete themselves when used, and expire after 15 minutes;
#   only their paths are returned.
# * Remote server (HTTP transports): the server can't write to the user's
#   machine, so it returns a script that calls the API with its current
#   short-lived access token. Those scripts state the tools they require.

_SCRIPT_TTL_SECONDS = 15 * 60
_SCRIPT_DIR: Path | None = None
_SCRIPT_EXT = {"bash": ".sh", "powershell": ".ps1", "cmd": ".cmd"}
_SHELLS = tuple(_SCRIPT_EXT)


def _script_delivery() -> str:
    """Return ``"file"`` or ``"inline"`` for generated scripts."""
    mode = str(_CFG.get("script_delivery", "auto")).lower()
    if mode in {"file", "inline"}:
        return mode
    transport = str(_CFG.get("transport_mode", "stdio")).lower()
    return "file" if transport == "stdio" else "inline"


def _shell(environment: str) -> str:
    env = environment.lower()
    if env not in _SCRIPT_EXT:
        raise ValueError(
            f"Unsupported environment {environment!r}; use 'bash', "
            "'powershell' or 'cmd'"
        )
    return env


def _script_dir() -> Path:
    """Private (0700) per-process directory for handoff files."""
    global _SCRIPT_DIR
    if _SCRIPT_DIR is None or not _SCRIPT_DIR.is_dir():
        _SCRIPT_DIR = Path(tempfile.mkdtemp(prefix="delinea-mcp-"))
        atexit.register(shutil.rmtree, _SCRIPT_DIR, True)
    return _SCRIPT_DIR


def _sweep_expired_scripts(directory: Path) -> None:
    cutoff = time.time() - _SCRIPT_TTL_SECONDS
    for old in directory.iterdir():
        try:
            if old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:  # pragma: no cover - raced with self-delete
            pass


def _write_private(content: str, suffix: str) -> Path:
    """Write a 0600 handoff file that expires after the TTL."""
    directory = _script_dir()
    _sweep_expired_scripts(directory)
    fd, name = tempfile.mkstemp(dir=directory, prefix="handoff-", suffix=suffix)
    path = Path(name)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.chmod(path, 0o600)
    expiry = threading.Timer(
        _SCRIPT_TTL_SECONDS, path.unlink, kwargs={"missing_ok": True}
    )
    expiry.daemon = True
    expiry.start()
    return path


def _self_deleting(body: str, environment: str, path: Path) -> str:
    """Wrap *body* so the script removes itself when it runs."""
    if environment == "bash":
        # Sourced scripts stay readable after unlink (open file descriptor).
        return f"rm -f '{path}'\n{body}\n"
    if environment == "powershell":
        return f"Remove-Item -LiteralPath '{path}' -Force\n{body}\n"
    # cmd reads batch files incrementally: delete as the very last action.
    return f'@echo off\n{body}\n(goto) 2>nul & del "%~f0"\n'


def _quote(value: str, environment: str) -> str:
    """Quote *value* as a literal for *environment* (bash/powershell)."""
    if environment == "bash":
        return "'" + value.replace("'", "'\\''") + "'"
    return "'" + value.replace("'", "''") + "'"


def _assignments(values: dict[str, str], environment: str) -> str:
    """Shell statements exporting *values* verbatim."""
    if environment == "bash":
        return "\n".join(f"export {k}={_quote(v, 'bash')}" for k, v in values.items())
    if environment == "powershell":
        return "\n".join(
            f"$env:{k} = {_quote(v, 'powershell')}" for k, v in values.items()
        )
    lines = []
    for key, value in values.items():
        # Inside `set "K=V"` only quotes, line breaks and % need care; a
        # quote would end the protected region, so refuse rather than guess.
        if any(ch in value for ch in '"\r\n'):
            raise ValueError(
                f"The value for {key} contains a quote or line break, which "
                "cmd can't hold safely; use environment='powershell' instead"
            )
        lines.append(f'set "{key}={value.replace("%", "%%")}"')
    return "\n".join(lines)


def _run_hint(environment: str, path: Path) -> str:
    if environment == "bash":
        return f"source '{path}' && <command that uses the variables>"
    if environment == "powershell":
        return f". '{path}'; <command that uses the variables>"
    return f'call "{path}" && <command that uses the variables>'


def _deliver_env_file(values: dict[str, str], environment: str, purpose: str) -> dict:
    """Write *values* as a self-deleting env file; return its path only."""
    fd_path = _write_private("", _SCRIPT_EXT[environment])
    fd_path.write_text(
        _self_deleting(_assignments(values, environment), environment, fd_path),
        encoding="utf-8",
    )
    return {
        "script_path": str(fd_path),
        "shell": environment,
        "run": _run_hint(environment, fd_path),
        "purpose": purpose,
        "note": (
            "The file sets the variables and deletes itself when run (or "
            "after 15 minutes). Run it in the same shell invocation as the "
            "command that needs it. Do not print, cat or copy its contents, "
            "or echo the variables."
        ),
    }


def _python_command(environment: str, job_path: Path) -> str:
    """Command line that runs ``delinea_mcp.field_push`` with this Python.

    ``-I`` (isolated mode) keeps the current directory, ``PYTHONPATH`` and
    user site-packages off ``sys.path``: the command runs inside the user's
    project, and a package there named like ``delinea_mcp`` or one of its
    dependencies must not get the job file and its access token.
    """
    exe = sys.executable
    module = "-I -m delinea_mcp.field_push"
    if environment == "bash":
        return f"{_quote(exe, 'bash')} {module} {_quote(str(job_path), 'bash')}"
    if environment == "powershell":
        return (
            f"& {_quote(exe, 'powershell')} {module} "
            f"{_quote(str(job_path), 'powershell')}"
        )
    return f'"{exe}" {module} "{job_path}"'


def _find_item(secret: dict, slug: str) -> dict | None:
    for item in secret.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        names = {
            str(item.get("slug", "")).lower(),
            str(item.get("fieldName", "")).lower(),
        }
        if slug in names:
            return item
    return None


def _field_text(response: Any) -> str:
    """The value from ``GET /v1/secrets/{id}/fields/{slug}``."""
    try:
        value = response.json()
    except ValueError:
        return response.text
    return "" if value is None else str(value)


class _NoCredentialFields(Exception):
    """The secret has neither a username nor a password field."""


def _handoff_values(
    session: Any, secret_id: int, names: dict[str, str], params: dict | None
) -> dict[str, str]:
    """Read the username and password for an environment-variable handoff.

    A secret GET doesn't have to include password values (the API documents
    that it leaves them out); when it doesn't, the password comes from the
    field endpoint, the same call ``reveal_secret_field`` makes. Using the
    GET's value when it's there keeps a secret that needs check-out to one
    check-out and check-in.
    """
    secret = session.request("GET", f"/v2/secrets/{secret_id}", params=params).json()
    values: dict[str, str] = {}
    for slug, var in names.items():
        item = _find_item(secret, slug)
        if item is None:
            continue
        value = item.get("itemValue")
        if value in (None, "") and (item.get("isPassword") or slug == "password"):
            field = item.get("slug") or slug
            response = session.request(
                "GET", f"/v1/secrets/{secret_id}/fields/{field}", params=params
            )
            values[var] = _field_text(response)
        else:
            values[var] = "" if value is None else str(value)
    if not values:
        slugs = [i.get("slug") for i in secret.get("items", []) if isinstance(i, dict)]
        raise _NoCredentialFields(
            f"Secret {secret_id} has no username or password field; its "
            f"fields are {slugs}. Use set_secret_field_environment_variable "
            "or get_secret to work with other fields."
        )
    return values


def _checkout_params(comment: str | None) -> dict | None:
    if not comment:
        return None
    return {"autoCheckout": "true", "autoCheckIn": "true", "autoComment": comment}


def get_secret_environment_variable(
    secret_id: int, environment: str, comment: str | None = None
) -> str | dict:
    """Load a secret's username and password into shell environment variables.

    This is the preferred way to *use* a credential: the value never appears
    in the conversation. When the server runs locally (stdio), it reads the
    secret itself and writes a private, self-deleting file of shell
    assignments, returning only the file's path; nothing else needs to be
    installed. Over HTTP transports it returns a script instead, which calls
    the Secret Server REST API with the server's short-lived access token
    (bash needs curl and jq; powershell needs nothing extra).

    Before retrieving a secret, check whether it requires approval:

    1. Call ``get_secret(id, summary=True)`` and inspect
       ``requiresApproval`` and ``requiresComment``.
    2. If approval is required, call ``get_pending_access_requests()``
       to check for an existing grant, or request access and wait for
       approval via ``handle_access_request()``.
    3. Always provide the *comment* parameter explaining **why** this
       secret is being accessed.  If the action is tied to a ticket,
       incident, or change request, that reference **must** be named
       in the comment.

    Parameters
    ----------
    secret_id:
        Identifier of the secret to retrieve.
    environment:
        Target shell environment. Supported values are ``"bash"``,
        ``"powershell"`` and ``"cmd"``.
    comment:
        Required when the secret has ``requiresComment`` or
        ``requiresApproval`` set.  Must explain **why** this secret is
        being accessed and, if the action is tied to a formal request
        (e.g. a Jira ticket, incident, or change request), that
        reference must be included.

    Returns
    -------
    dict
        ``script_path`` plus a ``run`` hint (local mode). Running it exports
        ``SECRET_USERNAME_<id>`` and ``SECRET_PASSWORD_<id>``.
    str
        The script text (HTTP transports).
    dict
        Error information if the secret requires approval or a comment
        that was not provided.
    """
    env = _shell(environment)
    session = SessionManager.get()

    # Pre-check approval requirements
    check = _check_secret_approval(session, secret_id, comment)
    if check is not None:
        return check

    names = {
        "username": f"SECRET_USERNAME_{secret_id}",
        "password": f"SECRET_PASSWORD_{secret_id}",
    }
    purpose = f"Exports {names['username']} and {names['password']}"

    if _script_delivery() == "file":
        try:
            values = _handoff_values(
                session, secret_id, names, _checkout_params(comment)
            )
        except _NoCredentialFields as exc:
            return {"error": str(exc)}
        except Exception as exc:  # pragma: no cover - network failures
            logger.exception("Failed to read secret %s", secret_id)
            return {"error": f"Failed to read secret {secret_id}: {exc}"}
        return _deliver_env_file(values, env, purpose)

    if env == "cmd":
        return {
            "error": (
                "cmd scripts aren't available when the server runs remotely; "
                "use environment='powershell' or 'bash'."
            )
        }
    query = ""
    if comment:
        from urllib.parse import quote

        query = f"?autoCheckout=true&autoCheckIn=true&autoComment={quote(comment)}"
    url = f"{session.base_url}/api/v2/secrets/{secret_id}{query}"
    # Secret GETs may leave password values out; the field endpoint has them.
    password_url = (
        f"{session.base_url}/api/v1/secrets/{secret_id}/fields/password{query}"
    )
    access_token = session.token
    if env == "bash":
        auth = f'-H "Authorization: Bearer {access_token}"'
        fail = (
            f"|| {{ echo 'Failed to read secret {secret_id}' >&2; "
            "return 1 2>/dev/null || exit 1; }\n"
        )
        pick = "'.items[] | select(.slug == \"%s\") | .itemValue // empty'"
        return (
            "# Requires: curl, jq\n"
            f"_dmcp_resp=\"$(curl -fsS {auth} '{url}')\" {fail}"
            f'_dmcp_pw="$(printf \'%s\' "$_dmcp_resp" | jq -r {pick % "password"})"\n'
            'if [ -z "$_dmcp_pw" ]; then\n'
            f"  _dmcp_pw=\"$(curl -fsS {auth} '{password_url}' "
            f"| jq -sRr 'fromjson? // .')\" {fail}"
            "fi\n"
            f'export {names["username"]}="$(printf \'%s\' "$_dmcp_resp" '
            f'| jq -r {pick % "username"})"\n'
            f'export {names["password"]}="$_dmcp_pw"\n'
            "unset _dmcp_resp _dmcp_pw"
        )
    return (
        f'$headers = @{{"Authorization" = "Bearer {access_token}"}}\n'
        f'$response = Invoke-RestMethod -Uri "{url}" -Headers $headers\n'
        '$usernameItem = $response.items | Where-Object { $_.slug -eq "username" }\n'
        '$passwordItem = $response.items | Where-Object { $_.slug -eq "password" }\n'
        "$password = $passwordItem.itemValue\n"
        "if (-not $password) {\n"
        f'  $password = Invoke-RestMethod -Uri "{password_url}" -Headers $headers\n'
        "}\n"
        f"$env:{names['password']} = $password\n"
        f"$env:{names['username']} = $usernameItem.itemValue\n"
        "Remove-Variable headers, response, usernameItem, passwordItem, password"
    )


def create_secret_with_generated_password(
    name: str,
    secret_template_id: int,
    password_field_id: int,
    items: list[dict] | str,
    folder_id: int | None = None,
    site_id: int | None = None,
    comment: str | None = None,
) -> dict:  # pragma: no cover
    """Create a new secret with a server-generated password.

    The password is generated by the Delinea API using the template field's
    password requirements and is **never returned** to the caller.  The model
    receives only the secret's ID and safe metadata.

    Before calling, use ``check_secret_template(template_id)`` to discover:

    * Which fields exist and their ``secretTemplateFieldId`` values.
    * Which fields have ``isPassword=True`` (use their ID as
      *password_field_id*).
    * Which fields have ``isRequired=True`` (must be provided in *items*).

    Parameters
    ----------
    name:
        Display name for the new secret.
    secret_template_id:
        Template ID that defines the secret structure.
    password_field_id:
        ``secretTemplateFieldId`` of the password field on the template.
        Used to call ``POST /v1/secret-templates/generate-password/{id}``.
    items:
        Non-password field values as a list of ``RestSecretItem`` dicts (or
        a JSON string).  Each dict should contain ``fieldId`` and
        ``itemValue``.  An entry for the password field may be omitted or
        have an empty ``itemValue`` — the generated password will be
        injected automatically.
    folder_id:
        Optional folder to store the secret in.
    site_id:
        Optional distributed engine site identifier.
    comment:
        Audit comment recorded against the new secret.  Must explain
        **why** this secret is being created and, if the action is tied
        to a formal request (e.g. a Jira ticket, incident, or change
        request), that reference must be included.

    Returns
    -------
    dict
        ``{"result": {...}, "verification": {...}}`` with safe metadata
        only.  The password value is never included.
    """
    logger.debug(
        "create_secret_with_generated_password(name=%s, template=%s, field=%s)",
        name,
        secret_template_id,
        password_field_id,
    )
    session = SessionManager.get()

    parsed_items: list[dict] = (
        json.loads(items) if isinstance(items, str) else list(items)
    )

    try:
        # 1. Generate password server-side
        gen_resp = session.request(
            "POST",
            f"/v1/secret-templates/generate-password/{password_field_id}",
        )
        generated_password = gen_resp.json()
        if isinstance(generated_password, dict):
            generated_password = generated_password.get(
                "password", generated_password.get("value", "")
            )
        if not generated_password:
            return {"error": "Password generation returned empty result"}

        # 2. Inject generated password into items
        password_injected = False
        for item in parsed_items:
            if item.get("fieldId") == password_field_id:
                item["itemValue"] = generated_password
                password_injected = True
                break
        if not password_injected:
            parsed_items.append(
                {"fieldId": password_field_id, "itemValue": generated_password}
            )

        # 3. Create the secret
        create_payload: dict[str, Any] = {
            "name": name,
            "secretTemplateId": secret_template_id,
            "items": parsed_items,
        }
        if folder_id is not None:
            create_payload["folderId"] = folder_id
        if site_id is not None:
            create_payload["siteId"] = site_id

        create_result = session.request(
            "POST", "/v1/secrets", json=create_payload
        ).json()

        # 4. Sanitize — only safe metadata, never items/field values
        secret_id = create_result.get("id")
        safe_result = {
            "id": secret_id,
            "name": create_result.get("name"),
            "folderId": create_result.get("folderId"),
            "secretTemplateId": create_result.get("secretTemplateId"),
            "password_generated": True,
            "password_field_id": password_field_id,
        }

        # 5. Verify via summary (never returns field values)
        verify: dict = {}
        if secret_id is not None:
            try:
                verify = session.request(
                    "GET", f"/v1/secrets/{secret_id}/summary"
                ).json()
            except Exception as exc:  # pragma: no cover - network failures
                logger.exception("Secret verification failed after create")
                verify = {"error": str(exc)}

        return {"result": safe_result, "verification": verify}

    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to create secret with generated password")
        return {"error": f"Failed to create secret: {exc}"}


def set_secret_field_environment_variable(
    secret_id: int,
    field_slug: str,
    environment: str,
    source: str = "stdin",
    comment: str | None = None,
) -> str | dict:
    """Store a value from the user's machine in a secret field, unseen by the model.

    Use this for values that **cannot** be generated by Delinea (e.g. AWS API
    keys, external tokens). The value is written with
    ``PUT /v1/secrets/{id}/fields/{slug}`` and never enters the conversation.

    When the server runs locally (stdio):

    * ``file:`` sources are read and uploaded by the server directly; the
      file's contents are stored as-is (a trailing newline is dropped).
    * ``env:`` and ``stdin`` sources return a one-line ``command`` that runs
      this package's own Python to read the value (hidden prompt for
      ``stdin``) and upload it. Nothing else needs to be installed. The
      command's job file holds a short-lived access token, is private, and
      deletes itself when used or after 15 minutes. With ``stdin`` the user
      must run the command in their own terminal.

    Over HTTP transports a script is returned instead (bash needs curl and
    jq, cmd needs curl).

    For new secrets, first create the secret (with a placeholder or via
    ``create_secret_with_generated_password``), then use this tool to populate
    external fields.

    Before modifying a secret, check whether it requires approval:

    1. Call ``get_secret(id, summary=True)`` and inspect
       ``requiresApproval`` and ``requiresComment``.
    2. If approval is required, call ``get_pending_access_requests()``
       to check for an existing grant, or request access and wait for
       approval via ``handle_access_request()``.
    3. Always provide the *comment* parameter explaining **why** this
       secret is being modified.  If the action is tied to a ticket,
       incident, or change request, that reference **must** be named
       in the comment.

    Parameters
    ----------
    secret_id:
        ID of the existing secret to update.
    field_slug:
        Field slug name (e.g. ``"password"``, ``"username"``, ``"api-key"``).
        Use ``check_secret_template`` to discover slugs.
    environment:
        Target shell — ``"bash"``, ``"powershell"`` or ``"cmd"``.
    source:
        Where to read the value.  Options:

        * ``"env:VAR_NAME"`` — read from environment variable *VAR_NAME*
        * ``"file:/path/to/file"`` — read from a file
        * ``"stdin"`` — prompt the user to type/paste (default)
    comment:
        Required when the secret has ``requiresComment`` or
        ``requiresApproval`` set.  Must explain **why** this secret is
        being modified and, if the action is tied to a formal request
        (e.g. a Jira ticket, incident, or change request), that
        reference must be included.

    Returns
    -------
    dict
        ``result`` (``file:`` source) or ``command`` (``env:``/``stdin``) in
        local mode.
    str
        The script text (HTTP transports).
    dict
        Error information if the secret requires approval or a comment
        that was not provided.
    """
    logger.debug(
        "set_secret_field_environment_variable(secret_id=%s, slug=%s, env=%s, src=%s)",
        secret_id,
        field_slug,
        environment,
        source,
    )
    session = SessionManager.get()

    # Pre-check approval requirements
    check = _check_secret_approval(session, secret_id, comment)
    if check is not None:
        return check

    env = _shell(environment)
    field_path = f"/v1/secrets/{secret_id}/fields/{field_slug}"
    if _script_delivery() == "file":
        params = _checkout_params(comment)
        if source.startswith("file:"):
            file_path = Path(source[5:]).expanduser()
            try:
                value = file_path.read_text(encoding="utf-8").rstrip("\r\n")
            except (OSError, UnicodeDecodeError) as exc:
                return {"error": f"Can't read {file_path}: {exc}"}
            kwargs: dict[str, Any] = {"json": {"value": value}}
            if params:
                kwargs["params"] = params
            try:
                session.request("PUT", field_path, sensitive=[value], **kwargs)
            except Exception as exc:  # pragma: no cover - network failures
                logger.exception("Failed to update field %s", field_slug)
                return {
                    "error": redact(
                        f"Failed to update field {field_slug!r}: {exc}", value
                    )
                }
            return {
                "result": {
                    "secret_id": secret_id,
                    "field": field_slug,
                    "updated": True,
                    "source": str(file_path),
                }
            }
        if not (source == "stdin" or source.startswith("env:")):
            raise ValueError(
                f"Unsupported source {source!r}; use 'stdin', 'env:VAR' or 'file:/path'"
            )
        job = {
            "url": session.base_url.rstrip("/") + "/api" + field_path,
            "token": session.token,
            "params": params,
            "source": source,
            "secret_id": secret_id,
            "field": field_slug,
            "expires": time.time() + _SCRIPT_TTL_SECONDS,
        }
        job_path = _write_private(json.dumps(job), ".json")
        purpose = f"Writes field {field_slug!r} on secret {secret_id}"
        if source == "stdin":
            purpose += (
                "; prompts for the value, so the user must run it in their own terminal"
            )
        return {
            "command": _python_command(env, job_path),
            "shell": env,
            "purpose": purpose,
            "note": (
                "Runs this server's own Python, so nothing else needs to be "
                "installed. The job file holds a short-lived access token and "
                "deletes itself when used (or after 15 minutes). Do not print "
                "or copy it."
            ),
        }

    url = f"{session.base_url}/api/v1/secrets/{secret_id}/fields/{field_slug}"
    if comment:
        from urllib.parse import quote

        url += f"?autoCheckout=true&autoCheckIn=true&autoComment={quote(comment)}"
    access_token = session.token

    if env == "bash":
        if source.startswith("env:"):
            var_name = source[4:]
            read_cmd = f'VALUE="${{{var_name}}}"'
        elif source.startswith("file:"):
            file_path = source[5:]
            read_cmd = f'VALUE="$(cat {file_path})"'
        else:  # stdin
            read_cmd = 'echo "Enter secret value:"; read -rs VALUE'

        body = (
            "# Requires: curl, jq\n"
            f"{read_cmd}\n"
            "jq -n --arg v \"$VALUE\" '{value: $v}' | curl -fsS -X PUT \\\n"
            f'  -H "Authorization: Bearer {access_token}" \\\n'
            f'  -H "Content-Type: application/json" \\\n'
            "  --data-binary @- \\\n"
            f"  '{url}' >/dev/null && \\\n"
            f'echo "Field {field_slug} updated on secret {secret_id}"\n'
            "unset VALUE"
        )
    elif env == "powershell":
        if source.startswith("env:"):
            var_name = source[4:]
            read_cmd = f"$Value = $env:{var_name}"
        elif source.startswith("file:"):
            file_path = source[5:]
            read_cmd = f'$Value = Get-Content -Raw "{file_path}"'
        else:
            read_cmd = '$Value = Read-Host -Prompt "Enter secret value" -AsSecureString | ConvertFrom-SecureString -AsPlainText'

        body = (
            f"{read_cmd}\n"
            f'$headers = @{{"Authorization" = "Bearer {access_token}"; "Content-Type" = "application/json"}}\n'
            f'$body = @{{"value" = $Value}} | ConvertTo-Json\n'
            f'Invoke-RestMethod -Method Put -Uri "{url}" -Headers $headers -Body $body\n'
            f'Write-Host "Field {field_slug} updated on secret {secret_id}"'
        )
    elif env == "cmd":
        if source.startswith("env:"):
            var_name = source[4:]
            read_cmd = f"set VALUE=%{var_name}%"
        elif source.startswith("file:"):
            file_path = source[5:]
            read_cmd = f'set /p VALUE=<"{file_path}"'
        else:
            read_cmd = "set /p VALUE=Enter secret value: "

        body = (
            "REM Requires: curl\n"
            f"{read_cmd}\n"
            f'curl -s -X PUT -H "Authorization: Bearer {access_token}" '
            f'-H "Content-Type: application/json" '
            f'-d "{{\\"value\\": \\"%VALUE%\\"}}" '
            f'"{url}"\n'
            f"echo Field {field_slug} updated on secret {secret_id}"
        )
    return body


def update_secret_generated_password(
    secret_id: int,
    field_slug: str,
    password_field_id: int,
    comment: str | None = None,
) -> dict:  # pragma: no cover
    """Rotate a password field on an existing secret with a server-generated value.

    The new password is generated using the template field's password rules and
    written directly to the vault via
    ``PUT /v1/secrets/{id}/fields/{slug}``.  The model **never** sees the old
    or new password value.

    Before modifying a secret, check whether it requires approval:

    1. Call ``get_secret(id, summary=True)`` and inspect
       ``requiresApproval`` and ``requiresComment``.
    2. If approval is required, call ``get_pending_access_requests()``
       to check for an existing grant, or request access and wait for
       approval via ``handle_access_request()``.
    3. Always provide the *comment* parameter explaining **why** this
       secret is being modified.  If the action is tied to a ticket,
       incident, or change request, that reference **must** be named
       in the comment.

    Parameters
    ----------
    secret_id:
        ID of the secret to update.
    field_slug:
        Field slug of the password field (e.g. ``"password"``).
        Use ``check_secret_template`` to discover slugs.
    password_field_id:
        ``secretTemplateFieldId`` of the password field.  Used to generate a
        compliant password via the template rules.
    comment:
        Required when the secret has ``requiresComment`` or
        ``requiresApproval`` set.  Must explain **why** this secret is
        being modified and, if the action is tied to a formal request
        (e.g. a Jira ticket, incident, or change request), that
        reference must be included.

    Returns
    -------
    dict
        ``{"result": {...}, "verification": {...}}`` with safe metadata only.
        The password value is never included.
    """
    logger.debug(
        "update_secret_generated_password(secret_id=%s, slug=%s, field=%s)",
        secret_id,
        field_slug,
        password_field_id,
    )
    session = SessionManager.get()

    # Pre-check approval requirements
    check = _check_secret_approval(session, secret_id, comment)
    if check is not None:
        return check

    try:
        # 1. Generate new password server-side
        gen_resp = session.request(
            "POST",
            f"/v1/secret-templates/generate-password/{password_field_id}",
        )
        generated_password = gen_resp.json()
        if isinstance(generated_password, dict):
            generated_password = generated_password.get(
                "password", generated_password.get("value", "")
            )
        if not generated_password:
            return {"error": "Password generation returned empty result"}

        # 2. Update the field on the existing secret
        put_kwargs: dict[str, Any] = {"json": {"value": generated_password}}
        if comment:
            put_kwargs["params"] = {
                "autoCheckout": "true",
                "autoCheckIn": "true",
                "autoComment": comment,
            }
        session.request(
            "PUT",
            f"/v1/secrets/{secret_id}/fields/{field_slug}",
            sensitive=[str(generated_password)],
            **put_kwargs,
        )

        # 3. Verify via summary (never returns field values)
        verify: dict = {}
        try:
            verify = session.request("GET", f"/v1/secrets/{secret_id}/summary").json()
        except Exception as exc:  # pragma: no cover - network failures
            logger.exception("Secret verification failed after password update")
            verify = {"error": str(exc)}

        return {
            "result": {
                "secret_id": secret_id,
                "field_slug": field_slug,
                "password_rotated": True,
            },
            "verification": verify,
        }

    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to update secret password")
        return {"error": f"Failed to update secret password: {exc}"}


def list_example_reports() -> str | dict:
    """Return the reference for writing ``run_report`` SQL.

    Includes tested example queries, the Secret Server database tables and
    columns they use, special fields, and the rules Secret Server enforces on
    custom report SQL (a single read-only SELECT). Read this before composing
    a ``run_report`` query.
    """
    logger.debug("list_example_reports")
    return (
        constants.EXAMPLE_QUERIES_TEXT
        + "\n\nTables and Columns:\n"
        + constants.TABLES_AND_COLUMNS
        + "\n\nSpecial Fields:\n"
        + constants.SPECIAL_FIELDS
        + "\n"
        + constants.REPORT_SQL_RULES
    )


MASK = "********"


def _mask_secret(data: Any) -> Any:
    """Replace password-type field values in a ``/v2/secrets`` payload.

    Masking happens server-side so the plaintext never reaches the model
    unless the human approves it through :func:`reveal_secret_field`.
    """
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return data
    masked: list[str] = []
    for item in data["items"]:
        if isinstance(item, dict) and item.get("isPassword") and item.get("itemValue"):
            item["itemValue"] = MASK
            masked.append(item.get("slug") or item.get("fieldName") or "?")
    if masked:
        data["maskedFields"] = masked
        note = (
            "Password fields are masked. To use a credential without exposing "
            "it, use get_secret_environment_variable."
        )
        if _reveal_mode() == "disabled":
            note += (
                " Showing plaintext is disabled on this server; the user or an "
                "administrator can enable it (plugin setting 'Allow revealing "
                "passwords', or secret_reveal_mode in config.json)."
            )
        else:
            note += (
                " Only if the user explicitly needs to see the plaintext, call "
                "reveal_secret_field; the user must approve that in their client."
            )
        data["maskedNote"] = note
    return data


def get_secret(id: int, summary: bool = False) -> dict:
    """Retrieve a secret's fields, with password-type values masked.

    Values of fields that the secret template marks as passwords are
    replaced with ``********`` and listed under ``maskedFields``. Use
    ``summary=True`` for metadata only (name, folder, template, approval
    and checkout requirements). To put a credential to work without
    exposing it, use ``get_secret_environment_variable``. Showing a masked
    value needs ``reveal_secret_field``, which is only available when the
    server has plaintext reveal enabled.

    Parameters
    ----------
    id:
        Numeric secret identifier.
    summary:
        When ``True`` return only the summary information.

    Returns
    -------
    dict
        JSON representation of the secret on success or an ``error`` key.
    """
    logger.debug("get_secret(%s, summary=%s)", id, summary)
    session = SessionManager.get()
    path = f"/v1/secrets/{id}/summary" if summary else f"/v2/secrets/{id}"
    try:
        data = session.request("GET", path).json()
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to retrieve secret %s", id)
        return {"error": f"Failed to retrieve secret {id}: {exc}"}
    return data if summary else _mask_secret(data)


class RevealConfirmation(BaseModel):
    """Approve showing this secret value to the AI assistant."""

    # Rendered by the client's approval dialog, so title and description are
    # user-facing text rather than code names.
    model_config = ConfigDict(title="Reveal secret value")

    confirm: bool = Field(
        title="Show the value",
        description="Show this value in plaintext to the AI assistant?",
    )


class _RevealGate(BaseModel):
    """Resolver outcome that settles a reveal without asking the human."""

    error: str | None = None  # refuse with this message; None = proceed

    def __init__(self, error: str | None = None) -> None:
        super().__init__(error=error)


_REVEAL_MODES = {"elicit", "client_approval", "disabled"}
# The plugin's "Allow revealing passwords" setting arrives as true/false.
_REVEAL_ALIASES = {"true": "elicit", "false": "disabled", "": "disabled"}


def _reveal_mode() -> str:
    """Return how plaintext reveals are authorised (see README).

    Reveal is off unless explicitly enabled, through the
    ``secret_reveal_mode`` config key or the ``DELINEA_SECRET_REVEAL_MODE``
    environment variable. Unrecognised values count as ``disabled``.
    """
    raw = _CFG.get("secret_reveal_mode")
    if raw is None:
        raw = os.getenv("DELINEA_SECRET_REVEAL_MODE", "disabled")
    mode = str(raw).strip().lower()
    mode = _REVEAL_ALIASES.get(mode, mode)
    return mode if mode in _REVEAL_MODES else "disabled"


def _client_supports_elicitation(ctx: Context) -> bool:
    try:
        return ctx.session.check_client_capability(
            ClientCapabilities(elicitation=ElicitationCapability())
        )
    except Exception:  # pragma: no cover - no active request
        return False


def _confirm_reveal(
    secret_id: int, field_slug: str, ctx: Context, comment: str | None = None
) -> Elicit[RevealConfirmation] | _RevealGate:
    """Decide whether to ask the human, refuse, or proceed.

    Runs before the tool body. Returning ``Elicit`` makes the MCP framework
    ask the user through their client, using whichever mechanism the
    negotiated protocol supports; the model cannot answer that prompt.
    """
    mode = _reveal_mode()
    if mode == "disabled":
        return _RevealGate(
            "Plaintext reveal is disabled on this server "
            "(secret_reveal_mode=disabled). Use get_secret_environment_variable "
            "to use the credential without displaying it."
        )
    check = _check_secret_approval(SessionManager.get(), secret_id, comment)
    if check is not None:
        return _RevealGate(check["error"])
    if mode == "client_approval":
        return _RevealGate()
    if not _client_supports_elicitation(ctx):
        return _RevealGate(
            "This MCP client cannot show a confirmation prompt (elicitation), "
            "so the value was not revealed. Use get_secret_environment_variable "
            "instead, or ask the server administrator to set "
            "secret_reveal_mode=client_approval."
        )
    return Elicit(
        message=(
            f"The AI assistant wants to see the plaintext value of field "
            f"'{field_slug}' on secret {secret_id}. If you approve, the value is "
            "shown to the assistant and saved in this conversation's transcript."
        ),
        schema=RevealConfirmation,
    )


async def reveal_secret_field(
    secret_id: int,
    field_slug: str,
    approval: Annotated[
        ElicitationResult[RevealConfirmation], Resolve(_confirm_reveal)
    ],
    comment: str | None = None,
) -> dict:
    """Return one secret field's plaintext value after the human approves.

    Call this only when the user has explicitly asked to *see* a value that
    ``get_secret`` masked. If the user only needs the credential to run a
    command, use ``get_secret_environment_variable`` instead, which keeps the
    value out of the conversation.

    Before releasing anything, the server asks the user directly for
    confirmation in their MCP client (elicitation); a model cannot answer
    that prompt. If the user declines, or the client cannot show the prompt,
    nothing is revealed. The revealed value becomes part of the conversation
    transcript.

    Parameters
    ----------
    secret_id:
        ID of the secret.
    field_slug:
        Field slug from ``maskedFields`` in the ``get_secret`` result, for
        example ``"password"``.
    comment:
        Required when the secret has ``requiresComment`` or
        ``requiresApproval``; explain why the value is needed and reference
        any ticket or change request.

    Returns
    -------
    dict
        ``{"secret_id", "field", "value"}`` on success, or an ``error`` key.
    """
    logger.debug("reveal_secret_field(%s, %s)", secret_id, field_slug)
    if not isinstance(approval, AcceptedElicitation):
        return {
            "error": (
                "The user declined to reveal the value. Do not retry unless "
                "the user asks again."
            )
        }
    decision = approval.data
    if isinstance(decision, _RevealGate):
        if decision.error:
            return {"error": decision.error}
    elif not decision.confirm:
        return {
            "error": (
                "The user declined to reveal the value. Do not retry unless "
                "the user asks again."
            )
        }

    session = SessionManager.get()
    path = f"/v1/secrets/{secret_id}/fields/{field_slug}"
    params = None
    if comment:
        params = {"autoCheckout": "true", "autoCheckIn": "true", "autoComment": comment}
    try:
        response = await anyio.to_thread.run_sync(
            lambda: session.request("GET", path, params=params)
        )
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to reveal field %s on %s", field_slug, secret_id)
        return {"error": f"Failed to read field '{field_slug}': {exc}"}
    try:
        value = response.json()
    except ValueError:
        value = response.text
    return {"secret_id": secret_id, "field": field_slug, "value": value}


def get_folder(id: int, all_children: bool = False) -> dict:
    """Return folder metadata for the given folder ID.

    Parameters
    ----------
    id:
        Identifier of the folder to fetch.
    all_children:
        When ``True`` include ``childFolders`` with the full descendant
        tree, which can be large. To page through direct children only, use
        ``folder_management("list", params={"filter.parentFolderId": id})``.

    Returns
    -------
    dict
        Folder metadata including children or an ``error`` message.
    """
    logger.debug("get_folder(%s, all_children=%s)", id, all_children)
    session = SessionManager.get()
    params = {"getAllChildren": "true" if all_children else "false"}
    try:
        return session.request("GET", f"/v1/folders/{id}", params=params).json()
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to retrieve folder %s", id)
        return {"error": f"Failed to retrieve folder {id}: {exc}"}


def search_secrets(
    query: str, lookup: bool = False, take: int = DEFAULT_PAGE_SIZE, skip: int = 0
) -> dict:
    """Search or look up secrets.

    Parameters
    ----------
    query:
        Search text.
    lookup:
        If ``True``, perform a metadata lookup instead of a full search.
    take:
        Page size (default 50, capped at 500).
    skip:
        Number of records to skip, for paging with ``take``.

    Returns
    -------
    dict
        JSON response from the appropriate search endpoint.
    """
    logger.debug("search_secrets(%s, lookup=%s)", query, lookup)
    session = SessionManager.get()
    path = "/v1/secrets/lookup" if lookup else "/v2/secrets"
    try:
        params = _paged({"filter.searchText": query}, take, skip)
        return session.request("GET", path, params=params).json()
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to search secrets %s", query)
        return {"error": f"Failed to search secrets '{query}': {exc}"}


def search_folders(
    query: str, lookup: bool = False, take: int = DEFAULT_PAGE_SIZE, skip: int = 0
) -> dict:
    """Search or look up folders.

    Parameters
    ----------
    query:
        Text to search for in folder names.
    lookup:
        If ``True``, query the ``/lookup`` endpoint for metadata only.
    take:
        Page size (default 50, capped at 500).
    skip:
        Number of records to skip, for paging with ``take``.

    Returns
    -------
    dict
        JSON payload from the search call.
    """
    logger.debug("search_folders(%s, lookup=%s)", query, lookup)
    session = SessionManager.get()
    path = "/v1/folders/lookup" if lookup else "/v1/folders"
    try:
        params = _paged({"filter.searchText": query}, take, skip)
        return session.request("GET", path, params=params).json()
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to search folders %s", query)
        return {"error": f"Failed to search folders '{query}': {exc}"}


def check_secret_template_field(
    template_id: int, field_id: str
) -> dict:  # pragma: no cover
    """Check if a field exists in the given secret template.

    Parameters
    ----------
    template_id:
        Identifier of the secret template.
    field_id:
        Numeric field ID or field name to search for.

    Returns
    -------
    dict
        ``{"exists": bool, "field": {...}}`` when found or a message when not
        present.
    """
    logger.debug("check_secret_template_field(%s, %s)", template_id, field_id)
    session = SessionManager.get()
    try:
        result = session.request(
            "GET",
            "/v1/secret-templates/fields/search",
            params={
                "filter.secretTemplateId": template_id,
                "filter.searchText": field_id,
                "take": 1,
            },
        ).json()
        for field in result.get("records", []):
            if str(field.get("id")) == str(field_id) or field.get("name") == str(
                field_id
            ):
                return {"exists": True, "field": field}
        return {
            "exists": False,
            "message": f"Field '{field_id}' not found in template {template_id}",
        }
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception(
            "Failed to check secret template %s for field %s", template_id, field_id
        )
        return {
            "error": f"Failed to check secret template {template_id} for field {field_id}: {exc}"
        }


def get_secret_template_field(field_id: int) -> dict:
    """Retrieve details for a secret template field.

    Parameters
    ----------
    field_id:
        Numeric identifier of the field to fetch.

    Returns
    -------
    dict
        JSON object describing the field or an ``error`` key on failure.
    """
    logger.debug("get_secret_template_field(%s)", field_id)
    session = SessionManager.get()
    try:
        return session.request("GET", f"/v1/secret-templates/fields/{field_id}").json()
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to retrieve secret template field %s", field_id)
        return {"error": f"Failed to retrieve secret template field {field_id}: {exc}"}


def handle_access_request(
    request_id: int,
    status: str,
    response_comment: str,
    start_date: str | None = None,
    expiration_date: str | None = None,
) -> dict:  # pragma: no cover
    """Approve or deny a pending secret access request.

    Parameters
    ----------
    request_id:
        Identifier of the access request to modify.
    status:
        Either ``"Approved"`` or ``"Denied"``.
    response_comment:
        Comment explaining the decision.
    start_date, expiration_date:
        Optional ISO date strings used when approving the request. If these
        values are present in the object returned by
        :func:`get_pending_access_requests`, include them by default unless
        overridden.

    Returns
    -------
    dict
        ``{"result": ... , "verification": ...}`` where ``result`` contains the
        API response from the update call and ``verification`` contains the
        request retrieved afterwards.
    """
    logger.debug(
        "handle_access_request(%s, %s, %s, %s, %s)",
        request_id,
        status,
        response_comment,
        start_date,
        expiration_date,
    )
    session = SessionManager.get()
    if status not in ["Approved", "Denied"]:
        return {"error": "Invalid status. Must be 'Approved' or 'Denied'."}
    payload = {
        "secretAccessRequestId": request_id,
        "status": status,
        "responseComment": response_comment,
    }
    if start_date:
        payload["startDate"] = start_date
    if expiration_date:
        payload["expirationDate"] = expiration_date
    try:
        response = session.request(
            "PUT",
            "/v1/secret-access-requests",
            json=payload,
        )
        result = response.json()
        verify = {}
        try:
            verify = session.request(
                "GET",
                f"/v1/secret-access-requests/{request_id}",
            ).json()
        except Exception as exc:  # pragma: no cover - network failures
            logger.exception("Access request verification failed")
            verify = {"error": str(exc)}
        return {"result": result, "verification": verify}
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception(
            "Failed to handle access request %s with status %s",
            request_id,
            status,
        )
        return {
            "error": f"Failed to handle access request {request_id} with status {status}: {exc}"
        }


def get_pending_access_requests() -> dict:  # pragma: no cover
    """Retrieve pending secret access requests for the current user.

    Returns
    -------
    dict
        Raw API response containing pending requests or an ``error`` key on
        failure.
    """
    logger.debug("get_pending_access_requests")
    session = SessionManager.get()
    try:
        response = session.request(
            "GET",
            "/v1/secret-access-requests",
            params={
                "filter.isMyRequest": "false",
                "filter.status": "Pending",
                "skip": 0,
                "sortBy[0].direction": "desc",
                "sortBy[0].name": "startDate",
                "take": 60,
            },
        )
        return response.json()
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to retrieve pending access requests")
        return {"error": f"Failed to retrieve pending access requests: {exc}"}


def get_inbox_messages(
    read_status_filter: str | None = None,
    take: int = 20,
    skip: int = 0,
) -> dict:  # pragma: no cover
    """Search, filter, sort and page inbox messages.

    Parameters
    ----------
    read_status_filter:
        Optional filter value of ``"Read"`` or ``"Unread"``.
    take, skip:
        Paging parameters controlling the number of messages returned and the
        starting offset.

    Returns
    -------
    dict
        Raw JSON response from the ``/v1/inbox/messages`` endpoint.
    """
    logger.debug(
        "get_inbox_messages(read_status_filter=%s, take=%d, skip=%d)",
        read_status_filter,
        take,
        skip,
    )
    session = SessionManager.get()
    params = {
        "take": take,
        "skip": skip,
    }
    if read_status_filter:
        params["filter.readStatusFilter"] = read_status_filter
    try:
        response = session.request("GET", "/v1/inbox/messages", params=params)
        return response.json()
    except Exception as exc:
        logger.exception("Failed to get inbox messages")
        return {"error": f"Failed to get inbox messages: {exc}"}


def mark_inbox_messages_read(
    message_ids: list[int],
    read: bool = True,
) -> dict:  # pragma: no cover
    """Mark one or more inbox messages as read or unread.

    Parameters
    ----------
    message_ids:
        List of message identifiers to update.
    read:
        ``True`` to mark the messages as read or ``False`` to mark them as
        unread.

    Returns
    -------
    dict
        ``{"result": ..., "verification": ...}`` where ``result`` contains the
        outcome of the update and ``verification`` is the inbox listing after the
        change.
    """

    logger.debug("mark_inbox_messages_read(message_ids=%s, read=%s)", message_ids, read)
    session = SessionManager.get()
    payload = {"data": {"messageIds": message_ids, "read": read}}
    try:
        response = session.request(
            "POST",
            "/v1/inbox/update-read",
            json=payload,
        )
        result = response.json() if response.content else {"success": True}
        verify = {}
        try:
            verify = session.request(
                "GET",
                "/v1/inbox/messages",
                params={"take": 20, "skip": 0},
            ).json()
        except Exception as exc:  # pragma: no cover - network failures
            logger.exception("Inbox verification failed")
            verify = {"error": str(exc)}
        return {"result": result, "verification": verify}
    except Exception as exc:
        logger.exception("Failed to mark inbox messages read/unread")
        return {"error": f"Failed to mark inbox messages read/unread: {exc}"}


def role_management(
    action: str,
    role_id: int | None = None,
    data: dict | None = None,
    params: dict | None = None,
) -> dict:
    """Create, update or query roles.

    Parameters
    ----------
    action:
        One of ``"list"``, ``"get"``, ``"create"`` or ``"update"``.
    role_id:
        Identifier of the role to operate on. Required for ``"get"`` and
        ``"update"``.
    data:
        JSON body used with ``"create"`` and ``"update"``.
    params:
        Optional query parameters for ``"list"``.

    When ``action`` is ``"create"``, ``data`` must contain the required keys
    ``name`` and ``enabled`` defining the role's name and active state.
    When ``action`` is ``"update"``, you need to do a get first, update the
    relevant fields and post everything back

    ``"create"`` and ``"update"`` actions issue a follow-up ``GET`` request to
    confirm the new role state. The function returns ``{"result": ...,
    "verification": ...}`` where ``result`` is the response from the write
    operation and ``verification`` is the data retrieved from the subsequent
    ``GET`` call.

    Returns
    -------
    dict
        Dictionary containing ``result`` from the write call and
        ``verification`` from the subsequent ``GET``.
    """

    logger.debug(
        "role_management(action=%s, role_id=%s, data=%s)", action, role_id, data
    )
    session = SessionManager.get()
    data = _parse_json_data(data)

    try:
        if action == "list":
            return session.request("GET", "/v1/roles", params=_paged(params)).json()
        if action == "get":
            if role_id is None:
                raise ValueError("role_id required for get")
            return session.request("GET", f"/v1/roles/{role_id}").json()
        if action == "update":
            if role_id is None or data is None:
                raise ValueError("role_id and data required for update")
            result = session.request("PATCH", f"/v1/roles/{role_id}", json=data).json()
            verify = {}
            try:
                verify = session.request("GET", f"/v1/roles/{role_id}").json()
            except Exception as exc:  # pragma: no cover - network failures
                logger.exception("Role verification failed after update")
                verify = {"error": str(exc)}
            return {"result": result, "verification": verify}
        if action == "create":
            result = session.request("POST", "/v1/roles", json=data or {}).json()
            role_id = result.get("id") or result.get("roleId")
            verify = {}
            if role_id is not None:
                try:
                    verify = session.request("GET", f"/v1/roles/{role_id}").json()
                except Exception as exc:  # pragma: no cover - network failures
                    logger.exception("Role verification failed after create")
                    verify = {"error": str(exc)}
            return {"result": result, "verification": verify}
        raise ValueError(f"Unknown action: {action}")
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Role management action failed")
        return {"error": str(exc)}


def user_role_management(
    action: str,
    user_id: int,
    role_ids: list[int] | None = None,
) -> dict:
    """Add or remove roles for a user.

    Parameters
    ----------
    action:
        ``"get"`` to list current roles, ``"add"`` to assign new roles or
        ``"remove"`` to revoke them.
    user_id:
        Identifier of the target user.
    role_ids:
        List of role identifiers used with ``"add"`` and ``"remove"``.

    Returns
    -------
    dict
        JSON payload from the API.
    """

    logger.debug(
        "user_role_management(action=%s, user_id=%s, role_ids=%s)",
        action,
        user_id,
        role_ids,
    )
    session = SessionManager.get()

    try:
        if action == "get":
            return session.request("GET", f"/v1/users/{user_id}/roles").json()
        if action == "add":
            if not role_ids:
                raise ValueError("role_ids required for add")
            return session.request(
                "POST", f"/v1/users/{user_id}/roles", json={"roleIds": role_ids}
            ).json()
        if action == "remove":
            if not role_ids:
                raise ValueError("role_ids required for remove")
            return session.request(
                "DELETE", f"/v1/users/{user_id}/roles", json={"roleIds": role_ids}
            ).json()
        raise ValueError(f"Unknown action: {action}")
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("User role management action failed")
        return {"error": str(exc)}


def group_management(
    action: str,
    group_id: int | None = None,
    data: dict | None = None,
    params: dict | None = None,
) -> dict:
    """Create, list or delete groups.

    Parameters
    ----------
    action:
        ``"get"``, ``"list"``, ``"create`` or ``"delete"``.
    group_id:
        Group identifier required for ``"get"`` and ``"delete"``.
    data:
        JSON payload used with ``"create"``.
    params:
        Optional filters for ``"list"``.

    When ``action`` is ``"create"``, ``data`` must include ``name`` and
    ``enabled``. Optional keys include ``adGuid``, ``domainId``,
    ``hasGroupOwners``, ``isPlatform``, ``ownerGroupIds``, ``ownerGroupNames``,
    ``ownerUserIds``, ``ownerUserNames``, ``synchronized`` and
    ``synchronizeNow``.
    When ``action`` is ``"update"``, you need to do a get first, update the
    relevant fields and post everything back

    ``"create"`` and ``"delete"`` actions perform a verifying ``GET`` after the
    write. The response contains ``{"result": ... , "verification": ...}``.

    Returns
    -------
    dict
        Dictionary with ``result`` from the write operation and
        ``verification`` from the subsequent ``GET`` call.
    """

    logger.debug(
        "group_management(action=%s, group_id=%s, data=%s)", action, group_id, data
    )
    session = SessionManager.get()
    data = _parse_json_data(data)

    try:
        if action == "get":
            if group_id is None:
                raise ValueError("group_id required for get")
            return session.request("GET", f"/v1/groups/{group_id}").json()
        if action == "list":
            return session.request("GET", "/v1/groups", params=_paged(params)).json()
        if action == "create":
            result = session.request("POST", "/v1/groups", json=data or {}).json()
            group_id = result.get("id") or result.get("groupId")
            verify = {}
            if group_id is not None:
                try:
                    verify = session.request("GET", f"/v1/groups/{group_id}").json()
                except Exception as exc:  # pragma: no cover - network failures
                    logger.exception("Group verification failed after create")
                    verify = {"error": str(exc)}
            return {"result": result, "verification": verify}
        if action == "delete":
            if group_id is None:
                raise ValueError("group_id required for delete")
            result = session.request("DELETE", f"/v1/groups/{group_id}").json()
            verify = {}
            try:
                verify = session.request("GET", f"/v1/groups/{group_id}").json()
            except Exception as exc:  # pragma: no cover - network failures
                verify = {"error": str(exc)}
            return {"result": result, "verification": verify}
        raise ValueError(f"Unknown action: {action}")
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Group management action failed")
        return {"error": str(exc)}


def user_group_management(
    action: str,
    user_id: int,
    group_ids: list[int] | None = None,
) -> dict:
    """Add or remove a user from groups.

    Parameters
    ----------
    action:
        ``"get"`` to list groups for the user, ``"add"`` to add the user to
        groups or ``"remove"`` to remove them.
    user_id:
        Target user identifier.
    group_ids:
        List of group identifiers used with ``"add"`` and ``"remove"``.

    Returns
    -------
    dict
        API response content.
    """

    logger.debug(
        "user_group_management(action=%s, user_id=%s, group_ids=%s)",
        action,
        user_id,
        group_ids,
    )
    session = SessionManager.get()

    try:
        if action == "get":
            return session.request("GET", f"/v1/users/{user_id}/groups").json()
        if action == "add":
            if not group_ids:
                raise ValueError("group_ids required for add")
            return session.request(
                "POST", f"/v1/users/{user_id}/groups", json={"groupIds": group_ids}
            ).json()
        if action == "remove":
            if not group_ids:
                raise ValueError("group_ids required for remove")
            return session.request(
                "DELETE", f"/v1/users/{user_id}/groups", params={"groupIds": group_ids}
            ).json()
        raise ValueError(f"Unknown action: {action}")
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("User group management action failed")
        return {"error": str(exc)}


def group_role_management(
    action: str,
    group_id: int,
    role_ids: list[int] | None = None,
) -> dict:
    """Assign or revoke roles on a group.

    Parameters
    ----------
    action:
        ``"list"`` to view current roles, ``"add"`` to attach roles or
        ``"remove"`` to detach them.
    group_id:
        Target group identifier.
    role_ids:
        List of roles used with ``"add"`` and ``"remove"``.

    Returns
    -------
    dict
        Response body from the API.
    """

    logger.debug(
        "group_role_management(action=%s, group_id=%s, role_ids=%s)",
        action,
        group_id,
        role_ids,
    )
    session = SessionManager.get()

    try:
        if action == "list":
            return session.request("GET", f"/v1/groups/{group_id}/roles").json()
        if action == "add":
            if not role_ids:
                raise ValueError("role_ids required for add")
            return session.request(
                "POST", f"/v1/groups/{group_id}/roles", json={"roleIds": role_ids}
            ).json()
        if action == "remove":
            if not role_ids:
                raise ValueError("role_ids required for remove")
            return session.request(
                "DELETE", f"/v1/groups/{group_id}/roles", json={"roleIds": role_ids}
            ).json()
        raise ValueError(f"Unknown action: {action}")
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Group role management action failed")
        return {"error": str(exc)}


def folder_management(
    action: str,
    folder_id: int | None = None,
    data: dict | None = None,
    params: dict | None = None,
) -> dict:
    """Create, update or query folders.

    Parameters
    ----------
    action:
        ``"get"``, ``"list"``, ``"create"``, ``"update"`` or ``"delete"``.
    folder_id:
        Folder identifier required for ``"get"``, ``"update"`` and ``"delete"``.
    data:
        JSON body used with ``"create"`` and ``"update"``. Create needs
        ``folderName``, ``parentFolderId`` (``-1`` for the root) and
        ``folderTypeId`` (``1``); ``inheritPermissions`` and
        ``inheritSecretPolicy`` are optional booleans.
    params:
        Optional query parameters for ``"list"``.

    ``"create"``, ``"update"`` and ``"delete"`` actions perform a verifying
    ``GET`` after the write. The response contains ``{"result": ... ,
    "verification": ...}``.

    Returns
    -------
    dict
        Dictionary with ``result`` from the write operation and
        ``verification`` from the subsequent ``GET`` call.
    """

    logger.debug(
        "folder_management(action=%s, folder_id=%s, data=%s)",
        action,
        folder_id,
        data,
    )
    session = SessionManager.get()
    data = _parse_json_data(data)

    try:
        if action == "get":
            if folder_id is None:
                raise ValueError("folder_id required for get")
            return session.request(
                "GET", f"/v1/folders/{folder_id}", params={"getAllChildren": "false"}
            ).json()
        if action == "list":
            return session.request("GET", "/v1/folders", params=_paged(params)).json()
        if action == "create":
            result = session.request("POST", "/v1/folders", json=data or {}).json()
            folder_id = result.get("id") or result.get("folderId")
            verify = {}
            if folder_id is not None:
                try:
                    verify = session.request("GET", f"/v1/folders/{folder_id}").json()
                except Exception as exc:  # pragma: no cover - network failures
                    logger.exception("Folder verification failed after create")
                    verify = {"error": str(exc)}
            return {"result": result, "verification": verify}
        if action == "update":
            if folder_id is None or data is None:
                raise ValueError("folder_id and data required for update")
            result = session.request(
                "PUT", f"/v1/folders/{folder_id}", json=data
            ).json()
            verify = {}
            try:
                verify = session.request("GET", f"/v1/folders/{folder_id}").json()
            except Exception as exc:  # pragma: no cover - network failures
                logger.exception("Folder verification failed after update")
                verify = {"error": str(exc)}
            return {"result": result, "verification": verify}
        if action == "delete":
            if folder_id is None:
                raise ValueError("folder_id required for delete")
            result = session.request("DELETE", f"/v1/folders/{folder_id}").json()
            verify = {}
            try:
                verify = session.request("GET", f"/v1/folders/{folder_id}").json()
            except Exception as exc:  # pragma: no cover - network failures
                verify = {"error": str(exc)}
            return {"result": result, "verification": verify}
        raise ValueError(f"Unknown action: {action}")
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Folder management action failed")
        return {"error": str(exc)}


def health_check() -> dict:
    """Return the current server health status.

    The endpoint responds with general service information and ``{"status": "Healthy"}``
    when the server is operational.
    """
    logger.debug("health_check")
    session = SessionManager.get()
    try:
        return session.request("GET", "/v1/healthcheck", params={"noBus": True}).json()
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to call health check")
        return {"error": f"Failed to perform health check: {exc}"}


def search(query: str) -> dict:
    """Return search results in MCP format.

    Parameters
    ----------
    query:
        Text to search across the enabled object types.

    Returns
    -------
    dict
        ``{"results": [...]}`` where each result object contains ``id``,
        ``title``, ``text`` and ``url`` as defined by the MCP specification.
    """
    logger.debug("search(%s)", query)
    from . import secretserver_users

    mapping = {
        "secret": search_secrets,
        "user": secretserver_users.search_secretserver_local_users,
        "folder": search_folders,
        "group": lambda q: group_management("list", params={"filter.searchText": q}),
        "role": lambda q: role_management("list", params={"filter.searchText": q}),
    }

    base = _api_base_url()
    results: list[dict] = []
    for kind in sorted(_SEARCH_ALLOWED):
        func = mapping.get(kind)
        if func is None:
            continue
        try:
            data = func(query)
        except Exception:  # pragma: no cover - network failures
            logger.exception("search failed for %s", kind)
            continue

        records = data.get("records", []) if isinstance(data, dict) else []
        for rec in records:
            rec_id = (
                rec.get("id")
                or rec.get("userId")
                or rec.get("folderId")
                or rec.get("groupId")
                or rec.get("roleId")
            )
            if rec_id is None:
                continue
            title = (
                rec.get("name")
                or rec.get("username")
                or rec.get("folderName")
                or rec.get("groupName")
                or rec.get("roleName")
                or str(rec_id)
            )
            # The entire record JSON is returned as ``text``
            text = json.dumps(rec, sort_keys=True)
            url_map = {
                "secret": (
                    f"{base}/v2/secrets/{rec_id}" if base else f"/v2/secrets/{rec_id}"
                ),
                "user": f"{base}/v1/users/{rec_id}" if base else f"/v1/users/{rec_id}",
                "folder": (
                    f"{base}/v1/folders/{rec_id}" if base else f"/v1/folders/{rec_id}"
                ),
                "group": (
                    f"{base}/v1/groups/{rec_id}" if base else f"/v1/groups/{rec_id}"
                ),
                "role": f"{base}/v1/roles/{rec_id}" if base else f"/v1/roles/{rec_id}",
            }
            url = url_map.get(
                kind, f"{base}/{kind}/{rec_id}" if base else f"/{kind}/{rec_id}"
            )
            identifier = f"{kind}/{rec_id}"
            results.append(
                {"id": identifier, "title": title, "text": text or title, "url": url}
            )
    return {"results": results}


def fetch(id: str) -> dict:
    """Retrieve the full record for an identifier returned by ``search``.

    Parameters
    ----------
    identifier:
        Value from the ``id`` field of a search result, in ``"<type>/<id>"``
        format.

    Returns
    -------
    dict
        Object with ``id``, ``title``, ``text``, ``url`` and ``metadata``
        fields as required by the MCP specification.
    """
    identifier = id
    if "/" not in identifier:
        raise ValueError(
            f"identifier {identifier!r} must be in '<type>/<id>' format, "
            "e.g. 'secret/42', as returned in search results"
        )
    kind, obj_id = identifier.split("/", 1)
    kind = kind.lower().rstrip("s")
    if kind not in _FETCH_ALLOWED:
        raise ValueError(
            f"fetch for {kind!r} is not enabled on this server; enabled types: "
            f"{', '.join(sorted(_FETCH_ALLOWED))}"
        )

    from . import secretserver_users

    mapping = {
        "secret": lambda i: get_secret(int(i)),
        "user": lambda i: secretserver_users.secretserver_local_user_management(
            "get", user_id=int(i)
        ),
        "folder": lambda i: get_folder(int(i)),
        "group": lambda i: group_management("get", group_id=int(i)),
        "role": lambda i: role_management("get", role_id=int(i)),
    }
    func = mapping.get(kind)
    if func is None:
        raise ValueError(f"unknown fetch type: {kind}")

    data = func(obj_id)
    title = (
        data.get("name")
        or data.get("username")
        or data.get("folderName")
        or data.get("groupName")
        or data.get("roleName")
        or str(obj_id)
    )
    # Return the entire document as the ``text`` value
    text = json.dumps(data, sort_keys=True)
    base = _api_base_url()
    url_map = {
        "secret": f"{base}/v2/secrets/{obj_id}" if base else f"/v2/secrets/{obj_id}",
        "user": f"{base}/v1/users/{obj_id}" if base else f"/v1/users/{obj_id}",
        "folder": f"{base}/v1/folders/{obj_id}" if base else f"/v1/folders/{obj_id}",
        "group": f"{base}/v1/groups/{obj_id}" if base else f"/v1/groups/{obj_id}",
        "role": f"{base}/v1/roles/{obj_id}" if base else f"/v1/roles/{obj_id}",
    }
    url = url_map.get(kind, f"{base}/{kind}/{obj_id}" if base else f"/{kind}/{obj_id}")
    return {
        "id": identifier,
        "title": title,
        "text": text,
        "url": url,
        "metadata": data,
    }


def update_secret_fields(
    secret_id: int,
    field_updates: dict[str, str] | str,
    comment: str | None = None,
    *,
    allow_password_fields: bool = False,
) -> dict:
    """Edit non-sensitive fields on an existing secret.

    Composes the read-mutate-verify flow:

    1. ``GET /v1/secrets/{id}/summary`` to check approval / comment
       requirements via :func:`_check_secret_approval`.
    2. ``GET /v1/secrets/{id}`` (template lookup) to identify which slugs
       are password fields.
    3. ``PUT /v1/secrets/{id}/fields/{slug}`` per entry in *field_updates*.
    4. ``GET /v1/secrets/{id}/summary`` for verification.

    By default, slugs whose template field has ``isPassword=True`` are
    refused — the model should not see plaintext password values.  Use
    :func:`set_secret_field_environment_variable` (which emits a shell
    script that reads the value locally and PUTs it without the value
    ever passing through the model) for password-class fields, or set
    ``allow_password_fields=True`` to override (not recommended).

    Parameters
    ----------
    secret_id:
        Identifier of the secret to update.
    field_updates:
        Mapping of ``field_slug -> new_value`` (or a JSON string).  Use
        slugs (e.g. ``"notes"``, ``"url"``, ``"hostname"``) discoverable
        via :func:`check_secret_template`.
    comment:
        Audit comment recorded against each field update.  Required when
        the secret has ``requiresComment`` or ``requiresApproval`` set.
        Must explain **why** the change is being made and reference any
        related ticket, incident, or change request.
    allow_password_fields:
        Set to ``True`` to permit updating password-class fields.  Doing
        so means the new value passes through the model — prefer
        :func:`set_secret_field_environment_variable` for those fields.

    Returns
    -------
    dict
        ``{"result": {...}, "verification": {...}}`` where ``result`` lists
        per-field outcomes and ``verification`` is the post-update summary.
    """

    logger.debug(
        "update_secret_fields(secret_id=%s, field_count=%s)",
        secret_id,
        len(field_updates) if hasattr(field_updates, "__len__") else "?",
    )
    session = SessionManager.get()

    parsed = (
        _parse_json_data(field_updates)
        if isinstance(field_updates, str)
        else field_updates
    )
    if not isinstance(parsed, dict) or not parsed:
        return {"error": "field_updates must be a non-empty mapping of slug -> value"}

    # Pre-check approval requirements
    check = _check_secret_approval(session, secret_id, comment)
    if check is not None:
        return check

    # Identify password-class fields on this secret's template
    password_slugs: set[str] = set()
    if not allow_password_fields:
        try:
            secret = session.request("GET", f"/v2/secrets/{secret_id}").json()
            template_id = secret.get("secretTemplateId")
            if template_id is not None:
                tmpl = session.request(
                    "GET", f"/v1/secret-templates/{template_id}"
                ).json()
                for f in tmpl.get("fields", []) or []:
                    if f.get("isPassword"):
                        slug = (
                            f.get("fieldSlugName") or f.get("slugName") or f.get("name")
                        )
                        if slug:
                            password_slugs.add(str(slug).lower())
        except Exception as exc:  # pragma: no cover - network failures
            logger.exception("Failed to inspect template for password fields")
            return {
                "error": (
                    f"Failed to verify password-field safety for secret {secret_id}: "
                    f"{exc}. Pass allow_password_fields=True to override."
                )
            }

    refused = [slug for slug in parsed if str(slug).lower() in password_slugs]
    if refused:
        return {
            "error": (
                f"Refusing to update password-class field(s) {refused} via this tool. "
                "Use set_secret_field_environment_variable so the value never enters "
                "the model context, or pass allow_password_fields=True to override."
            )
        }

    common_params = None
    if comment:
        common_params = {
            "autoCheckout": "true",
            "autoCheckIn": "true",
            "autoComment": comment,
        }

    per_field: list[dict] = []
    for slug, value in parsed.items():
        try:
            kwargs: dict[str, Any] = {"json": {"value": value}}
            if common_params:
                kwargs["params"] = common_params
            session.request("PUT", f"/v1/secrets/{secret_id}/fields/{slug}", **kwargs)
            per_field.append({"slug": slug, "updated": True})
        except Exception as exc:  # pragma: no cover - network failures
            logger.exception("Failed to update field %s on secret %s", slug, secret_id)
            per_field.append({"slug": slug, "updated": False, "error": str(exc)})

    verify: dict = {}
    try:
        verify = session.request("GET", f"/v1/secrets/{secret_id}/summary").json()
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Secret verification failed after field updates")
        verify = {"error": str(exc)}

    return {
        "result": {
            "secret_id": secret_id,
            "fields": per_field,
            "all_updated": all(r.get("updated") for r in per_field),
        },
        "verification": verify,
    }


# --------------------------------------------------------------------------- #
# bulk_user_response                                                          #
# --------------------------------------------------------------------------- #


# Each scenario is an ordered list of (label, path, body-builder).  The body
# builder receives the user_ids list and returns the JSON body for the POST.
def _bulk_user_body(user_ids: list[int]) -> dict:
    return {"data": {"userIds": user_ids}}


_BULK_USER_SCENARIOS: dict[str, list[tuple[str, str]]] = {
    # Compromise response: kill sessions, lock, disable account, strip 2FA so
    # the attacker can't re-enrol.  Order matters: force-logout first to evict
    # active sessions before the account is disabled.
    "compromise": [
        ("force_logout", "/v1/bulk-user-operations/force-logout"),
        ("lock", "/v1/bulk-user-operations/lock"),
        ("disable", "/v1/bulk-user-operations/disable"),
        ("reset_fido2", "/v1/bulk-user-operations/reset-fido2-two-factor"),
        ("reset_totp", "/v1/bulk-user-operations/reset-totp-auth"),
    ],
    # Offboarding: more graceful.  Disable the account and force logout, but
    # keep 2FA factors registered so audit trails remain intact.
    "offboard": [
        ("force_logout", "/v1/bulk-user-operations/force-logout"),
        ("disable", "/v1/bulk-user-operations/disable"),
    ],
    # Restore access after a temporary lockout / IR action.
    "unlock": [
        ("unlock", "/v1/bulk-user-operations/unlock"),
        ("enable", "/v1/bulk-user-operations/enable"),
    ],
    # Re-enable a disabled-but-not-locked account.
    "reenable": [
        ("enable", "/v1/bulk-user-operations/enable"),
    ],
    # Just kick active sessions.
    "force_logout": [
        ("force_logout", "/v1/bulk-user-operations/force-logout"),
    ],
}


def bulk_user_response(
    user_ids: list[int] | str,
    scenario: str,
    comment: str,
    *,
    confirm: bool = False,
) -> dict:
    """Apply an opinionated sequence of bulk user operations.

    .. warning::
        This tool can lock out, disable, or strip 2FA from many users in a
        single call.  It is intended for incident response (e.g. compromised
        accounts), bulk offboarding, or break-glass restoration.  **Always
        verify the user_ids list with the caller before invoking** and
        require an explicit ``confirm=True`` plus a meaningful audit
        ``comment`` referencing the ticket/incident.

    Composes calls to ``POST /v1/bulk-user-operations/*`` endpoints in the
    sequence prescribed by *scenario*.

    Scenarios
    ---------
    ``"compromise"``
        Force-logout → lock → disable → reset FIDO2 → reset TOTP.  Use when
        an account is suspected of compromise and you want the strongest
        possible response.
    ``"offboard"``
        Force-logout → disable.  Less aggressive — keeps 2FA registrations
        so audit trails remain meaningful.
    ``"unlock"``
        Unlock → enable.  Reverses a prior lockout/disable.
    ``"reenable"``
        Enable only.  Use after ``"compromise"`` was applied in error.
    ``"force_logout"``
        Just terminate active sessions.

    Parameters
    ----------
    user_ids:
        List of user identifiers (or JSON string of the same).
    scenario:
        One of the scenario names listed above.
    comment:
        Required audit comment.  Must reference the ticket/incident and
        explain *why* this action is being taken.  An empty comment is
        rejected.
    confirm:
        Must be set to ``True`` to actually run any destructive scenario.
        ``"unlock"``, ``"reenable"`` and ``"force_logout"`` also require
        confirmation, but planning calls (``confirm=False``) return a
        preview of what the tool would do.

    Returns
    -------
    dict
        On preview (``confirm=False``): ``{"preview": {...}}`` with the
        list of steps and target user_ids, no API calls made.
        On execute: ``{"result": {...}, "verification": {...}}`` where
        ``result`` lists per-step API responses and ``verification`` is
        a fresh user listing for the affected ids.
    """

    logger.debug(
        "bulk_user_response(scenario=%s, n_users=%s, confirm=%s)",
        scenario,
        len(user_ids) if hasattr(user_ids, "__len__") else "?",
        confirm,
    )

    if scenario not in _BULK_USER_SCENARIOS:
        return {
            "error": (
                f"Unknown scenario {scenario!r}. "
                f"Valid: {sorted(_BULK_USER_SCENARIOS)}"
            )
        }

    if isinstance(user_ids, str):
        try:
            user_ids = json.loads(user_ids)
        except Exception:
            return {"error": "user_ids must be a list or a JSON-encoded list"}
    if not isinstance(user_ids, list) or not user_ids:
        return {"error": "user_ids must be a non-empty list"}
    try:
        ids = [int(i) for i in user_ids]
    except Exception:
        return {"error": "user_ids must contain integers"}

    if not isinstance(comment, str) or not comment.strip():
        return {
            "error": (
                "comment is required and must explain why this bulk action "
                "is being taken (include ticket/incident reference)"
            )
        }

    steps = _BULK_USER_SCENARIOS[scenario]

    if not confirm:
        return {
            "preview": {
                "scenario": scenario,
                "user_ids": ids,
                "user_count": len(ids),
                "steps": [label for label, _ in steps],
                "comment": comment,
                "note": (
                    "No API calls were made. Pass confirm=True to execute. "
                    "Verify the user_ids list with a human before confirming."
                ),
            }
        }

    session = SessionManager.get()
    body = _bulk_user_body(ids)

    per_step: list[dict] = []
    for label, path in steps:
        try:
            resp = session.request("POST", path, json=body)
            payload = resp.json() if resp.content else {"success": True}
            per_step.append({"step": label, "ok": True, "response": payload})
        except Exception as exc:  # pragma: no cover - network failures
            logger.exception("bulk_user_response step %s failed", label)
            per_step.append({"step": label, "ok": False, "error": str(exc)})

    # Verification: re-fetch each affected user record so the caller can
    # confirm enabled/lockedOut/loginFailures fields reflect the change.
    verification: list[dict] = []
    for uid in ids:
        try:
            user = session.request("GET", f"/v1/users/{uid}").json()
            verification.append(
                {
                    "userId": uid,
                    "enabled": user.get("enabled"),
                    "isLockedOut": user.get("isLockedOut"),
                    "lastLogin": user.get("lastLogin"),
                }
            )
        except Exception as exc:  # pragma: no cover - network failures
            verification.append({"userId": uid, "error": str(exc)})

    return {
        "result": {
            "scenario": scenario,
            "user_ids": ids,
            "comment": comment,
            "steps": per_step,
            "all_ok": all(s["ok"] for s in per_step),
        },
        "verification": verification,
    }


TOOLS = [
    ("search", search),
    ("fetch", fetch),
    ("run_report", run_report),
    ("list_example_reports", list_example_reports),
    ("get_secret", get_secret),
    ("reveal_secret_field", reveal_secret_field),
    ("get_folder", get_folder),
    ("role_management", role_management),
    ("user_role_management", user_role_management),
    ("group_management", group_management),
    ("user_group_management", user_group_management),
    ("group_role_management", group_role_management),
    ("folder_management", folder_management),
    ("health_check", health_check),
    ("search_secrets", search_secrets),
    ("search_folders", search_folders),
    ("get_secret_environment_variable", get_secret_environment_variable),
    ("check_secret_template", check_secret_template),
    ("check_secret_template_field", check_secret_template_field),
    ("handle_access_request", handle_access_request),
    ("get_pending_access_requests", get_pending_access_requests),
    ("get_inbox_messages", get_inbox_messages),
    ("mark_inbox_messages_read", mark_inbox_messages_read),
    ("get_secret_template_field", get_secret_template_field),
    (
        "create_secret_with_generated_password",
        create_secret_with_generated_password,
    ),
    (
        "set_secret_field_environment_variable",
        set_secret_field_environment_variable,
    ),
    ("update_secret_generated_password", update_secret_generated_password),
    # New in v1.0.0: secret editing flow and bulk user incident response.
    ("update_secret_fields", update_secret_fields),
    ("bulk_user_response", bulk_user_response),
]


def load_enabled_tools(path: str | Path) -> set[str]:
    """Load enabled tool names from a JSON config file."""
    file = Path(path)
    if not file.exists():  # pragma: no cover - optional config
        return set()
    try:
        data = json.loads(file.read_text())
        names = data.get("enabled_tools", [])
        if not isinstance(names, list):  # pragma: no cover - defensive
            return set()
        return {str(n) for n in names}
    except Exception:  # pragma: no cover - invalid file
        logger.exception("Failed to load tool config from %s", file)
        return set()


def register(mcp: Any, enabled: Iterable[str] | None = None) -> None:
    """Register reporting tools on the given MCP server."""
    enabled_set = set(enabled or [])
    if not enabled_set:
        enabled_set = {name for name, _ in TOOLS}
    if _reveal_mode() == "disabled":
        # Off unless explicitly enabled: don't offer a tool that always refuses.
        enabled_set.discard("reveal_secret_field")
    for name, func in TOOLS:
        if name in enabled_set:
            mcp.tool(**tool_metadata(name))(guard_tool(func))
