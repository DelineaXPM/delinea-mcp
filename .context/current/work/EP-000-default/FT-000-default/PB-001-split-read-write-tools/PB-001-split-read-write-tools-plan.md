# PB-001: Split mixed read/write tools and link API docs

> **Type:** pbi
> **Created:** 2026-11-20T00:00:00-08:00
> **Updated:** 2026-11-20T16:00:00-08:00
> **ADO:** TBD (not yet linked)

---

## Metadata

| Field              | Value                                |
| ------------------ | ------------------------------------ |
| **Criticality**    | C3 (proposed, awaiting confirmation) |
| **Target version** | 3.0.0 (breaking: tool names change)  |

---

## Overview

The Claude directory review criteria reject any tool that takes both safe and
unsafe operations:

> A single tool that accepts both safe HTTP methods, such as GET, HEAD, and
> OPTIONS, and unsafe methods, such as POST, PUT, PATCH, and DELETE, is
> rejected. [...] Split a catch-all tool into a read-only tool and one or more
> write tools. Ideally, split write operations further by action type: create,
> update, and delete. Documenting safe versus unsafe operations within one
> tool's description doesn't satisfy this requirement.
>
> — <https://claude.com/docs/connectors/building/review-criteria>, "Separate
> read and write tools"

13 registered tools dispatch reads and writes through one `action` parameter
(plus `platform_user_management`, a deprecated alias of one of them, for 14).
This item replaces each with a read tool, a non-destructive write tool and a
destructive tool, and links the vendor API documentation from every tool that
takes a caller-built request body (required by the same page's "Reference API
docs in custom query tools") and from the other tools where a stable doc URL
exists.

---

## Requirements

1. No registered tool accepts both a read operation and a write operation.
2. Per resource: one read tool (list/get), one non-destructive write tool
   (create/update/add), one destructive tool (delete/remove/lock/reset). A
   resource with no destructive action gets no destructive tool.
3. Every new tool has a `title` and an accurate `readOnlyHint` or
   `destructiveHint` (in `annotations.py`).
4. Where an existing read tool already covers a read (`get_folder`,
   `search_folders`, `search_users`, `search_secretserver_local_users`), reuse
   it instead of adding a duplicate.
5. Old tool names are no longer registered. An old name in `enabled_tools`,
   `DELINEA_ENABLED_TOOLS` or the plugin's Custom tool list expands to its
   replacements, with a deprecation warning in the log.
6. Every tool that takes a freeform JSON `data` body names its target API
   endpoint and links the vendor API docs in its description.
7. Other tools link the API docs where a stable public URL exists.
8. StrongDM tools are split the same way.
9. Release as 3.0.0: `pyproject.toml`, plugin `version` and the pinned `uvx`
   version move together; CHANGELOG lists every rename.
10. Non-functional: tool descriptions stay narrow and accurate; no catch-all
    tool is introduced.

---

## Tool map

Annotation: RO = `readOnlyHint: true`; W = write, `destructiveHint: false`;
D = `destructiveHint: true`. Names are proposals; review in plan review.

### Secret Server (`delinea_mcp/tools.py`)

| Old tool (actions)                                      | New tools                                                                                      |
| ------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `role_management` (list, get, create, update)           | `get_roles` RO (list, or one by `role_id`); `create_or_update_role` W                          |
| `user_role_management` (get, add, remove)               | `get_user_roles` RO; `add_user_roles` W; `remove_user_roles` D                                 |
| `group_management` (get, list, create, delete)          | `get_groups` RO; `create_group` W; `delete_group` D                                            |
| `user_group_management` (get, add, remove)              | `get_user_groups` RO; `add_user_to_groups` W; `remove_user_from_groups` D                      |
| `group_role_management` (list, add, remove)             | `get_group_roles` RO; `add_group_roles` W; `remove_group_roles` D                              |
| `folder_management` (get, list, create, update, delete) | reads: existing `get_folder`, `search_folders`; `create_or_update_folder` W; `delete_folder` D |

### Secret Server local users (`delinea_mcp/secretserver_users.py`)

- `secretserver_local_user_management` (get, create, update, delete,
  list_sessions, reset_2fa, reset_password, lock_out): New tools:
  `get_secretserver_local_user` RO; `list_secretserver_user_sessions` RO;
  `create_or_update_secretserver_local_user` W;
  `delete_secretserver_local_user` D;
  `secretserver_local_user_security_action` D (reset_2fa, reset_password,
  lock_out: all writes)

### Delinea Platform (`delinea_mcp/user_platform_tools.py`)

| Old tool (actions)                                             | New tools                                                                                                             |
| -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `user_management` (get, create, update, delete, search)        | search: existing `search_users`; `get_platform_user` RO; `create_or_update_platform_user` W; `delete_platform_user` D |
| `platform_user_management` (deprecated alias)                  | dropped; maps to the `user_management` replacements                                                                   |
| `platform_role_management` (list, get, create, update, delete) | `get_platform_roles` RO; `create_or_update_platform_role` W; `delete_platform_role` D                                 |
| `platform_user_role_management` (list, add, remove)            | `get_platform_role_members` RO; `add_platform_role_members` W; `remove_platform_role_members` D                       |

### StrongDM (`delinea_mcp/strongdm_tools.py`)

Grants and role attachments keep the existing policy: they change security
posture, so they carry `destructiveHint` even when additive.

- `sdm_user_management` (list, get, create, onboard, suspend, reactivate,
  offboard, delete): New tools: `sdm_get_users` RO; `sdm_create_user` D
  (create, onboard: onboard attaches roles); `sdm_set_user_status` D (suspend,
  reactivate, offboard); `sdm_delete_user` D
- `sdm_role_management` (list, get, list_members, create, delete, add_user,
  remove_user): New tools: `sdm_get_roles` RO (list, get, list_members);
  `sdm_create_role` W; `sdm_delete_role` D; `sdm_add_role_member` D;
  `sdm_remove_role_member` D

Net: 14 tools removed, 39 added. Every tool on (StrongDM and reveal
included): 73. Plugin defaults (no StrongDM, reveal off): 55.

### Reviewed, unchanged

- `platform_reports`: `run` is an HTTP POST, but it is a query that changes
  nothing except a "View" audit entry. Same for
  `get_platform_role_members` (POSTs a RunReport). Kept read-only; noted as a
  review risk in the PR.
- `run_report`: POST + DELETE of a temporary report; already annotated as a
  non-destructive write, already links the API docs.
- `sdm_access_requests`: list/status, both reads.

---

## Verifiable Behaviors

- 1: Requirement: R1; Given: all tools enabled, StrongDM enabled; When:
  `list_tools()`; Then: no tool has an `action` parameter whose values span
  read and write; none of the 14 old names is listed; Verify by: unit
- 2: Requirement: R3; Given: all tools enabled; When: `list_tools()`; Then:
  every tool has `title` and annotation `title`; every tool has `readOnlyHint:
true` or explicit `destructiveHint`; Verify by: unit
- 3: Requirement: R2; Given: new read tool, e.g. `get_roles` with no id; When:
  called; Then: sends `GET /v1/roles` with paging; with `role_id`, `GET
/v1/roles/{id}`; Verify by: unit
- 4: Requirement: R2; Given: `create_or_update_role` with `role_id`; When:
  called; Then: `PATCH /v1/roles/{id}` then verifying `GET`; without
  `role_id`, `POST /v1/roles`; Verify by: unit
- 5: Requirement: R2; Given: each destructive tool; When: called with valid
  args; Then: issues only its delete/remove request; Verify by: unit
- 6: Requirement: R5; Given: `enabled_tools: ["role_management"]`; When:
  server starts; Then: `get_roles` and `create_or_update_role` registered;
  warning logged naming the replacements; Verify by: unit
- 7: Requirement: R5; Given: plugin Custom list `folder_management`; When:
  server starts; Then: `create_or_update_folder`, `delete_folder`,
  `get_folder`, `search_folders` registered; Verify by: unit
- 8: Requirement: R5; Given: read-only preset; When: server starts; Then: new
  RO tools included; no W or D tool included; Verify by: unit
- 9: Requirement: R6; Given: every tool whose schema has a `data` property;
  When: description inspected; Then: contains an `https://` doc URL and the
  endpoint path; Verify by: unit
- 10: Requirement: R9; Given: release files; When: inspected; Then:
  `pyproject.toml` version == plugin `version` == pinned `uvx` version ==
  3.0.0; Verify by: unit (extend existing plugin test)
- 11: Requirement: R1-R3; Given: live test tenant; When: each new SS/Platform
  tool called; Then: success response; writes clean up after themselves;
  Verify by: integration
- 12: Requirement: R7; Given: MCP Inspector `tools/list` against stdio server;
  When: run; Then: 71 tools with expected titles/annotations; Verify by:
  manual

Ambiguous rows for plan review:

- Row 7: should an old read-and-write name also expand to the reused existing
  read tools (`get_folder`, `search_folders`, `search_users`)? Proposed: yes,
  so the user keeps every capability the old tool had.
- Row 8: the read-only preset grows (role/group/membership reads join it).
  Proposed: accept; they are reads.

---

## Architecture Approach

Thin public wrappers over the existing logic. Each old function keeps its
name and its `action` dispatch, verification `GET`s and error handling, but
is no longer registered as a tool (changed from the planned private rename
during implementation: existing tests call the old names, and the contract
test stops them being registered again). Each new tool is a
short public function with its own signature and docstring that calls the
helper with a fixed action. The dispatch code is already tested; the wrappers
only fix the action, so no request logic is rewritten.

**Key Design Decisions:**

- Wrappers over rewrite: smallest diff, keeps the tested request paths and
  `{"result", "verification"}` shapes unchanged.
- Legacy-name map lives next to `TOOL_ANNOTATIONS` in `annotations.py`
  (`LEGACY_TOOL_NAMES: dict[str, tuple[str, ...]]`), expanded once in
  `server._select_tools`, so every allowlist source (config.json, env, plugin
  Custom list) goes through one place.
- Reuse existing reads rather than adding `list_folders`/`search_platform_users`
  duplicates.
- Doc URLs: Secret Server REST API reference
  (`https://docs.delinea.com/online-help/secret-server/api-scripting/rest-api/index.htm`,
  already cited by `run_report`), Delinea Platform API reference and StrongDM
  SDK reference. Platform and StrongDM URLs to be verified in Phase 0 before
  use; no unverified URL goes into a description.

---

## Implementation Plan

**TDD Approach:** Each phase follows Red-Green-Refactor. Write tests BEFORE
implementation code.

### Phase 0: Verify API doc URLs

**Complexity:** Simple (proposed)

- Fetch and confirm the Secret Server REST API reference, the Delinea Platform
  API reference (identity users, roles, reports) and the StrongDM Python SDK
  reference. Record the confirmed URLs in context.md.
- No code change.

### Phase 1: Guardrails and legacy-name expansion

**Complexity:** Moderate (proposed)

**Tests First (RED):**

- `tests/test_tool_contract.py` (new): with all tools + StrongDM registered,
  assert behaviors 1, 2 and 9 (no old names, every tool titled and hinted,
  every `data`-taking tool links docs).
- `tests/test_plugin_tool_defaults.py`: behaviors 6, 7, 8.

**Implementation (GREEN):**

- Files: `delinea_mcp/annotations.py`, `delinea_mcp/server.py`
- Add `LEGACY_TOOL_NAMES`; expand in `_select_tools`; log one warning per
  legacy name used.

**Verify:** contract tests stay RED until Phases 2-4 land (expected);
expansion tests GREEN; full suite otherwise green.

### Phase 2: Secret Server split

**Complexity:** Moderate (proposed)

**Tests First (RED):**

- Per new tool: request method/path/body test (behaviors 3-5), following the
  mocked-session pattern in `tests/test_management.py`.

**Implementation (GREEN):**

- Files: `delinea_mcp/tools.py`, `delinea_mcp/annotations.py`
- Rename the six helpers to private, add 16 wrappers, update `TOOLS`,
  `TOOL_ANNOTATIONS`, `TOOL_TITLES`.
- Move existing tests that call the old public names to the helpers or the
  new tools (`test_management.py`, `test_new_flows.py`,
  `test_tools_errors.py`, `test_coverage_fill.py`, `test_tool_guard.py`).

**Verify:** new tests GREEN; full suite green.

### Phase 3: Local users and Platform split

**Complexity:** Moderate (proposed)

- Same pattern for `secretserver_users.py` (5 tools) and
  `user_platform_tools.py` (9 tools; drop `platform_user_management`).
- Files: those two modules, `annotations.py`, `tests/test_user_platform_tools.py`,
  `tests/test_v2_review_fixes.py`, `tests/test_register.py`.

### Phase 4: StrongDM split

**Complexity:** Moderate (proposed)

- Same pattern for `strongdm_tools.py` (9 tools). The `confirm` + `comment`
  preview flow stays on every StrongDM write tool.
- Files: `strongdm_tools.py`, `annotations.py`, `tests/test_strongdm_tools.py`.

### Phase 5: Doc links, docs, release metadata

**Complexity:** Simple (proposed)

**Tests First (RED):** behavior 10 (versions 3.0.0).

**Implementation (GREEN):**

- Add endpoint + verified doc URL to each new tool's docstring (required for
  `data`-taking tools, Phase 1 contract test enforces it).
