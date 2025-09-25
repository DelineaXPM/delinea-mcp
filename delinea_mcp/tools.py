"""Reporting helper functions and MCP tools."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

from delinea_api import DelineaSession

from . import constants

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
    if delinea and getattr(delinea, "base_url", None):
        base = delinea.base_url
    if not base:
        return ""
    return base.rstrip("/") + "/api"


delinea: DelineaSession | None = None


def _require_session() -> DelineaSession:
    """Return the active :class:`DelineaSession` or raise an error."""
    if delinea is None:  # pragma: no cover
        raise RuntimeError("Delinea session not initialised")  # pragma: no cover
    return delinea


def _parse_json_data(data: dict | str | None) -> dict | None:
    """Return a dict from ``data`` when given a JSON string."""
    if isinstance(data, str):
        try:
            return json.loads(data)
        except Exception:
            logger.exception("Failed to parse JSON string")
            raise ValueError("Invalid JSON data")
    return data


def init(session: DelineaSession) -> None:
    """Store the session for use by reporting helpers."""
    global delinea
    delinea = session
    logger.debug("Tools session initialised")


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
    session = _require_session()
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
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to create report '%s'", report_name)
        raise RuntimeError(f"Failed to create report '{report_name}': {exc}")


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
    session = _require_session()
    try:
        response = session.request(
            "POST",
            "/v1/reports/execute",
            json={"id": report_id, "useDefaultParameters": True},
        )
        return response.json()
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to execute report %s", report_id)
        raise RuntimeError(f"Failed to execute report {report_id}: {exc}")


def run_report(sql_query: str, report_name: str | None = None) -> dict:
    """Create and execute a temporary report and return its result rows.

    Parameters
    ----------
    sql_query:
        The SQL query to run.
    report_name:
        Optional name for the temporary report.

    Returns
    -------
    dict
        Dictionary containing ``columns`` and ``rows`` from the executed report
        or an ``error`` key on failure.
    """
    logger.debug("run_report(%s)", sql_query)
    session = _require_session()
    name = report_name or "MCP Generated Report"
    try:
        report_id = create_report(name, sql_query)
        result = execute_report(report_id)
    except Exception as exc:
        logger.exception("Failed to run report '%s'", name)
        return {"error": f"Failed to run report '{name}': {exc}"}

    try:
        session.request("DELETE", f"/v1/reports/{report_id}")
    except Exception:
        logger.exception("Failed to delete report %s", report_id)

    return {"columns": result.get("columns", []), "rows": result.get("rows", [])}


def generate_sql_query(user_query: str) -> str:
    """Generate a SQL query from natural language using Azure OpenAI.

    Parameters
    ----------
    user_query:
        Free form description of the desired data.

    Returns
    -------
    str
        SQL statement or an error message if generation fails.
    """
    logger.debug("generate_sql_query(%s)", user_query)
    # Import OpenAI lazily so tests don't require the package unless this
    # function is invoked.
    import openai

    azure_endpoint = _cfg_or_env("AZURE_OPENAI_ENDPOINT")
    azure_key = os.getenv("AZURE_OPENAI_KEY")
    deployment_name = _cfg_or_env("AZURE_OPENAI_DEPLOYMENT")

    if not azure_endpoint or not azure_key or not deployment_name:
        return "Error: Azure OpenAI environment variables are not set"

    openai.api_type = "azure"
    openai.api_base = azure_endpoint
    openai.api_key = azure_key
    openai.api_version = "2023-05-15"

    system_message = (
        "You are a SQL query generator for Delinea Secret Server. "
        "Use the following information about tables, example queries and special "
        "fields to generate the SQL.\n\n"
        f"Tables and Columns:\n{constants.TABLES_AND_COLUMNS}\n\n"
        f"Example Queries:\n{constants.EXAMPLE_QUERIES_TEXT}\n\n"
        f"Special Fields:\n{constants.SPECIAL_FIELDS}"
        "\nGenerate only the SQL without markdown formatting."
    )

    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": f"Generate a SQL query for: {user_query}"},
    ]

    try:
        response = openai.ChatCompletion.create(
            model=deployment_name,
            messages=messages,
            temperature=0.7,
            max_tokens=500,
            n=1,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to generate SQL")
        return f"Error generating SQL: {exc}"


def check_secret_template(template_id: int) -> dict:  # pragma: no cover
    """Returns the template details for the given ID."""
    logger.debug("check_secret_template(%s)", template_id)
    session = _require_session()
    try:
        return session.request("GET", f"/v1/secret-templates/{template_id}").json()
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to retrieve secret template %s", template_id)
        return {"error": f"Failed to retrieve secret template {template_id}: {exc}"}


def get_secret_environment_variable(
    secret_id: int, environment: str
) -> str:  # pragma: no cover
    """Return shell code to fetch a secret and store it in environment variables.

    Parameters
    ----------
    secret_id:
        Identifier of the secret to retrieve.
    environment:
        Target shell environment. Supported values are ``"bash"``,
        ``"powershell"`` and ``"cmd"``.

    Returns
    -------
    str
        Script snippet that reads the secret via ``curl`` and exports it as
        ``SECRET_PASSWORD_<id>`` and ``SECRET_USERNAME_<id>``.
    """

    session = _require_session()
    url = f"{session.base_url}/api/v2/secrets/{secret_id}"
    access_token = session.token
    if environment.lower() == "bash":
        return (
            f'export SECRET_PASSWORD_{secret_id}="$(curl -H "Authorization: Bearer {access_token}" {url} | jq -r ".items[] | select(.fieldName == "Password") | .itemValue")"'
            f'export SECRET_USERNAME_{secret_id}="$(curl -H "Authorization: Bearer {access_token}" {url} | jq -r ".items[] | select(.fieldName == "Username") | .itemValue")"'
        )
    elif environment.lower() == "powershell":
        return (
            f'$headers = @{{"Authorization" = "Bearer {access_token}"}}\n'
            f'$response = Invoke-RestMethod -Uri "{url}" -Headers $headers\n'
            f'$passwordItem = $response.items | Where-Object {{ $_.fieldName -eq "Password" }}\n'
            f'$usernameItem = $response.items | Where-Object {{ $_.fieldName -eq "Username" }}\n'
            f"$env:SECRET_PASSWORD_{secret_id} = $passwordItem.itemValue\n"
            f"$env:SECRET_USERNAME_{secret_id} = $usernameItem.itemValue"
        )
    elif environment.lower() == "cmd":
        return (
            f'for /f "delims=" %p in (\'curl -H "Authorization: Bearer {access_token}" {url} ^| findstr /C:"fieldName=Password;" ^| findstr /C:"itemValue=" ^| head -n 1 ^| sed -E "s/.*itemValue=([^;]*);.*/\\1/") do set SECRET_PASSWORD_{secret_id}=%p\n'
            f'for /f "delims=" %u in (\'curl -H "Authorization: Bearer {access_token}" {url} ^| findstr /C:"fieldName=Username;" ^| findstr /C:"itemValue=" ^| head -n 1 ^| sed -E "s/.*itemValue=([^;]*);.*/\\1/") do set SECRET_USERNAME_{secret_id}=%u'
        )
    else:
        raise ValueError(f"Unsupported environment: {environment}")


def ai_generate_and_run_report(description: str) -> dict:
    """Generate SQL from a description, run it, and return the results."""
    logger.debug("ai_generate_and_run_report(%s)", description)
    sql = generate_sql_query(description)
    if sql.startswith("Error"):
        return {"error": sql}

    result = run_report(sql, report_name=f"AI Generated: {int(time.time())}")
    if "error" in result:
        return result

    result["generated_sql"] = sql
    return result


def list_example_reports() -> str:
    """Return sample queries, table information and special fields."""
    logger.debug("list_example_reports")
    return (
        constants.EXAMPLE_QUERIES_TEXT
        + "\n\nTables and Columns:\n"
        + constants.TABLES_AND_COLUMNS
        + "\n\nSpecial Fields:\n"
        + constants.SPECIAL_FIELDS
    )


def get_secret(id: int, summary: bool = False) -> dict:
    """Retrieve a secret or its summary. Due to Secret safety concerns
    before retrieval the user must explicitly confirm they want the full
    secret and be warned it'll exist in the session logs. otherwise only
    use ``summary=True``, which is safe.

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
    session = _require_session()
    path = f"/v1/secrets/{id}/summary" if summary else f"/v2/secrets/{id}"
    try:
        return session.request("GET", path).json()
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to retrieve secret %s", id)
        return {"error": f"Failed to retrieve secret {id}: {exc}"}


