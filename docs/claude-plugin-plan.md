# Plan: Publish DelineaMCP as a Claude Plugin

Status: draft (2026-11-17). Covers what this repository needs before the MCP server can ship as a Claude Code plugin,
through our own marketplace and through Anthropic's plugin directory.

## Summary

- **Prior art**: Delinea has no Claude plugin today. The closest internal example is `DelineaXPM/devex-claude`, a
  skills-only marketplace (`.claude-plugin/marketplace.json` with `source: "./"`). The MCP server itself is listed on
  third-party directories (Glama, mcp.so, mcpservers.org), but nothing exists on the Claude side.
- **Two distribution targets**:
  1. **Our own marketplace in this repository.** Users run `claude plugin marketplace add DelineaXPM/delinea-mcp`.
     No review; live as soon as it merges.
  2. **Anthropic's directory**, submitted at [claude.ai/directory/manage](https://claude.ai/directory/manage).
     Reviewed, widest reach. Requires a Delinea claude.ai Owner (or a member with the Directory role) on a paid plan.
     The `claude-plugins-official` marketplace does not take submissions; it is partner-only.
- **Surface reality**: a local stdio MCP server that references `${user_config.*}` runs in **Claude Code only**.
  claude.ai chat ignores local MCP servers, and Cowork ignores servers whose options lack a default (credentials can't
  have one). Any listing will effectively be Claude Code-only unless we add skills, which load everywhere.

## Gaps in the current repository

1. **Not installable as a package.** `pyproject.toml` has no `[build-system]` or `[project.scripts]`; `server.py` and
   `delinea_api.py` live at the root; `delinea-mcp` returns 404 on PyPI. A plugin must launch the server through a pinned
   launcher (`uvx delinea-mcp==X.Y.Z`), and unpinned launchers block directory submission.
2. **No release pipeline.** `release.yml` hardcodes `version=v0.1.0`; PyPI and Docker publishing are TODOs in
   `.goreleaser.yaml`. Each plugin version needs a matching PyPI release.
3. **Cannot be configured from environment variables alone.** `server.py` `_init_from_config` reads `delinea_username`
   only from the config file and calls `os.environ.pop("DELINEA_USERNAME")` when the config has none. A plugin passes
   settings as `env`, so the Secret Server session never initializes.
4. **Loads `config.json` from the working directory (security).** `run_server()` reads `Path("config.json")` from the
   cwd when `--config` is absent. Under Claude Code the cwd is the user's project, so any repository that contains a
   `config.json` would configure the server, including `transport_mode: sse`, which binds `0.0.0.0:8000`. Must be gated
   before shipping.
5. **All tools enabled by default.** `enabled_tools: []` enables every tool, including destructive ones
   (`update_secret_fields`, `user_management`, `handle_access_request`). The plugin should default to the read-only set;
   the `_RO` annotations in `delinea_mcp/annotations.py` already identify it.
6. **Repository root cannot be the plugin folder.** `docs/delinea-secret-server-openapi-spec.json` and
   `docs/mcp-standard-info.md` exceed 256 KiB, and the root also holds `CLAUDE.md`, tests, and a Dockerfile. Files over
   256 KiB are held for review, and a `CLAUDE.md` at the plugin root triggers a validator warning.

Already in good shape: no `print()` to stdout (required for stdio), Platform credentials already fall back to
environment variables, MIT license, and tool behavior annotations.

## Target layout

This repository acts as both the marketplace and the plugin source. The plugin lives in a subfolder so only the files
it needs are shipped.

```text
.claude-plugin/marketplace.json      # name: "delinea", plugins[0].source: "./plugin"
plugin/
  .claude-plugin/plugin.json
  .mcp.json
  README.md                          # at least 40 words; disclose every outbound call
  LICENSE                            # a copy, not a symlink (symlinks block submission)
  skills/secret-server/SKILL.md      # optional, phase 4
```

`plugin/.claude-plugin/plugin.json`:

