# Release Notes

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
  etc.) are **not exposed** via the `xpmheadless` OAuth scope on modern
  Platform tenants. `platform_role_management` and
  `platform_user_role_management` therefore support read actions
  (`list`, `get`) but return a structured "not supported on this scope"
  error for write actions, directing the caller to use the SS-side
  `role_management` tool or the Platform admin UI.

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
