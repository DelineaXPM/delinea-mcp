# Release Notes

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