- Update `README.md` tool tables, `docs/claude-remote-connector.md`,
  `docs/openwebui-admin.md`, `docs/strongdm.md`, `AGENTS.md`, plugin
  `userConfig` descriptions if they name tools, plugin skills if they name
  tools.
- `CHANGELOG.md`: 3.0.0 entry with the old → new table.
- Bump `pyproject.toml`, plugin `version`, pinned `uvx` version; regenerate
  `uv.lock` / `requirements.txt` if the version is recorded there.

**Verify:** `claude plugin validate ./plugins/delinea`; `trunk fmt && trunk
check --fix`; full suite green.

### Phase 6: Live verification

**Complexity:** Moderate (proposed)

- Update `tests/integration/test_tools_live.py`,
  `tests/integration/test_platform_live.py`,
  `tests/integration/test_stdio_e2e_live.py` to the new names; run against the
  plugin test tenant (`.env.test-tenant.local`).
- MCP Inspector `tools/list` and one `tools/call` per new tool (behavior 12);
  install the plugin locally and confirm Claude Code shows every tool with its
  title.

---

## Testing Strategy

**Test Coverage Target:** 80%+ for new code.

**Unit Tests:** request shape per new tool; missing-id errors on get/update/
delete; legacy expansion from each allowlist source; contract test over the
full registered tool list.

