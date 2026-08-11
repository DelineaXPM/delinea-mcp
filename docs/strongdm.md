# StrongDM (SDM) Tools

> **Experimental.** This backend is unit-tested against the strongdm SDK
> surface but has not yet been verified against a live SDM organization
> (the gated live suite lights up once `SDM_API_ACCESS_KEY` /
> `SDM_API_SECRET_KEY` are available). Expect rough edges.

Delinea completed the StrongDM acquisition in March 2026. delinea-mcp can
expose the SDM admin API as a third backend next to Secret Server and the
Delinea Platform, using compound tools that complete whole admin journeys
(resolve → act → verify) rather than wrapping single API calls.

## Installation

The StrongDM SDK (gRPC + HMAC request signing; there is no public REST
API) is an optional extra so the base install stays light:

```bash
pip install "delinea-mcp[strongdm]"
# or in a checkout:
uv sync --extra strongdm
```

Without the extra the tools still register and return a clear guidance
error when called.

## Credentials

Create an API key in the SDM Admin UI under **Principals → Tokens**. The
permission scope is chosen at key creation — grant only what the tools you
enable need. Then:

```bash
export SDM_API_ACCESS_KEY=auth-...
export SDM_API_SECRET_KEY=...
```

Non-secret settings go in `config.json`:

```json
{
  "strongdm_api_host": "app.strongdm.com:443"
}
```

Use `app.uk.strongdm.com:443` or `app.eu.strongdm.com:443` for UK/EU
control planes.

## Tools

| Tool                  | What it does                                                                                                                         |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `sdm_search`          | Find resources, accounts, or roles (SDM filter syntax or plain text).                                                                |
| `sdm_audit_access`    | Entitlement report from a user, resource, or role viewpoint: granted + requestable access, role memberships.                         |
| `sdm_grant_access`    | Grant a user a resource — time-boxed (just-in-time, auto-expiring) or standing — or attach a role. Confirm-gated with audit comment. |
| `sdm_revoke_access`   | Delete a user's direct grants on a resource; reports role-derived access that survives and how to remove it.                         |
| `sdm_user_management` | User lifecycle: create, onboard (create + roles), suspend, reactivate, offboard (suspend + enumerate leftovers), delete.             |
| `sdm_role_management` | Role lifecycle and membership (add/remove/list users).                                                                               |
| `sdm_resource_health` | Trigger a healthcheck and summarise per-node results for a resource.                                                                 |
| `sdm_access_requests` | List/inspect pending access requests.                                                                                                |
| `sdm_activity_report` | Query log (SQL bodies, durations, replayable sessions) + admin activity, scoped by user/resource/time.                               |
| `sdm_network_status`  | Gateway/relay fleet summary by state; surfaces dead or stopped nodes.                                                                |

Safety rails (house contract):

- Destructive/mutating actions require `confirm=True` **and** a non-empty
  `comment`; `confirm=False` returns a preview and performs no API call.
- Fuzzy name/email resolution that matches more than one object returns
  the candidate list and mutates nothing.
- Writes return a `verification` read-back of the changed object.
- Every list call is bounded (the SDK auto-paginates through the entire
  org otherwise).

## Known API asymmetry

Access requests can be **listed but not approved or denied** through the
SDM admin API — approvers act in the Admin UI or the Slack/Teams/Jira
integrations. `sdm_access_requests` says so in its output; to unblock
someone directly, `sdm_grant_access` with `duration_hours` creates the
equivalent time-boxed grant.

## Example connector allowlist

Audit-only profile:

```json
{
  "enabled_tools": [
    "sdm_search",
    "sdm_audit_access",
    "sdm_access_requests",
    "sdm_activity_report",
    "sdm_network_status"
  ]
}
```

## Live tests

```bash
export SDM_API_ACCESS_KEY=... SDM_API_SECRET_KEY=...
PYTHONPATH=. uv run pytest tests/integration/test_strongdm_live.py -v
```

Read-only; skips cleanly when credentials are absent.