def get_folder(id: int) -> dict:
    """Return folder metadata and children for the given folder ID.

    Parameters
    ----------
    id:
        Identifier of the folder to fetch.

    Returns
    -------
    dict
        Folder metadata including children or an ``error`` message.
    """
    logger.debug("get_folder(%s)", id)
    session = _require_session()
    params = {"getAllChildren": "true"}
    try:
        return session.request("GET", f"/v1/folders/{id}", params=params).json()
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to retrieve folder %s", id)
        return {"error": f"Failed to retrieve folder {id}: {exc}"}


def search_users(query: str) -> dict:
    """Search active users by text.

    Parameters
    ----------
    query:
        Text to search for in usernames or display names.

    Returns
    -------
    dict
        Raw search results as returned by the API.
    """
    logger.debug("search_users(%s)", query)
    session = _require_session()
    try:
        return session.request(
            "GET", "/v1/users", params={"filter.searchText": query}
        ).json()
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to search users %s", query)
        return {"error": f"Failed to search users '{query}': {exc}"}


def search_secrets(query: str, lookup: bool = False) -> dict:
    """Search or look up secrets.

    Parameters
    ----------
    query:
        Search text.
    lookup:
        If ``True``, perform a metadata lookup instead of a full search.

    Returns
    -------
    dict
        JSON response from the appropriate search endpoint.
    """
    logger.debug("search_secrets(%s, lookup=%s)", query, lookup)
    session = _require_session()
    path = "/v1/secrets/lookup" if lookup else "/v2/secrets"
    try:
        return session.request("GET", path, params={"filter.searchText": query}).json()
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to search secrets %s", query)
        return {"error": f"Failed to search secrets '{query}': {exc}"}