**Integration Tests:** live tenant round trip for every Secret Server and
Platform tool (create → read → delete on throwaway objects). StrongDM covered
by unit tests only (no live StrongDM tenant).

**Manual Testing:** MCP Inspector; plugin install in Claude Code with
Read-only, All tools and Custom presets; confirm destructive tools prompt and
read tools don't.

---

## Security Considerations

- [x] **Authentication/Authorization:** unchanged sign-in. The split changes
      which calls Claude Code auto-approves: reads stay auto-approvable, deletes
      always prompt, creates/updates no longer carry the destructive hint. Review
      each W/D assignment.
- [x] **Input Validation:** existing helper validation (required ids, JSON
      parsing) runs unchanged under the wrappers; wrappers add none.
- [x] **Data Exposure:** password masking in local-user create/update/reset
      (`masked`) stays in the helper; must remain on the new write tools. Contract
      test does not cover this; existing masking tests must move with the tools.
- [x] **Secrets Management:** no change.
- [x] **API Security:** legacy expansion must never widen access: an old name
      expands only to its own replacements, and the read-only preset still
      selects by `readOnlyHint` only.

---

## Critical Paths

| Path / Component                                 | Why critical                                          | Review level     |
| ------------------------------------------------ | ----------------------------------------------------- | ---------------- |
| `delinea_mcp/annotations.py`                     | hints drive auto-approval in Claude                   | security-focused |
| `delinea_mcp/server.py` `_select_tools`          | allowlist and preset selection; must not widen access | security-focused |
| `delinea_mcp/secretserver_users.py`              | password masking on create/update/reset               | security-focused |
| `delinea_mcp/strongdm_tools.py`                  | access grants; confirm/comment gate                   | security-focused |
| `delinea_mcp/tools.py`, `user_platform_tools.py` | mechanical wrappers                                   | standard         |
| `plugins/delinea/.claude-plugin/plugin.json`     | version pin; directory reads it                       | standard         |

