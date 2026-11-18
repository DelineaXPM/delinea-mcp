# PB-001: Publish DelineaMCP as a Claude Code plugin

> **Type:** pbi
> **Created:** 2026-11-17T00:00:00Z
> **Updated:** 2026-11-17T00:00:00Z
> **ADO:** TBD (not yet created)
> **Source plan:** [docs/claude-plugin-plan.md](../../../../../../docs/claude-plugin-plan.md)

---

## Metadata

| Field           | Value                                                                                                      |
| --------------- | ---------------------------------------------------------------------------------------------------------- |
| **Criticality** | C3 (Significant), confirmed by user. Changes config loading (security fix), tool exposure, and credentials |

---

## Overview

Ship the DelineaMCP server as a Claude Code plugin. Distribute it through a marketplace hosted in this repository and
then through Anthropic's plugin directory. Approach (user-confirmed): the plugin lives in a `plugin/` subfolder and
launches the server as a PyPI package with a pinned `uvx delinea-mcp==X.Y.Z`.

The server currently can't run as a plugin, for three reasons:

- It can't be installed as a package.
- It can't be configured from environment variables alone.
- It reads `config.json` from the working directory, which under Claude Code is the user's project.

This work fixes those problems, publishes the package, and adds the plugin and marketplace files.

---

## Requirements

1. **R1, env-only configuration:** the server initializes a Secret Server session from `DELINEA_BASE_URL`,
   `DELINEA_USERNAME`, and `DELINEA_PASSWORD` without any config file.
2. **R2, no ambient config in plugin mode:** when `DELINEA_MCP_PLUGIN=1`, the server ignores `config.json` in the
   working directory and at the package default path. `--config` still works.
3. **R3, safe default toolset:** in plugin mode, an empty tool list registers only tools annotated `read_only_hint=True`.
4. **R4, explicit tool selection via env:** `DELINEA_ENABLED_TOOLS` (comma-separated) selects tools when no config
   `enabled_tools` is given.
5. **R5, installable package:** `uv build` produces a wheel. Installing it provides a `delinea-mcp` console script that
   starts the server, and `importlib.metadata.version("delinea-mcp")` returns the package version.
6. **R6, PyPI release:** a GitHub Actions job publishes the wheel and sdist to PyPI with Trusted Publishing.
7. **R7, plugin and marketplace files:**
   - `plugin/.claude-plugin/plugin.json`, `plugin/.mcp.json`, `plugin/README.md`, and `plugin/LICENSE` exist.
   - `.claude-plugin/marketplace.json` at the repository root lists the plugin with `source: "./plugin"`.
   - `claude plugin validate --strict` passes on both.
8. **R8, version lockstep:** CI fails if the `plugin.json` `version`, the `.mcp.json` `uvx` pin, and the
   `pyproject.toml` `version` differ.
9. **R9, disclosure:** the plugin README lists every network destination the server can contact.
10. **R10, no regressions:** existing behavior is unchanged when `DELINEA_MCP_PLUGIN` is unset. That covers
    `uv run server.py`, cwd `config.json` lookup, empty `enabled_tools` meaning all tools, and Docker.

---

## Verifiable Behaviors