def search_folders(query: str, lookup: bool = False) -> dict:
    """Search or look up folders.

    Parameters
    ----------
    query:
        Text to search for in folder names.
    lookup:
        If ``True``, query the ``/lookup`` endpoint for metadata only.

    Returns
    -------
    dict
        JSON payload from the search call.
    """
    logger.debug("search_folders(%s, lookup=%s)", query, lookup)
    session = _require_session()
    path = "/v1/folders/lookup" if lookup else "/v1/folders"
    try:
        return session.request("GET", path, params={"filter.searchText": query}).json()
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
    session = _require_session()
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
    session = _require_session()
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
    session = _require_session()
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
    session = _require_session()
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
    session = _require_session()
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
    session = _require_session()
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


def user_management(
    action: str,
    user_id: int | None = None,
    data: dict | None = None,
    *,
    skip: int = 0,
    take: int = 20,
    is_exporting: bool = False,
) -> dict:
    """Manage users via a single helper.

    Parameters
    ----------
    action:
        Operation to perform: ``"get"``, ``"create"``, ``"update"``, ``"delete"``,
        ``"list_sessions"``, ``"reset_2fa"``, ``"reset_password"`` or ``"lock_out"``.
    user_id:
        Target user identifier. Required for all actions except ``"create"`` and
        ``"list_sessions"``.
    data:
        JSON body for ``"create"``, ``"update"`` and ``"reset_password"``.
    skip, take:
        Pagination controls for ``"list_sessions"``.
    is_exporting:
        Include the ``isExporting`` flag when listing sessions.

    When ``action`` is ``"create"``, ``data`` must include the required keys
    ``userName``, ``password`` and ``displayName``. Optional keys such as
    ``adGuid``, ``domainId``, ``duoTwoFactor``, ``emailAddress``, ``enabled``,
    ``fido2TwoFactor``, ``isApplicationAccount``, ``oathTwoFactor``,
    ``radiusTwoFactor``, ``radiusUserName``, ``twoFactor`` and
    ``unixAuthenticationMethod`` may also be supplied. Password must adhere
    to password security rules otherwise a 400 failure may occur.
    When ``action`` is ``"update"``, you need to do a get first, update the
    relevant fields and post everything back.

    For ``"create"``, ``"update"`` and ``"delete"`` actions the function
    performs an additional ``GET`` request after the operation to verify the
    result. The returned dictionary contains two keys: ``result`` with the
    original API response and ``verification`` with the data retrieved by the
    follow-up ``GET``.

    Returns
    -------
    dict
        Dictionary with ``result`` from the write action and ``verification``
        from the subsequent ``GET``.

    Examples
    --------
    >>> user_management("get", user_id=10)
    >>> user_management("create", data={"username": "alice"})
    """

    logger.debug(
        "user_management(action=%s, user_id=%s, data=%s)", action, user_id, data
    )
    session = _require_session()

    data = _parse_json_data(data)

    try:
        if action == "get":
            if user_id is None:
                raise ValueError("user_id required for get")
            return session.request("GET", f"/v1/users/{user_id}").json()
        if action == "create":
            result = session.request("POST", "/v1/users", json=data or {}).json()
            user_id = result.get("id") or result.get("userId")
            verify = {}
            if user_id is not None:
                try:
                    verify = session.request("GET", f"/v1/users/{user_id}").json()
                except Exception as exc:  # pragma: no cover - network failures
                    logger.exception("User verification failed after create")
                    verify = {"error": str(exc)}
            return {"result": result, "verification": verify}
        if action == "update":
            if user_id is None or data is None:
                raise ValueError("user_id and data required for update")
            result = session.request("PUT", f"/v1/users/{user_id}", json=data).json()
            verify = {}
            try:
                verify = session.request("GET", f"/v1/users/{user_id}").json()
            except Exception as exc:  # pragma: no cover - network failures
                logger.exception("User verification failed after update")
                verify = {"error": str(exc)}
            return {"result": result, "verification": verify}
        if action == "delete":
            if user_id is None:
                raise ValueError("user_id required for delete")
            result = session.request("DELETE", f"/v1/users/{user_id}").json()
            verify = {}
            try:
                verify = session.request("GET", f"/v1/users/{user_id}").json()
            except Exception as exc:  # pragma: no cover - network failures
                verify = {"error": str(exc)}
            return {"result": result, "verification": verify}
        if action == "list_sessions":
            params = {"skip": skip, "take": take}
            if is_exporting:
                params["isExporting"] = True
            return session.request("GET", "/v1/users/sessions", params=params).json()
        if action == "reset_2fa":
            if user_id is None:
                raise ValueError("user_id required for reset_2fa")
            return session.request(
                "POST", f"/v1/users/{user_id}/reset-two-factor", json=data or {}
            ).json()
        if action == "reset_password":
            if user_id is None or data is None:
                raise ValueError("user_id and data required for reset_password")
            return session.request(
                "POST", f"/v1/users/{user_id}/password-reset", json=data
            ).json()
        if action == "lock_out":
            if user_id is None:
                raise ValueError("user_id required for lock_out")
            return session.request(
                "POST", f"/v1/users/{user_id}/lock-out", json=data or {}
            ).json()
        raise ValueError(f"Unknown action: {action}")
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("User management action failed")
        return {"error": str(exc)}


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
    session = _require_session()
    data = _parse_json_data(data)

    try:
        if action == "list":
            return session.request("GET", "/v1/roles", params=params or {}).json()
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
    session = _require_session()

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
    session = _require_session()
    data = _parse_json_data(data)

    try:
        if action == "get":
            if group_id is None:
                raise ValueError("group_id required for get")
            return session.request("GET", f"/v1/groups/{group_id}").json()
        if action == "list":
            return session.request("GET", "/v1/groups", params=params or {}).json()
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
    session = _require_session()

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
    session = _require_session()

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
        JSON body used with ``"create"`` and ``"update"``.
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
    session = _require_session()
    data = _parse_json_data(data)

    try:
        if action == "get":
            if folder_id is None:
                raise ValueError("folder_id required for get")
            return session.request(
                "GET", f"/v1/folders/{folder_id}", params={"getAllChildren": "true"}
            ).json()
        if action == "list":
            return session.request("GET", "/v1/folders", params=params or {}).json()
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
    session = _require_session()
    try:
        return session.request("GET", "/v1/healthcheck", params={"noBus": True}).json()
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to call health check")
        return {"error": f"Failed to perform health check: {exc}"}


