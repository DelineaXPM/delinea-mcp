# Release Notes

## v2.0.0 — Claude Code plugin, PyPI package, secret-visibility hardening

### Distribution

- Published on PyPI as `delinea-mcp`, with a `delinea-mcp` console script
  (`uvx delinea-mcp`). The implementation moved into the package
  (`delinea_mcp/server.py`, `delinea_mcp/api.py`); the root `server.py` and
  `delinea_api.py` stay as aliases, so `uv run server.py` still works.
- New Claude Code plugin in `plugins/delinea`, with the
  **no-secret-visibility** and **building-reports** skills. The skills also
  work on their own with any Delinea MCP connection.
- Runs without a config file: connection settings fall back to
  `DELINEA_USERNAME`, `DELINEA_BASE_URL`, `PLATFORM_HOSTNAME`,
  `PLATFORM_SERVICE_ACCOUNT` and `PLATFORM_TENANT_ID`, and
  `DELINEA_MCP_CONFIG` can point at a config file. Fixes a bug where no
  tools were registered when `config.json` wasn't in the working directory.

### Secret visibility

- `get_secret` and `fetch` mask password-type fields (`********`) and list
  them under `maskedFields`.
- Plaintext reveal is **disabled by default**. When the user or an
  administrator enables it (new `secret_reveal_mode` config key,
  `DELINEA_SECRET_REVEAL_MODE`, or the plugin's "Allow revealing passwords"
  setting), a new `reveal_secret_field` tool returns one plaintext value
  only after the user approves an MCP elicitation prompt ("Reveal secret
  value") sent by the server, on both the 2026-07-28 input-required flow and
  older protocol versions. Modes: `disabled` (default), `elicit`,
  `client_approval`.
- Over stdio, `get_secret_environment_variable` fetches the secret itself
  and writes a private (`0600`), self-deleting env file that expires after
  15 minutes, returning only its path. It no longer needs curl or jq, and
  works the same in bash, PowerShell and cmd (the old cmd script needed
  `head` and `sed`, which Windows doesn't have). Passwords come from the
  field endpoint (`/secrets/{id}/fields/{slug}`), since a secret GET may
  leave them out; the HTTP-transport scripts do the same.
- Over stdio, `set_secret_field_environment_variable` uploads `file:`
  sources directly, and for `env:`/`stdin` returns a one-line command that
  runs the server's own Python in isolated mode (`python -I -m
delinea_mcp.field_push`, hidden prompt for `stdin`), so a package in the
  user's project can't stand in for it and read the job's access token. No
  curl, jq or PowerShell 7 needed.
- New `script_delivery` config key (`auto`, `file`, `inline`). Scripts
  returned over HTTP transports state their requirements; the broken bash
  script (both `export` lines on one line, mis-quoted `jq`, two API calls)
  is fixed, and cmd is refused there in favor of PowerShell.

### Plugin setup

- **One Platform service account is enough.** With a Platform hostname set,
  the vault session signs in through the Platform, and the Platform user,
  role and report tools now reuse that account unless a separate
  `PLATFORM_SERVICE_*` pair is given. The plugin settings say so.
- Error text built from API responses masks any value the user just
  submitted (`set_secret_field_environment_variable` and `field_push`) and
  the generated password in `update_secret_generated_password`, even if a
  server echoes it in a validation message. Masking happens before the text
  is shortened, so logs and tool results never hold part of the value.
- `scripts/seed_test_tenant.py` creates the folder, secret and IDs the live
  tests expect; the live tests can sign in through the Platform
  (`LIVE_SS_VIA_PLATFORM=1`).
- Outbound TLS is verified against the **operating system's certificate
  store** (`truststore`), so the server signs in on networks that inspect
  TLS (Cloudflare Gateway, Zscaler, Netskope) and to on-premises Secret
  Servers with internal CAs. Before, `requests` used Python's bundled list
  and failed with `CERTIFICATE_VERIFY_FAILED`. Set `DELINEA_TLS_TRUST=bundled`
  to keep the old behavior.
- **Platform first: only the Platform URL is needed.** With a Platform
  hostname and no Secret Server URL, the server signs in through the
  Platform and asks its vault broker (`GET /vaultbroker/api/vaults`) for the
  tenant's default Secret Server vault. The plugin's Secret Server URL is now
  an optional override (also for a standalone Secret Server). The Platform
  setting accepts a pasted URL (`https://<tenant>.delinea.app/`), and the
  plugin never falls back to `https://localhost/SecretServer` with your
  credentials when both URLs are blank.
- `max_result_bytes` now also caps async tools (`reveal_secret_field`), and
  an `enabled_tools` key in `config.json`, even an empty list (every tool),
  is no longer overridden by `DELINEA_TOOL_PRESET` or
  `DELINEA_ENABLED_TOOLS` from the environment.
- **Tool access presets.** The plugin's required **Tool access** picker
  chooses **Read-only** (read-only tools plus `run_report` and
  `get_secret_environment_variable`; nothing in the vault or Platform is
  changed), **All tools** (the default) or **Custom** (the **Custom tool
  list**, `DELINEA_ENABLED_TOOLS`). Outside the plugin: `tool_preset` in
  `config.json` or `DELINEA_TOOL_PRESET`. Unknown values and an empty custom
  list fall back to read-only. The picker needs Claude Code 2.1.271 or later.
- **Settings page reorganized.** Required settings come first, titled
  **Required:** (Platform URL, client ID, client secret, tool access and the
  custom tool list); everything else follows, titled **Optional:**.
- The plugin launches with `uvx --no-config --python 3.13`. It's
  distributed through the official Claude plugin directory.
- **The plugin never reads config files from your project.** Claude Code
  starts the server in the open project's folder, so a `config.json` in a
  cloned repository could have redirected `delinea_base_url` and received your
  keychain password. With `DELINEA_MCP_PLUGIN=1` (set by the plugin) the
  server ignores `./config.json` and `$DELINEA_MCP_CONFIG` and takes settings
  only from the plugin configuration. `uvx` runs with `--no-config` so a
  project's `uv.toml` / `[tool.uv]` can't point the download at another
  package index.

- **Windows support in the plugin is experimental.** The server, skills
  and credential handoff are platform-neutral, but the plugin's startup
  check and `/delinea:setup` helper are POSIX shell scripts (they run under
  the Git Bash that Claude Code uses on Windows) and haven't been verified
  on Windows yet; there `setup-uv.sh link` only prints PATH instructions.
- The startup check also notices when the plugin's required settings (a
  Platform URL, or a standalone Secret Server URL, and a client ID) were
  never entered and tells the user to fill them in under `/plugin`.
- A `SessionStart` hook checks for `uvx` and, only when it's missing or off
  PATH, asks Claude to offer `/delinea:setup`. It never installs anything.
- The `/delinea:setup` skill checks the machine, asks the user once, then
  installs uv (Homebrew, WinGet, Scoop, pipx, a private PyPI virtual
  environment, or uv's official installer), links `uvx` onto PATH so no
  restart is needed where possible, and pre-downloads the server. The logic
  lives in `plugins/delinea/scripts/setup-uv.sh` (no `sudo`); it covers
  proxies, blocked Python downloads, and a no-uv fallback.

### Tool quality

- `list_example_reports` no longer documents `tbUser.Active`, which current
  Secret Server versions don't have (reports using it failed). A live test
  now checks every documented table and column against the tenant.
- Every tool has a `title` (also set in its annotations).
- The deprecated `platform_user_management` alias takes the same parameters
  as `user_management` again. Its MCP schema asked for required `args` and
  `kwargs` strings, so calls with `action`/`user_id` failed validation.
- API failures return the Secret Server or Platform error message, its
  `errorCode`, and a hint on what to do, instead of a bare HTTP status.
- `run_report` links the Secret Server REST API docs, points at
  `list_example_reports` as its schema reference, and caps rows with
  `max_rows` (default 200), reporting `total_rows` and `truncated`.
- `search_secrets`, `search_folders` and every `list` action page with
  `take` (default 50, max 500) and `skip`. `get_folder` returns the
  descendant tree only with `all_children=True`.

### Breaking changes

- Removed `ai_generate_and_run_report`, the Azure OpenAI dependency and the
  `azure_openai_*` config keys. Build SQL from `list_example_reports` and
  run it with `run_report`.
- `get_secret` and `fetch` no longer return plaintext passwords; use
  `get_secret_environment_variable`, or enable `secret_reveal_mode` and use
  `reveal_secret_field`.
- Over stdio, `get_secret_environment_variable` returns
  `{"script_path", "run", ...}` and `set_secret_field_environment_variable`
  returns `{"result": ...}` or `{"command": ...}` instead of script text.
  Over HTTP transports, `get_secret_environment_variable` no longer
  supports `cmd`.
- `get_folder` and `folder_management("get")` no longer include all
  children by default.
- `run_report` errors start with `Report '<name>' failed:`.
- StrongDM tools register only with `strongdm_enabled: true`. StrongDM, a
  Delinea company, will be fully supported in a future release.

### Other

- License copyright: Delinea, 2026 (originally written by Gal Diskin, 2025).
- New `SECURITY.md` with private vulnerability reporting.
- Secret Server sign-in rejections (400/401/403) explain the Secret Server
  12.1+ **Prevent direct API authentication** default and how to fix it
  (use an Application Account, or grant **Bypass Direct API Authentication
  Restriction**); the README has a new "Secret Server account" section.
- Security work released since 1.1.0 (#60, #61, #63, #64, #65): `authlib`
  dropped in favor of `joserfc` (now `>=1.7.5`, for GHSA-jpxq-7h8p-2q76 and
  GHSA-9pg5-8c7x-5hfx) for JWT handling; mcp 2.2.0, pyjwt 2.15.1,
  urllib3 2.8.0 and anyio 4.14.2 in the lockfile; refreshed container base
  image and pinned CI actions; tool error text preserved on MCP SDK 2.1+.

## v1.1.0 — MCP protocol 2026-07-28, StrongDM backend, security batch

### MCP protocol / SDK

- Migrated to the `mcp` 2.0 SDK line (`MCPServer`). The server now speaks
  **protocol revision 2026-07-28** (stateless requests, `server/discover`)
  while continuing to serve 2024-11-05…2025-11-25 handshake clients.
- New **streamable HTTP endpoint at `/mcp`** — the current MCP transport —
  mounted alongside the legacy `/mcp/sse` + `/messages/` HTTP+SSE endpoints
  (unchanged) and stdio. New config keys `streamable_http_stateless` /
  `streamable_http_json_response` (both default `true`).
- **RFC 9728 protected-resource metadata** at
  `/.well-known/oauth-protected-resource` (+ `/mcp` alias); 401/403 responses
  now carry `WWW-Authenticate` headers with `resource_metadata` so clients
  can discover the authorization server per the current MCP auth spec.
- Every tool now publishes **behaviour annotations**
  (read-only/destructive/idempotent hints) via `tools/list`.

### StrongDM (new optional backend, experimental)

- `pip install "delinea-mcp[strongdm]"` adds ten compound SDM admin tools:
  `sdm_search`, `sdm_audit_access`, `sdm_grant_access` (time-boxed JIT or
  standing), `sdm_revoke_access`, `sdm_user_management` (onboard/offboard),
  `sdm_role_management`, `sdm_resource_health`, `sdm_access_requests`,
  `sdm_activity_report`, `sdm_network_status`. See `docs/strongdm.md`.
- House safety rails: confirm + audit-comment gating on destructive actions,
  preview mode, candidate disambiguation before any mutation, bounded lists,
  verification read-backs.

### Security

- OAuth guard now applies to the SSE message channel (`/messages/` routed
  through FastAPI instead of a dependency-bypassing mount) — previously
  every `tools/call` over SSE+OAuth was unauthenticated (#52).
- `/oauth/register` actually requires the registration PSK
  (constant-time compare; Bearer or JSON `secret`) (#53).
- `enabled_tools` allowlist now covers SS-local and Platform registrars (#54).
- Newly written JWT private keys are chmod 0600 (#55).
- Dependency patches: cryptography 50.0.0 (GHSA-537c-gmf6-5ccf), joserfc
  1.7.4, pyjwt 2.13.0, python-multipart 0.0.32, starlette 1.6.0
  (multiple PYSEC advisories); `pip-audit` reports clean.

### Fixes

- SSE clients are now advertised the exact guarded POST path
  (`/messages/`); the transport handlers no longer trigger a second ASGI
  response after streaming ends.
- Connector guides pointed at a `/sse` endpoint that never existed; they
  now document `/mcp` (and `/mcp/sse` as legacy).

### Notes

- SDK v2 runs sync tools on worker threads; token acquisition in the SS
  session and Platform header cache is now lock-protected.
- Follow-up recorded: CIMD (Client ID Metadata Documents) support — DCR is
  deprecated as of protocol 2026-07-28 but current connectors still use it.

## v1.0.0 — Platform-first user management (breaking)

In Delinea cloud and Platform-integrated tenants the authoritative user
store is the Delinea Platform identity directory; Secret Server's own
`/v1/users/*` endpoints only manage local-mirror records there. v1.0.0
makes the canonical `user_management` and `search_users` tools talk to
the Platform identity API by default.

### Breaking

- `user_management` now talks to the Delinea Platform identity API
  (`/identity/CDirectoryService/*`, `/identity/UserMgmt/*`). The previous
  Secret-Server-local implementation has moved to
  `secretserver_local_user_management` (in
  `delinea_mcp.secretserver_users`).
- `search_users` now searches the Platform user directory. The previous
  `/v1/users` search has moved to `search_secretserver_local_users`.
- Clients that pinned `enabled_tools` to `user_management` /
  `search_users` will now hit Platform endpoints. SS-only deployments
  must either:
  1. configure Platform (`PLATFORM_HOSTNAME`,
     `PLATFORM_SERVICE_ACCOUNT`, `PLATFORM_SERVICE_PASSWORD`,
     `PLATFORM_TENANT_ID`), or
  2. switch the client to the new `secretserver_local_*` tool names.

### Added

- **`update_secret_fields`** — read-template → mutate-non-password-fields
  → verify flow. Refuses fields whose template marks `isPassword=True`
  unless `allow_password_fields=True`; routes audit comments through
  `autoCheckout`/`autoCheckIn`/`autoComment` query params.
- **`bulk_user_response`** — opinionated combinator over
  `/v1/bulk-user-operations/*`. Scenarios: `compromise`, `offboard`,
  `unlock`, `reenable`, `force_logout`. Requires `confirm=True` _and_ a
  non-empty `comment`; `confirm=False` returns a preview that makes no
  API calls.
- **`platform_role_management`** — Platform identity role CRUD using
  `SaasManage/StoreRole`, `Roles/UpdateRole`, `Redrock/Query`, and
  `SaasManage/RemoveRole`.
- **`platform_user_role_management`** — add/remove/list users on a
  Platform role via `Roles/UpdateRole` `Users.Add`/`Users.Delete`.
- **`platform_user_management`** retained as a deprecated alias for
  `user_management`; old clients keep working.

### Notes

- Live-verified against:
  - a Secret-Server cloud tenant for all SS-side flows
    (`update_secret_fields`, `bulk_user_response` preview,
    `secretserver_local_*`, search/fetch).
  - a Delinea Platform tenant (`dartlabs.secureplatform.io`) for the
    Platform-side flows (`user_management` full CRUD lifecycle,
    `search_users`, `platform_role_management` read, `platform_user_role_management`
    read). 32 live integration tests pass.
- Platform endpoint discovery: on modern Delinea Platform tenants the
  identity-API namespace is `/identity/api/...` (not `/identity/...`),
  and `GetUser` was replaced by `GetUserAttributes` (POST `{"ID": …}`).
  This release fixes those paths.
- Role mutation endpoints (`SaasManage/StoreRole`, `Roles/UpdateRole`,
  `SaasManage/RemoveRole`) are **discovery-driven**: the tools attempt
  the documented endpoint and only fall back to a structured guidance
  error on HTTP 404 (typical on modern Platform tenants using the
  `xpmheadless` scope, which exposes user CRUD but not role CRUD).
  Tenants that DO expose those endpoints get the real result. The
  guidance error directs callers to the SS-side `role_management` /
  `user_role_management` tools or the Platform admin UI.

The current release introduces a comprehensive tool set for integrating Delinea Secret Server with the Model Context Protocol.

## Highlights

- Manage folders, secrets, users, groups and roles directly from the MCP server.
- Inbox management and access request helpers for administrators.
- Coding agent utilities and ChatGPT compatible tools (`search` and `fetch`).
- Initial Delinea Platform support limited to user management.
- Choose between SSE or STDIO transport modes.
- OAuth 2.0 authentication with Dynamic Client Registration.
- TLS support for secure connections.
- Verified with ChatGPT (deep research and custom connector), Claude Desktop, remote Claude connector, VSCode Copilot and openwebui.

## Roadmap

1. Passthrough authentication
2. Streaming HTTP transport support
3. Expanded tool coverage on the Delinea Platform and other Delinea products