```json
{
  "name": "delinea",
  "displayName": "Delinea",
  "version": "1.2.0",
  "description": "Delinea Secret Server and Platform tools for Claude, run locally via uvx",
  "author": { "name": "Delinea", "url": "https://delinea.com" },
  "homepage": "https://github.com/DelineaXPM/delinea-mcp",
  "repository": "https://github.com/DelineaXPM/delinea-mcp",
  "license": "MIT",
  "keywords": ["secrets", "pam", "secret-server", "delinea"],
  "userConfig": {
    "secret_server_url": {
      "type": "string",
      "title": "Secret Server URL",
      "description": "For example https://tenant.secretservercloud.com",
      "required": true
    },
    "secret_server_username": {
      "type": "string",
      "title": "Secret Server application account",
      "description": "Secret Server Application Account username",
      "required": true
    },
    "secret_server_password": {
      "type": "string",
      "title": "Secret Server password",
      "description": "Application account password",
      "sensitive": true,
      "required": true
    },
    "platform_hostname": {
      "type": "string",
      "title": "Platform hostname (optional)",
      "default": ""
    },
    "platform_service_account": {
      "type": "string",
      "title": "Platform service account (optional)",
      "default": ""
    },
    "platform_service_password": {
      "type": "string",
      "title": "Platform service password (optional)",
      "sensitive": true,
      "default": ""
    },
    "platform_tenant_id": {
      "type": "string",
      "title": "Platform tenant ID (optional)",
      "default": ""
    },
    "enabled_tools": {
      "type": "string",
      "title": "Enabled tools",
      "description": "Comma-separated tool names. Leave blank for the read-only default set.",
      "default": ""
    }
  }
}
```

`plugin/.mcp.json`:

```json
{
  "mcpServers": {
    "delinea": {
      "command": "uvx",
      "args": ["--no-config", "--python", "3.13", "delinea-mcp==1.2.0"],
      "env": {
        "DELINEA_MCP_PLUGIN": "1",
        "DELINEA_SECRET_SERVER_URL": "${user_config.secret_server_url}",
        "DELINEA_SECRET_SERVER_USERNAME": "${user_config.secret_server_username}",
        "DELINEA_SECRET_SERVER_PASSWORD": "${user_config.secret_server_password}",
        "PLATFORM_HOSTNAME": "${user_config.platform_hostname}",
        "PLATFORM_SERVICE_ACCOUNT": "${user_config.platform_service_account}",
        "PLATFORM_SERVICE_PASSWORD": "${user_config.platform_service_password}",
        "PLATFORM_TENANT_ID": "${user_config.platform_tenant_id}",
        "DELINEA_ENABLED_TOOLS": "${user_config.enabled_tools}"
      }
    }
  }
}
```

Shipped decisions: `enabled_tools` is a plain comma-separated string (userConfig has no usable list default), plugin
mode is `DELINEA_MCP_PLUGIN=1` (exact string), `--no-config` stops a project `uv.toml` redirecting the package index,
and `--python 3.13` pins the interpreter. The `DELINEA_SECRET_SERVER_*` names are preferred and fall back to the
legacy `DELINEA_BASE_URL` / `DELINEA_USERNAME` / `DELINEA_PASSWORD`.

Sensitive `userConfig` values are stored in the OS credential store, not in `settings.json`. Directory policy also
requires prompting through `userConfig` rather than reading a credential already set in the user's environment.

## Phases

### Phase 1: Make the server packageable

1. Add a `[build-system]` (hatchling) and `[project.scripts] delinea-mcp = "server:run_server"`. Ship `server` and
   `delinea_api` as top-level modules. Moving them into `delinea_mcp/` is cleaner, but `uvx` installs into an isolated
   environment, so it isn't required for the plugin. Revisit if pip users hit module-name collisions.
2. Add environment fallbacks in `_init_from_config`: `DELINEA_SECRET_SERVER_USERNAME` / `DELINEA_USERNAME`, and `DELINEA_ENABLED_TOOLS` as a
   comma-separated list. Remove the `os.environ.pop("DELINEA_USERNAME")`.
3. Gate the cwd `config.json` lookup behind plugin mode, `DELINEA_MCP_PLUGIN=1` (gap 4, resolved). Also check the import-time
   `load_config(DEFAULT_PATH)`: once installed, that path resolves next to `site-packages`.
4. When launched by the plugin with no `enabled_tools`, register only the read-only tool set.
5. Add tests for each change, keeping 100% coverage on non-test files per `AGENTS.md`.

### Phase 2: Publish to PyPI

1. Claim the `delinea-mcp` name on PyPI now; it is still unregistered.
2. Replace the stub release job with `uv build` and `uv publish` using PyPI Trusted Publishing. The workflow already
   grants `id-token: write`. Replace the hardcoded version detection; changie is already wired in.