def search(query: str) -> Dict[str, List[Dict[str, Any]]]:
    """Return search results in MCP format.

    Parameters
    ----------
    query:
        Text to search across the enabled object types.

    Returns
    -------
    list[dict]
        Each result object contains ``id``, ``title``, ``text`` and ``url`` as
        defined by the MCP specification.
    """
    logger.debug("search(%s)", query)
    mapping = {
        "secret": search_secrets,
        "user": search_users,
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


def fetch(id: str) -> Dict[str, Any]:
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
        raise ValueError("identifier must be in '<type>/<id>' format")
    kind, obj_id = identifier.split("/", 1)
    kind = kind.lower().rstrip("s")
    if kind not in _FETCH_ALLOWED:
        raise ValueError(f"fetch for {kind} not enabled")

    mapping = {
        "secret": lambda i: get_secret(int(i)),
        "user": lambda i: user_management("get", user_id=int(i)),
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


TOOLS = [
    ("search", search),
    ("fetch", fetch),
    ("run_report", run_report),
    ("ai_generate_and_run_report", ai_generate_and_run_report),
    ("list_example_reports", list_example_reports),
    ("get_secret", get_secret),
    ("get_folder", get_folder),
    ("user_management", user_management),
    ("role_management", role_management),
    ("user_role_management", user_role_management),
    ("group_management", group_management),
    ("user_group_management", user_group_management),
    ("group_role_management", group_role_management),
    ("folder_management", folder_management),
    ("health_check", health_check),
    ("search_users", search_users),
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
]


def _ai_env_configured() -> bool:
    """Return True if Azure OpenAI configuration is available."""
    return bool(
        _cfg_or_env("AZURE_OPENAI_ENDPOINT")
        and os.getenv("AZURE_OPENAI_KEY")
        and _cfg_or_env("AZURE_OPENAI_DEPLOYMENT")
    )


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
    """Register reporting tools on the given FastMCP server."""
    enabled_set = set(enabled or [])
    if not enabled_set:
        enabled_set = {name for name, _ in TOOLS}
    if not _ai_env_configured():
        enabled_set.discard("ai_generate_and_run_report")
    for name, func in TOOLS:
        if name in enabled_set:
            mcp.tool()(func)
