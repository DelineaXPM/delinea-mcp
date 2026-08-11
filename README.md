# DelineaMCP

**MCP server for the Delinea Secret Server and Platform APIs**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## News

- **11 Aug 2026** — MCP Protocol v2 (spec revision 2026-07-28, streamable HTTP)
  and experimental StrongDM API support are here — see the
  [release notes](CHANGELOG.md).
- **11 Aug 2026** — We're the original providers of the "no secret visibility
  to the LLM" vault use case — beware of copycats ;)

---

## Features

- Automatic authentication against Secret Server
- Extensive Secret Server tool set for managing folders, secrets, users, groups and roles.
  Includes inbox and access request helpers and coding agent utilities.
- ChatGPT compatibility tools (`search` and `fetch`) for controlled AI interactions.
- Optional Delinea Platform user management tools
- Optional **experimental** StrongDM (SDM) tools — access grants, entitlement
  audits, user/role lifecycle, health and activity reports (see
  [docs/strongdm.md](docs/strongdm.md); install with
  `pip install "delinea-mcp[strongdm]"`)
- Streamable HTTP (`/mcp`), legacy Server-Sent Events (`/mcp/sse`) and STDIO transports
- OAuth 2.0 with dynamic client registration per the MCP specification
- TLS support for secure connections
- Ready-to-run Docker image and development server entry point
- Tested with ChatGPT, Claude Desktop, remote Claude connector, VSCode Copilot and openwebui

## Installation