3. Release order: publish to PyPI first, then bump `plugin.json` `version` and the `.mcp.json` pin together. Add a CI
   check that fails when the pin and the `pyproject.toml` version differ.
4. Leave StrongDM out of plugin v1. It needs `uvx --from "delinea-mcp[strongdm]==X" delinea-mcp`, which the directory's
   pin detection may not parse.

### Phase 3: Plugin and marketplace files, CI validation

1. Add the layout above.
2. In `lint.yml`, install Claude Code and run `claude plugin validate --strict plugin/` and `claude plugin validate .`.
3. Smoke test locally: `claude plugin marketplace add ./`, `claude plugin install delinea@delinea`, then confirm in
   `/mcp` that the server connects to a test tenant.
4. Keep `.DS_Store` out of `plugin/` (blocks submission), and keep `.npmrc` / `uv.toml` out of it (a custom package
   source next to a launcher blocks submission).

### Phase 4: Directory readiness

1. Write the plugin README so it lists every destination the server contacts: the user's Secret Server, Platform, and
   StrongDM, and **Azure OpenAI when `ai_generate_and_run_report` is enabled, which sends prompt text there**.
   Undisclosed outbound traffic fails the security scan.
2. Add the listing fields to `plugin.json`: `icon` (PNG or SVG inside the plugin), `documentationUrl`, `supportUrl`,
   `privacyPolicyUrl`, and `termsOfServiceUrl` on delinea.com.
3. Optional: add a `secret-server` skill with usage guidance. Prefer `get_secret_environment_variable` so the model
   never sees secret values, explain the report SQL rules, and state the Application Account requirement. Skills also
   load in claude.ai chat, so the listing isn't empty there.

### Phase 5: Distribution

1. **Internal dogfood**: publish to Delinea's claude.ai organization library (from Claude Code's plugin publishing or
   from claude.ai). An organization admin reviews it.
2. **Public, self-hosted**: merge to `main` and add install instructions to the main README:

   ```bash
   claude plugin marketplace add DelineaXPM/delinea-mcp
   claude plugin install delinea@delinea
   ```

3. **Anthropic directory**: a Delinea Owner submits `plugin/` as a **Plugin bundle** at
   [claude.ai/directory/manage](https://claude.ai/directory/manage). Run **Validate** first.
   - Expect a **Runs a pinned npx or uvx package** policy hold. Every `uvx` plugin gets one; it is not a rejection.
   - The brand-name check is also held for review. That is fine as long as the submitter is in the Delinea org.

## Open decisions

- **Plugin name (resolved: `delinea`).** It is permanent once published. Recommendation: `delinea` (components appear as `delinea:...`).
  Alternative: `delinea-mcp`. A bare `mcp` or `plugin` is reserved.
- **Remote mode (deferred).** Optionally add a second server for customers who already host the SSE/OAuth deployment
  (`"type": "http", "url": "${user_config.server_url}"`). Skipped for v1: it only works in Claude Code and adds a server
  that fails when no URL is set.
- **Claude Desktop (deferred).** A `.mcpb` extension would replace the manual setup in `docs/claude-desktop.md`. Treat it as a
  separate track; bundling `.mcpb` inside the plugin is held for review.
- **Directory submitter (open).** Identify who at Delinea holds Owner or Directory rights on claude.ai. This is the only
  external blocker.
- **Platform domain (open).** `secureplatform.io` (plugin.json, repo docs) versus `delinea.app` (plugin README install
  example); confirm which is current.
- **LICENSE copyright holder (open).** Confirm with the owners before the PyPI release.

## References

- [Plugin manifest reference](https://code.claude.com/docs/en/plugins-reference)
- [Create a marketplace](https://code.claude.com/docs/en/plugin-marketplaces)
- [Publish and distribute a plugin](https://code.claude.com/docs/en/plugins/publish.md)
- [Plugin pre-submission checklist](https://claude.com/docs/plugins/pre-submission-checklist)
- [Plugin feature support across platforms](https://claude.com/docs/plugins/platform-support)
- [Anthropic Software Directory Policy](https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy)
- [Delinea MCP server announcement](https://delinea.com/news/delinea-mcp-server-to-provide-secure-credential-access-for-ai-agents)