| #   | Req | Given                                                                    | When                                | Then                                                    | Verify by     |
| --- | --- | ------------------------------------------------------------------------ | ----------------------------------- | ------------------------------------------------------- | ------------- |
| 1   | R1  | No config file; env has `DELINEA_USERNAME`, `DELINEA_PASSWORD`, base URL | `_init_from_config({})`             | `SessionManager` is initialized with the env username   | unit          |
| 2   | R1  | Config has `delinea_username: "cfg"`; env has `DELINEA_USERNAME=env`     | `_init_from_config(cfg)`            | Config value wins (`cfg`)                               | unit          |
| 3   | R1  | Config `delinea_username` is a `<placeholder>` or empty string           | `_init_from_config(cfg)`            | Falls back to env username                              | unit          |
| 4   | R2  | `DELINEA_MCP_PLUGIN=1`; cwd has `config.json` with `transport_mode: sse` | `run_server([])`                    | cwd config is not loaded; stdio transport runs          | unit          |
| 5   | R2  | `DELINEA_MCP_PLUGIN` unset; cwd has `config.json`                        | `run_server([])`                    | cwd config is loaded (today's behavior)                 | unit (exists) |
| 6   | R2  | `DELINEA_MCP_PLUGIN=1`; `--config path` passed                           | `run_server(["--config", p])`       | Explicit config is loaded                               | unit          |
| 7   | R3  | `DELINEA_MCP_PLUGIN=1`; no `enabled_tools`, no `DELINEA_ENABLED_TOOLS`   | Server initializes                  | Exactly the `_RO` tools of configured backends register | unit          |
| 8   | R3  | `DELINEA_MCP_PLUGIN` unset; no `enabled_tools`                           | Server initializes                  | All tools register (today's behavior)                   | unit (exists) |
| 9   | R4  | `DELINEA_ENABLED_TOOLS="get_folder, search_secrets"`                     | Server initializes                  | Only those two tools register; whitespace is trimmed    | unit          |
| 10  | R4  | Config `enabled_tools` non-empty and `DELINEA_ENABLED_TOOLS` set         | Server initializes                  | Config list wins                                        | unit          |
| 11  | R5  | Clean venv                                                               | Install wheel; `delinea-mcp --help` | Exits 0 and prints argparse usage                       | CI script     |
| 12  | R5  | Installed wheel                                                          | `version("delinea-mcp")`            | Equals `pyproject.toml` version, not `0.0.0-dev`        | CI script     |
| 13  | R7  | Plugin files present                                                     | `claude plugin validate`            | `Validation passed`                                     | CI            |
| 14  | R8  | `plugin.json` version is 1.2.0; `.mcp.json` pins 1.2.1                   | CI version check                    | Job fails, naming the mismatch                          | CI            |
| 15  | R7  | Local marketplace added; plugin installed; test-tenant userConfig        | Run `/mcp` in a session             | Server connected; only read-only tools listed           | manual        |
| 16  | R3  | **Ambiguous:** `get_secret` (`_RO`, returns secret values) in default?   | —                                   | Needs a decision (context.md Open Questions)            | engineer      |

---

## Architecture Approach

The code changes stay in `server.py` `_init_from_config` and `run_server`. Those two functions are the only places
config gets turned into runtime state, and every tool module's `register(mcp, enabled)` already accepts the
`enabled` set.

**Key Design Decisions:**

- **One env flag, `DELINEA_MCP_PLUGIN=1`, controls both plugin-mode behaviors**: ignoring ambient config and the
  read-only default.
  - Rationale: the defaults stay unchanged for existing users (R10).
  - The plugin's `.mcp.json` always sets the flag, so the two behaviors never need to be toggled separately.
- **Read-only set is derived from `TOOL_ANNOTATIONS`** (`read_only_hint is True`), not a hand-maintained list. New
  tools are classified once, in `annotations.py`.
- **`DELINEA_ENABLED_TOOLS` is a comma-separated string.**
  - The plugin's `userConfig` field is a single `string`, not `multiple: true`.
  - How Claude Code substitutes an array into an `env` value is undocumented, so a plain string avoids the guesswork.
- **Keep `server.py` and `delinea_api.py` as top-level py-modules** in the wheel.
  - `uvx` installs into an isolated environment, so the generic `server` module name can't collide with anything.
  - Moving them into `delinea_mcp/` is deferred until pip users report collisions.
- **Remove the `os.environ.pop("DELINEA_USERNAME")`.** It has been there since the initial commit (`095b907`) with no
  recorded reason, and it is what blocks env-only configuration.
- **StrongDM is out of plugin v1.** It needs the `[strongdm]` extra, and the directory's pin detection may not parse
  `uvx --from "delinea-mcp[strongdm]==X"`.

---

## Implementation Plan

**TDD Approach:** each code phase follows Red-Green-Refactor. Write the tests before the implementation code.

### Phase 1: Env-only configuration and plugin-mode config isolation (R1, R2, R10)

**Complexity:** Complex (it touches the security boundary for config loading)

**Tests First (RED):**

- `tests/test_run_server.py`: behaviors 4 and 6. Use `monkeypatch.chdir` plus a hostile cwd `config.json` with
  `transport_mode: sse`, and assert that `mcp.run(transport="stdio")` is called.
- New tests in `tests/test_register.py` or `tests/test_server_platform.py` for behaviors 1–3.
- Confirm that behavior 5's existing tests still pass unchanged.

**Implementation (GREEN):**

- Files: `server.py`.
- `_init_from_config`:
  - `username = cfg.get("delinea_username") or os.getenv("DELINEA_USERNAME")`, with the same placeholder handling as
    `tools._cfg_or_env`.
  - Drop the `os.environ.pop`.
- `run_server`: when `os.getenv("DELINEA_MCP_PLUGIN") == "1"` and there is no `--config`, call `_init_from_config({})`
  and skip the cwd `config.json` and the import-time `CURRENT_CONFIG`.
- Import-time `CURRENT_CONFIG = load_config()`: skip it in plugin mode, so that once installed, nothing reads
  `site-packages/../config.json`.

**Verify:**

- New tests pass; the full suite passes; the count is at least 332 plus the new tests.
- 100% coverage on `server.py` (`AGENTS.md`).

### Phase 2: Tool selection, env list and read-only default (R3, R4)

**Complexity:** Moderate

**Tests First (RED):**

- Behaviors 7, 9 and 10. Assert on the tool names registered on a `DummyMCP` across `tools`, `secretserver_users`,
  `user_platform_tools`, and `strongdm_tools`.

**Implementation (GREEN):**

- Files: `server.py` (and `delinea_mcp/annotations.py` only if it needs a helper).
- Resolve `enabled` in this order:
  1. Config `enabled_tools`.
  2. `DELINEA_ENABLED_TOOLS`, split and stripped.
  3. In plugin mode, `{n for n, a in TOOL_ANNOTATIONS.items() if a.read_only_hint}`.
  4. Otherwise an empty set, which means all tools.
- No changes to the per-module `register()` functions.

**Verify:** new tests pass; the full suite passes; coverage holds.

### Phase 3: Packaging (R5)

**Complexity:** Moderate

**Tests First (RED):**

- Add a `package-smoke` job to `.github/workflows/test.yml` that runs `uv build` and installs the wheel into a fresh
  venv. In that venv it asserts `delinea-mcp --help` exits 0 and that `python -c "import importlib.metadata as m;
print(m.version('delinea-mcp'))"` matches `pyproject.toml`. It fails today because there's no build-system.

**Implementation (GREEN):**

- Files: `pyproject.toml`, `uv.lock`.
- `[build-system]`: hatchling.
- `[project.scripts] delinea-mcp = "server:run_server"`.
- In `[tool.hatch.build.targets.wheel]`, include `delinea_mcp/`, `server.py`, and `delinea_api.py`.
  - Exclude `tests/`, `docs/`, and `scripts/`.
  - Check that `delinea_mcp/constants.py` and any package data ship.
- Add `license`, `authors`, and `[project.urls]` metadata, which PyPI requires.
- Bump `version` to `1.2.0`.
- Run `uv lock`; `requirements.txt` is unchanged.

**Verify:**

- The CI smoke job passes, and so does a local `uvx --from dist/*.whl delinea-mcp --help`.
- `docker build` still works (it doesn't use the wheel).

### Phase 4: PyPI release pipeline (R6)

**Complexity:** Moderate (CI only; there are no unit tests)

**Prerequisites (human):**

- Create a PyPI account for Delinea, or use an existing org account.
- Register a **pending Trusted Publisher** for project `delinea-mcp`: repository `DelineaXPM/delinea-mcp`, workflow
  `release.yml`, environment `pypi`.
- Create a `pypi` GitHub environment with required reviewers.

**Implementation:**

- Files: `.github/workflows/release.yml`.
- Replace the hardcoded `version=v0.1.0` detection with the `pyproject.toml` version.
- Add a `pypi-publish` job: `uv build`, then `uv publish --trusted-publishing always`, in the `pypi` environment with
  `id-token: write`.
- Leave the goreleaser TODOs alone; they're out of scope.

**Verify:** a dry run against TestPyPI (`UV_PUBLISH_URL=https://test.pypi.org/legacy/`) succeeds, and
`uvx --index-url https://test.pypi.org/simple/ --index-strategy unsafe-best-match delinea-mcp==1.2.0 --help` works.

### Phase 5: Plugin, marketplace, and CI validation (R7, R8)

**Complexity:** Simple

**Tests First (RED):**

- Add a `plugin-validate` job to `test.yml`. It installs a pinned `@anthropic-ai/claude-code` and runs
  `claude plugin validate --strict plugin/` and `claude plugin validate .`.
- The same job runs a version-lockstep check: `jq` on `plugin.json` and `.mcp.json`, plus the `pyproject.toml` version,
  failing on any mismatch.

**Implementation (GREEN):**

- New files:
  - `plugin/.claude-plugin/plugin.json` and `plugin/.mcp.json`, per `docs/claude-plugin-plan.md`, with these changes:
    `enabled_tools` becomes a single comma-separated `string`, `.mcp.json` sets `DELINEA_MCP_PLUGIN=1` and
    `DELINEA_ENABLED_TOOLS=${user_config.enabled_tools}`, and the pin is `uvx delinea-mcp==1.2.0`.
  - `plugin/README.md`.
  - `plugin/LICENSE`, a copy of the root `LICENSE`.
  - `.claude-plugin/marketplace.json`, named `delinea`.
- Don't add a `.npmrc` or `uv.toml` under `plugin/`.
- Add `.DS_Store` to `.gitignore` if it isn't there already.

**Verify:** the CI job passes, and changing the pin by hand makes it fail (behavior 14).

### Phase 6: Directory readiness and docs (R9)

**Complexity:** Simple

- `plugin/README.md`:
  - What the plugin does.
  - The Application Account requirement.
  - Every destination it contacts: the user's Secret Server, Platform, and StrongDM, and Azure OpenAI only when it is
    configured.
  - That credentials are stored in the OS keychain.
  - The default read-only toolset and how to widen it.
- Add the listing fields to `plugin.json`: `icon` (an SVG or PNG under `plugin/`), plus `documentationUrl`,
  `supportUrl`, `privacyPolicyUrl`, and `termsOfServiceUrl`, using URLs from Delinea.
- Root `README.md`: add a Claude Code plugin install section. Update `docs/claude-desktop.md` with a pointer to it.
- Changelog: a `v1.2.0` section in the hand-written `CHANGELOG.md` (the repo has no changie config).
- Document `DELINEA_SECRET_SERVER_{URL,USERNAME,PASSWORD}` (preferred, with legacy fallback), `DELINEA_MCP_PLUGIN`
  and `DELINEA_ENABLED_TOOLS` in the root README configuration section.
- Update `docs/claude-plugin-plan.md` with final decisions (key names, string `enabled_tools`, Platform settings).
- Optional, after v1: a `skills/secret-server/SKILL.md` usage-guidance skill.

### Phase 7: Resilient startup on Secret Server auth failure

**Complexity:** Moderate

**Problem:** `_init_from_config` builds `DelineaSession`, which authenticates in `__post_init__`. A wrong URL or
password, or a network blip at launch, raises and kills the process, so `/mcp` shows "failed" with no reason.

**Tests First (RED):**

- With credentials set and authentication raising (`ConnectionError`, HTTP 401, `ValueError`), `_init_from_config`
  returns normally and tools still register.
- A tool call after a failed startup returns an error payload naming the cause (for example "Secret Server login
  failed: ..."), never the password.
- A later tool call retries authentication and succeeds once the server is reachable (transient failure recovers
  without restarting).
- Concurrent first calls authenticate once.

**Implementation (GREEN):**

- `SessionManager` gains a lazy path: store a factory instead of a built session; `get()` builds it on first use under
  a lock and raises a clear `RuntimeError` on failure. `guard_tool` already turns tool exceptions into error payloads.
- `_init_from_config` registers the factory and logs (does not raise) a startup authentication failure.

**Verify:** plugin-mode smoke test with an unreachable URL answers `initialize` and lists tools; a tool call returns the
login error.

### Phase 8: Release and distribution (manual)

**Complexity:** Simple (process)

1. Merge to `main`, then release `1.2.0` to PyPI through Phase 4.
2. Smoke test (behavior 15): `claude plugin marketplace add DelineaXPM/delinea-mcp`, then
   `claude plugin install delinea@delinea`, then `/mcp` against a test tenant.
3. Internal dogfood: publish to Delinea's claude.ai organization library.
4. Directory: a Delinea claude.ai Owner submits `plugin/` at claude.ai/directory/manage and runs **Validate**. Expect a
   pinned-`uvx` policy hold.

---

## Testing Strategy

**Coverage target:** 100% on non-test files (the repository standard in `AGENTS.md`, which is above the 80% template
default).

**Unit Tests:**

- Config precedence (config, then env, then placeholder) for the username and the tool list.
- Plugin-mode isolation against a hostile cwd `config.json`.
- Read-only set derivation, including that StrongDM and Platform read-only tools are included only when registered.
- Edge cases: `DELINEA_ENABLED_TOOLS` that is empty, only whitespace, or contains unknown tool names (ignored, as
  `enabled_tools` does today); and `DELINEA_MCP_PLUGIN` set to values other than `1` (treated as off).

**Integration / CI:**

- Wheel build, install, and console-script smoke test.
- `claude plugin validate --strict`.
- Version lockstep check.

**Manual Testing:**

- Behavior 15: an end-to-end install from the local marketplace and from GitHub.
- The secret password is stored in the keychain, not in `~/.claude/settings.json`.
- Existing usage still works: `uv run server.py --config config.json` and the Docker image.

---

## Security Considerations

- [x] **Authentication/Authorization:** unchanged. Secret Server authentication still uses the password grant with an
      Application Account. In plugin mode, the read-only default reduces the blast radius of a prompt-injected tool call.
- [x] **Input Validation:** `DELINEA_ENABLED_TOOLS` is only matched against known tool names, so unknown names are
      ignored. The `--config` path validation is unchanged.
- [x] **Data Exposure:**
  - Plugin mode stops a project-supplied `config.json` from redirecting the server to a different base URL, turning on
    SSE on `0.0.0.0`, or enabling Azure OpenAI. Any of those would exfiltrate data or credentials.
  - Open question: `get_secret` in the default set exposes secret values to the model.
- [x] **Secrets Management:**
  - The password comes from a `sensitive: true` `userConfig` field, stored in the OS keychain, and is passed only
    through the MCP server's `env`.
  - No credentials go in repository files or examples. The directory scan blocks those.
- [x] **API Security:** stdio only; no listening port in plugin mode.
- [x] **Supply chain:**
  - PyPI publishing uses Trusted Publishing, so there's no long-lived token.
  - The pinned exact version is in `.mcp.json`.
  - A `pypi` environment with required reviewers gates each release.

---

## Critical Paths

| Path / Component                                             | Why critical                                                        | Review level     |
| ------------------------------------------------------------ | ------------------------------------------------------------------- | ---------------- |
| `server.py` `run_server` config loading                      | Trust boundary between the user's project files and server config   | security-focused |
| `server.py` `_init_from_config` username and tool resolution | Credential sourcing; default tool exposure                          | security-focused |
| `.github/workflows/release.yml` PyPI job                     | Supply chain: publishes the code users execute                      | manual required  |
| `plugin/.mcp.json`, `plugin.json` userConfig                 | Credential flow into the server process                             | security-focused |
| `pyproject.toml` build config                                | Wheel contents (no tests or docs leaking, required modules present) | standard         |
| `delinea_mcp/session.py` lazy session (Phase 7)              | Auth error handling; must not leak credentials in error payloads    | security-focused |

---

## Database Changes

N/A. The plugin uses stdio only, and plugin mode doesn't touch the OAuth SQLite database (`oauth_db_path`).

---

## Rollback Strategy

**Immediate rollback (a bad PyPI release):**

1. `pip`/`uv` yank the bad version on PyPI. Pinned `.mcp.json` users stay on the previous pin until the plugin version
   bumps.
2. Revert the `plugin.json` and `.mcp.json` version bump on `main`, so `claude plugin update` doesn't move users to the
   yanked version.

**Delayed rollback (an issue discovered after release):**

1. Release a fixed patch version and bump the plugin pin in lockstep.
2. If the plugin itself must be pulled: remove the entry from `.claude-plugin/marketplace.json`, and unpublish it from
   the org library and the directory portal.
3. The server-side changes are inert unless `DELINEA_MCP_PLUGIN=1` is set, so existing non-plugin deployments don't
   need a rollback.

---

## Success Criteria

- [ ] R1–R10 met; behaviors 1–15 verified; behavior 16 decided
- [ ] All tests pass; count ≥ 332 baseline plus new tests
- [ ] 100% coverage on non-test files
- [ ] No tests skipped or ignored to hide failures
- [ ] `claude plugin validate --strict` passes in CI
- [ ] `delinea-mcp==1.2.0` on PyPI; `uvx delinea-mcp==1.2.0 --help` works on a clean machine
- [ ] End-to-end install from `DelineaXPM/delinea-mcp` marketplace verified against a test tenant
- [ ] Security checklist addressed; critical paths reviewed at the stated level
- [ ] README, plugin README, and changelog updated