> [!NOTE]
>
> This project uses `uv` (https://github.com/astral-sh/uv), but if you prefer to run commands without this, you can do `pip` and `venv` commands as usual if desired.

- [Install Uv](https://docs.astral.sh/uv/getting-started/installation/)
- Initialize project: `uv pip sync requirements.txt`
- Use `uv run server.py --config config.json`

## Configuration

Secrets such as passwords continue to come from environment variables.
Provide `DELINEA_PASSWORD` in your shell environment.
Optional features rely on additional variables such as `AZURE_OPENAI_KEY` or `PLATFORM_SERVICE_PASSWORD`.

Non-secret parameters belong in `config.json`:

```json
{
  "delinea_username": "<username>",
  "delinea_base_url": "https://your-secret-server/SecretServer",
  "platform_hostname": "<tenant>.secureplatform.io",
  "platform_service_account": "<service_account>",
  "platform_tenant_id": "<tenant_id>",
  "azure_openai_endpoint": "https://example.openai.azure.com/",
  "azure_openai_deployment": "<deployment_name>",
  "auth_mode": "none",
  "transport_mode": "stdio",
  "chatgpt_disable_scope_checks": false,
  "port": 8000,
  "debug": false,
  "external_hostname": null,
  "ssl_keyfile": null,
  "ssl_certfile": null,
  "registration_psk": null,
  "jwt_key_path": ".cache/jwt.json",
  "oauth_db_path": ".cache/oauth.db",
  "enabled_tools": []
}
```

For Secret Server Cloud simply use the cloud URL without `/SecretServer`.
Specify `ssl_keyfile` and `ssl_certfile` to enable HTTPS.
For Let's Encrypt, use the `privkey.pem` and `fullchain.pem` files.

The configuration file supports the following keys:

- **delinea_username** - Secret Server username. Must be a programmatic user with permission to do the tasks you want.
- **delinea_base_url** - Base URL of your Secret Server instance.
- **platform_hostname** - Platform tenant hostname (enables Platform tools).
- **platform_service_account** - Service account used with the Platform API.
- **platform_tenant_id** - Tenant ID for Platform API requests.
- **strongdm_api_host** - StrongDM control plane (default `app.strongdm.com:443`;
  UK/EU variants available). Credentials come from `SDM_API_ACCESS_KEY` /
  `SDM_API_SECRET_KEY` env vars; see [docs/strongdm.md](docs/strongdm.md).
- **azure_openai_endpoint** - Azure OpenAI endpoint. Only if you want the automatic report generation (most agents can generate their own report SQL so don't enable unless you need it).
- **azure_openai_deployment** - Deployment name for Azure OpenAI.
- **auth_mode** - Authentication mode (`none` or `oauth`). OAuth obviously doesn't work with stdio transport.
- **transport_mode** - `stdio` for command line or `sse` for HTTP. In `sse`
  mode the server exposes both the streamable HTTP endpoint at `/mcp`
  (current MCP transport, serves protocol revisions 2024-11-05 through
  2026-07-28) and the legacy HTTP+SSE endpoints at `/mcp/sse` + `/messages/`.
- **streamable_http_stateless** - default `true`; run `/mcp` without server-side
  sessions (recommended for remote connectors). Set `false` to enable
  session-based operation with the standalone GET stream.
- **streamable_http_json_response** - default `true`; respond with plain JSON
  instead of SSE-framed responses on `/mcp`.
- **chatgpt_disable_scope_checks** - Skip scope validation on ChatGPT requests. Enable only if you encounter problems connecting to ChatGPT.
- **port** - Port for the HTTP server in `sse` mode.
- **debug** - Enable verbose logging.
- **external_hostname** - Hostname used when constructing OAuth token audiences. Don't add HTTP(S) prefix or port.
- **ssl_keyfile** - Path to the SSL key for HTTPS. (eg `privkey.pem`)
- **ssl_certfile** - Path to the SSL certificate for HTTPS. (eg `fullchain.pem`)
- **registration_psk** - Pre-shared key required to register OAuth clients. You will need to type in this secret in your browser to approve OAuth connections.
- **jwt_key_path** - Location of the RSA key pair used for OAuth tokens. Defaults to `.cache/jwt.json`. autogenerated if doesn't exist.
- **oauth_db_path** - Path to the OAuth database file. Defaults to `.cache/oauth.db`. autogenerated if doesn't exist.
- **enabled_tools** - List of tool names to register. An empty list enables all tools. It is highly recommended to enable tools selectively per use case or task. See `docs/` folder for some examples.
- **search_objects** - Allowed object types for the `search` tool.
  Defaults to `["secret"]` but can include `user`, `folder`, `group` and `role`.
- **fetch_objects** - Allowed object types for the `fetch` tool.
  Defaults to `["secret"]` but can include the same values as `search_objects`.

## Running the Server

Start the server locally in development mode:

```bash
python server.py
```

On startup the server requests a bearer token and stores it for subsequent API requests.
This project will be expanded to integrate further with the Secret Server API.

## MCP Tools

The server exposes MCP tools for Secret Server, the Delinea Platform
identity directory, and (optionally) StrongDM. Every tool publishes
behaviour annotations (read-only/destructive hints) via `tools/list`.

### ChatGPT / deep-research compatibility

- `search(query)` - unified search returning `{id, title, url}` results; object
  types are limited by the `search_objects` config key (default: secrets only).
- `fetch(id)` - retrieve a single object surfaced by `search`; limited by
  `fetch_objects`.

### Secret Server

- `run_report(sql_query, report_name=None)` - create and execute a temporary report.
- `ai_generate_and_run_report(description)` - generate SQL using Azure OpenAI and run it.
  Requires the Azure OpenAI variables.
- `list_example_reports()` - list sample queries and table information.
- `get_secret(id, summary=False)` - retrieve a secret or summary details.
- `get_folder(id)` - fetch folder metadata and children.
- `search_secrets(query, lookup=False)` - search or look up secrets.
- `search_folders(query, lookup=False)` - search or look up folders.
- `get_secret_environment_variable(secret_id, environment)` - output a script for fetching secret credentials in the specified shell.
- `check_secret_template(template_id)` - fetch secret template details.
- `check_secret_template_field(template_id, field_id)` - check if a template contains a field.
- `get_secret_template_field(field_id)` - retrieve details about a specific secret template field by ID.
- `handle_access_request(request_id, status, response_comment, start_date=None, expiration_date=None)` - approve or deny an access request.
- `get_pending_access_requests()` - list pending access requests.
- `get_inbox_messages(read_status_filter=None, take=20, skip=0)` - retrieve inbox messages.
- `mark_inbox_messages_read(message_ids, read=True)` - mark messages as read or unread.
- `create_secret_with_generated_password(name, secret_template_id, password_field_id, items, folder_id=None, site_id=None, comment=None)` -
  create a secret whose password is generated server-side; only sanitized
  metadata is returned, the value never reaches the model.
- `update_secret_generated_password(secret_id, field_slug, password_field_id, comment=None)` -
  rotate a secret's password server-side without surfacing the value.
- `update_secret_fields(secret_id, field_updates, comment=None, allow_password_fields=False)` -
  read-template → mutate non-password fields → verify flow; refuses
  password-marked fields unless explicitly allowed.
- `set_secret_field_environment_variable(secret_id, field_slug, environment, source="stdin", comment=None)` -
  emit a shell script (bash/powershell/cmd) that reads a value locally and
  pushes it into the secret field, so the value bypasses the model entirely.
- `bulk_user_response(user_ids, scenario, comment, confirm=False)` - opinionated
  incident combinator over the bulk-user operations API. Scenarios:
  `compromise`, `offboard`, `unlock`, `reenable`, `force_logout`; requires
  `confirm=True` plus a non-empty audit comment, and previews when unconfirmed.
- `role_management(action, role_id=None, data=None, params=None)` - manage roles.
  `action` may be `list`, `get`, `create` or `update`.
  Pass optional query parameters with `params` when listing roles.
  Example: `role_management("update", role_id=3, data={"name": "New Role"})`.
- `user_role_management(action, user_id, role_ids=None)` - assign or remove roles from a user.
  `action` is `get`, `add` or `remove` and `role_ids` is a list of role identifiers for add/remove operations.
- `group_management(action, group_id=None, data=None, params=None)` - handle groups.
  `action` may be `get`, `list`, `create` or `delete`.
  Provide `group_id` for get/delete and `data` when creating a group.
- `folder_management(action, folder_id=None, data=None, params=None)` - manage folders.
  `action` may be `get`, `list`, `create`, `update` or `delete`.
  Provide `folder_id` for get, update or delete and supply `data` when creating or updating a folder.
- `user_group_management(action, user_id, group_ids=None)` - manage group membership for a user.
  `action` is `get`, `add` or `remove`.
  Supply a list of `group_ids` when adding or removing membership.
- `group_role_management(action, group_id, role_ids=None)` - control roles on a group.
  Use `list`, `add` or `remove` actions.
  Provide `role_ids` when adding or removing.
- `health_check()` - query the Secret Server health check endpoint and return the current service status.

### Delinea Platform users and roles

Since v1.0.0 the canonical user tools target the Delinea Platform identity
directory (requires `platform_hostname` + `PLATFORM_SERVICE_*` credentials;
without them the tools return guidance instead of failing):

- `user_management(action, user_id=None, data=None, username=None)` - Platform
  user CRUD. `action` accepts `get`, `create`, `update`, `delete` or `search`.
- `search_users(query)` - search the Platform user directory.
- `platform_role_management(action, role_id=None, data=None, page_size=100, query="%")` -
  Platform role CRUD (`list`, `get`, `create`, `update`, `delete`); role
  mutations are discovery-driven and return guidance on tenants whose API
  scope doesn't expose them.
- `platform_user_role_management(action, role_id, user_principals=None)` -
  `list`, `add` or `remove` users on a Platform role.
- `platform_user_management(...)` - deprecated alias of `user_management`.

### Secret Server local users (legacy)

For SS-only deployments without Platform configured:

- `secretserver_local_user_management(action, user_id=None, data=None, skip=0, take=20, is_exporting=False)` -
  the pre-v1.0.0 Secret Server user operations: `get`, `create`, `update`,
  `delete`, `list_sessions`, `reset_2fa`, `reset_password`, `lock_out`.
  Example: `secretserver_local_user_management("reset_password", user_id=42, data={"newPassword": "Pa$$w0rd"})`.
- `search_secretserver_local_users(query)` - search Secret Server's local user store.

### StrongDM tools (optional, experimental)

**Experimental**: the StrongDM backend has not yet been verified against a
live SDM organization (unit-tested against the SDK surface only). Expect
rough edges and report issues. Installed via the `strongdm` extra; see
[docs/strongdm.md](docs/strongdm.md) for the full guide. `sdm_search`, `sdm_audit_access`, `sdm_grant_access`
(time-boxed just-in-time or standing grants), `sdm_revoke_access`,
`sdm_user_management` (onboard/offboard flows), `sdm_role_management`,
`sdm_resource_health`, `sdm_access_requests`, `sdm_activity_report`,
`sdm_network_status`. Destructive actions are confirm-gated with audit
comments; ambiguous name matches return candidates without mutating.

Use the server configuration variables described above to authenticate.
The AI tool is automatically disabled if the Azure OpenAI variables are missing.
Only the tool names listed in `config.json` will be registered.
An empty list enables every tool.

## Use Cases

The documentation covers several workflows for connecting tools to the server:

- [ChatGPT Custom Connector](docs/chatgpt-connector.md)
- [Claude Desktop](docs/claude-desktop.md)
- [Remote Claude Connector](docs/claude-remote-connector.md)
- [openwebui for Administration](docs/openwebui-admin.md)
- [VSCode Copilot](docs/vscode-copilot.md)

## Docker Quickstart

A `Dockerfile` is provided for running the MCP server without installing Python dependencies locally.

1. Build the image:

```bash
docker build -t dev.local/delinea-mcp:latest .
```

2. Run the server (pass your credentials via environment variables):

```bash
docker run --rm -p 8000:8000 \
  -e DELINEA_PASSWORD=<password> \
  -e PLATFORM_SERVICE_PASSWORD=<password> \
  -e DELINEA_DEBUG=1 \
  -e AZURE_OPENAI_KEY=<your-key-or-appropriate-token> \
  -v $(pwd)/config.json:/app/config.json:ro \
  -v mcp-data:/app/data \
  dev.local/delinea-mcp:latest
```

Populate `config.json` with your usernames and URLs as shown above.

The container stores `oauth.db` and `jwt.json` in `/app/data`.
Mount a volume (shown as `mcp-data` above) so these files and any HTTPS certificates persist between runs.

Replace `<https://your-secret-server/SecretServer>` with the base URL of your Secret Server instance to avoid connection errors.

The server will start on port `8000` by default using `python server.py`.
Set the `port` option in `config.json` to override the default.
Enable `debug: true` to log all incoming HTTP requests.

## Example Scripts

The `manual_secret_request.py` script shows how to retrieve an OAuth token for a specific secret ID:

```bash
python scripts/manual_secret_request.py <Secret_ID>
```

Set the environment variables `SECRET_USERNAME_<id>` and `SECRET_PASSWORD_<id>` for the secret before running the script.
Optionally set `DELINEA_BASE_URL` to override the default `https://localhost/SecretServer`.

## Running Tests

Run the unit tests with coverage (CI enforces a minimum of 70%):

```bash
pip install -r requirements.txt
coverage run -m pytest -q
coverage report --omit "tests/*"
```

### Live Testing

Some integration tests require valid credentials.
Set the following environment variables and the optional `LIVE_SECRET_ID` before running the suite:

```bash
export DELINEA_PASSWORD=<password>
# Optional secret used by tests/test_live.py
export LIVE_SECRET_ID=<id>
export SECRET_USERNAME_<id>=<secret_username>
export SECRET_PASSWORD_<id>=<secret_password>
```

When these variables are present the live tests will perform real API requests.

## Production Deployment

Dependencies are pinned in `requirements.txt` and releases are tagged using [Semantic Versioning](https://semver.org).
Build the Docker image from a tagged commit and deploy it to your production environment, passing the required environment variables (`DELINEA_USERNAME`, `DELINEA_PASSWORD`, optionally `DELINEA_BASE_URL`).
Optional features rely on additional variables:

- `PLATFORM_SERVICE_PASSWORD` along with `PLATFORM_HOSTNAME`, `PLATFORM_SERVICE_ACCOUNT`, and `PLATFORM_TENANT_ID` enables the user management tools.
- `AZURE_OPENAI_KEY` together with `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT` enables the AI report generation helper.
- `SDM_API_ACCESS_KEY` and `SDM_API_SECRET_KEY` enable the experimental StrongDM tools (requires the `strongdm` extra; see [docs/strongdm.md](docs/strongdm.md)).

When running with OAuth or SSE transport you may need to provide `registration_psk` and configure an `external_hostname` or HTTPS certificate files.

## Repository Layout

- `delinea_mcp/` - package containing the MCP tools: `tools.py` (Secret
  Server), `user_platform_tools.py` (Delinea Platform),
  `secretserver_users.py` (SS-local users), `strongdm_tools.py` (StrongDM,
  optional), plus `transports/` (SSE + streamable HTTP) and `auth/` (the
  embedded OAuth authorization server).
- `server.py` - thin entry point that registers everything with the MCP server.
- `docs/` - project documentation and the generated `delinea-secret-server-openapi-spec.json`.
- `scripts/` - helper examples including `manual_secret_request.py`.

## Security Considerations

The embedded OAuth authorization server is a convenience for development,
testing and small deployments; larger deployments should front the server
with their organisation's identity provider. Current safeguards:

- Client registration (`/oauth/register`) and the authorization form both
  require the `registration_psk` shared secret (constant-time compared).
- `redirect_uri` values are validated against the URIs registered for the
  client on both the authorize form and the code redirect.
- Access tokens are audience-bound RS256 JWTs; resource discovery follows
  RFC 9728 (`/.well-known/oauth-protected-resource` plus `WWW-Authenticate`
  headers on 401/403 responses).
- Always deploy with TLS (`ssl_keyfile`/`ssl_certfile` or a terminating
  proxy) — bearer tokens and secrets transit every request.
- Scope tool exposure per use case with `enabled_tools`; secret _values_
  are kept out of model context by design (server-side password
  generation, env-var script indirection, password-field guards).

## Release Notes

See [CHANGELOG.md](CHANGELOG.md) for a summary of the latest features and
roadmap items.

## Roadmap

1. Passthrough authentication
2. OAuth Client ID Metadata Documents (CIMD) client support (Dynamic Client
   Registration is deprecated as of MCP protocol revision 2026-07-28; the
   PSK-gated `/oauth/register` flow keeps working for current connectors)
3. Expand tool coverage on the Delinea Platform and add other Delinea products

## Contributing

Contributions are welcome!
Please open issues or pull requests for any improvements.
All new code should include unit tests and pass the existing test suite.

## License

This project is licensed under the [MIT License](LICENSE).