---

## Database Changes

N/A: no schema or stored data.

---

## Rollback Strategy

**Immediate (release fails):** don't publish; `release/current` only moves
after a successful PyPI publish, so the directory stays on 2.0.0.

**Delayed (issue after 3.0.0 ships):** publish 3.0.1 with the fix, or yank
3.0.0 from PyPI and reset the plugin pin to 2.0.0 in a new release commit
(`release/current` only fast-forwards, so rollback is a forward commit).
Users who pinned old names in config keep working via the legacy map either
way.

---

## Implementation Notes

Discovered while implementing; kept here because context.md is not tracked.

- Error guidance pointed Claude at removed tools (`_NOT_CONFIGURED_ERROR`,
  the Platform role 404 messages, the StrongDM revoke note, the `get_folder`
  description). All now name the new tools.
- Listing a folder's direct children was only possible through
  `folder_management("list", params=...)`. `search_folders` gained
  `parent_folder_id` so no capability is lost.
- `platform_user_management` (deprecated alias) was deleted with its two
  alias tests, not just unregistered.
- Platform role writes target endpoints the Platform doesn't serve
  (researched 2026-11-20 in ADO and live):
  - `/SaasManage/RemoveRole` never existed. The legacy Centrify controller
    (`CloudSuite:/Cloud/Saas/Cloud/controllers/manage.cs`) exposes
    `StoreRole`, `DeleteRole(Name=<role UUID>)` and `DeleteRoles([uuids])`;
    `Role.RemoveRole` is only an internal C# method.
  - The Platform identity service (`Identity:identity`,
    `src/Delinea.Identity.Api.Public/Controllers`) re-implements only part of
    that API: `UserMgmt`, `CDirectoryService`, `Report` and others, but no
    `SaasManage` or `Roles` controller. On the test tenant every
    `/identity/api/SaasManage/*` and `/identity/api/Roles/*` call, including
    the correct `DeleteRole`, returns an empty 404, the same as a made-up
    action name. So `create_or_update_platform_role`,
    `delete_platform_role` and `add/remove_platform_role_members` can never
    work on a Platform tenant; the "scope doesn't expose role mutations"
    message is wrong.
  - Platform roles live in the Permission service
    (`NewCo.Platform:Delinea.Permission`), served at `/permission/api/`:
    `roles` (POST create, GET search, GET/PUT/DELETE `{id}`, GET
    `{id}/members`, PATCH `{id}/permissions`) and `rolememberships` (POST,
    PATCH `{subjectId}/add-role` and `/remove-role`, GET/DELETE
    `{subjectId}`). Role IDs are role names. Live GETs return 200 with the
    tenant's real roles (Platform Admin, Platform User).
  - The current read tools (`role_searchbyname` report) list legacy identity
    roles such as "Everybody", which the Permission service treats as a
    group, not the Platform's roles.
  - Done 2026-11-20: the six Platform role tools now call the Permission
    API. Live run: role create, update, member add/remove, delete and the
    built-in-role 403 all pass on the test tenant; no objects left behind.
    `add_platform_role_members` falls back to `POST role-memberships` when
    a subject has no assignments yet (a new user already has Platform
    User, so the live run only exercises the PATCH path).
- Secret Server refuses role removals that would lock the service account
  out of Role Administration (`API_RoleAdministrationNoLockout`); the live
  test now allows that one error instead of ignoring every step's result.
- MCP Inspector reports a pre-existing schema-portability warning on
  `platform_reports.filters` (untyped list items). Unrelated to this item.

Verification run 2026-11-20: unit 539 passed; live 46 passed / 5 skipped
before the lockout fix, then the affected tests passed and no test objects
were left behind; stdio e2e 10 passed; MCP Inspector `tools/list` 55 tools,
all titled and hinted; `claude plugin validate` passed; trunk clean.

## Success Criteria

- [x] All requirements met
- [x] Contract test proves no mixed tool and full annotations
- [x] All tests pass; no regressions from baseline (478 → 539)
- [x] New code has 80%+ test coverage (every new tool has a request test; package 92%)
- [x] No tests skipped to hide failures
- [x] Security considerations addressed
- [x] Rollback strategy documented
- [x] Live tenant run passes for SS and Platform tools
- [x] `claude plugin validate` passes
- [x] Docs and CHANGELOG updated
- [ ] Plugin installed in Claude Code; destructive tools prompt (manual)
