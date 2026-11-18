# Delinea plugin for Claude Code

This plugin connects Claude Code to Delinea Secret Server and Delinea Platform through the
delinea-mcp server. The server runs locally on your machine via `uvx`, installed from PyPI, and
talks only to the Secret Server and Platform hosts you configure. By default it exposes only the
read-only tools; set the enabled tools option to opt in to more.

## What the plugin does

It gives Claude Code Secret Server and Delinea Platform tools: search and read secrets and folders,
look up users, run reports, and (if you enable them) make changes. The MCP server runs locally over
stdio. Nothing is hosted by Delinea for this plugin.

## Requirements

- A Secret Server **Application Account**: a non-interactive API user that cannot sign in to the UI
  and is exempt from Secret Server's "Prevent direct API authentication" setting, which blocks
  password-grant API logins for interactive users. Give it only the permissions you want Claude to
  have.
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) installed, which provides `uvx`.
- Network access to PyPI on first launch (see [Network destinations](#network-destinations)).

## Install

In a Claude Code session:

```text
/plugin marketplace add DelineaXPM/delinea-mcp
/plugin install delinea@delinea
```

Claude Code prompts for each setting. Passwords are stored in your OS keychain.

### Scripted install

Pass settings with `--config` to install without prompts. Leave the passwords out so they don't
land in shell history; Claude Code prompts for them.

```bash
claude plugin marketplace add DelineaXPM/delinea-mcp
claude plugin install delinea@delinea \
  --config secret_server_url=https://tenant.secretservercloud.com \
  --config secret_server_username=mcp-app-account \
  --config platform_hostname=tenant.delinea.app
```

## Settings

| Key                         | Title                                | Required | Sensitive (OS keychain) |
| --------------------------- | ------------------------------------ | -------- | ----------------------- |
| `secret_server_url`         | Secret Server URL                    | Yes      | No                      |
| `secret_server_username`    | Secret Server application account    | Yes      | No                      |
| `secret_server_password`    | Secret Server password               | Yes      | Yes                     |
| `platform_hostname`         | Platform hostname (optional)         | No       | No                      |
| `platform_service_account`  | Platform service account (optional)  | No       | No                      |
| `platform_service_password` | Platform service password (optional) | No       | Yes                     |
| `platform_tenant_id`        | Platform tenant ID (optional)        | No       | No                      |
| `enabled_tools`             | Enabled tools                        | No       | No                      |

Setting `platform_hostname` (for example `<your-platform-hostname>`) makes Secret Server login go
through Delinea Platform and enables the Platform tools. The Platform user tools also need the
service account and service password; the tenant ID is optional.

## Default tools

Only read-only tools are enabled unless you set `enabled_tools`:

`check_secret_template`, `check_secret_template_field`, `fetch`, `get_folder`, `get_inbox_messages`,
`get_pending_access_requests`, `get_secret`, `get_secret_template_field`, `health_check`,
`list_example_reports`, `platform_reports`, `search`, `search_folders`, `search_secrets`,
`search_secretserver_local_users`, `search_users`.

Read-only does not mean secret-free: `get_secret` and `fetch` return secret field values, including
passwords, to Claude. Restrict what Claude can read through the Application Account's Secret Server
permissions, or leave `get_secret` out of `enabled_tools`.

The `sdm_*` StrongDM tools are also listed as read-only, but they need the optional StrongDM
package, which this plugin does not install, so they only return a setup message.

To widen the set, put a comma-separated list of tool names in `enabled_tools`, for example
`get_secret,search_secrets,update_secret_fields`. Run `claude plugin configure delinea` to change it.

> [!WARNING]
> Write and destructive tools can change or delete secrets, folders, groups, roles, and users.
> Enable only the ones you need, and use an Application Account whose permissions match.

## Network destinations

The plugin and server contact only these hosts:

| Destination                                     | When                                                 | Purpose                                              |
| ----------------------------------------------- | ---------------------------------------------------- | ---------------------------------------------------- |
| Your Secret Server URL (`secret_server_url`)    | Always                                               | Sign in and all Secret Server API calls              |
| Your Platform hostname (`platform_hostname`)    | Only if set                                          | Platform sign-in, Platform user and report API calls |
| `pypi.org`, `files.pythonhosted.org`            | Launch, when `uvx` needs to fetch the pinned package | Download `delinea-mcp` and its dependencies          |
| `github.com` (python-build-standalone releases) | Launch, only if Python 3.13 is not installed         | `uv` downloads a Python interpreter                  |

The server sends no telemetry, and nothing else is contacted. StrongDM (`SDM_API_*`) is not
contacted because its SDK is not installed by the plugin.

## Troubleshooting

- Run `/mcp` in Claude Code to see whether the `delinea` server is connected or failed.
- Run `claude plugin configure delinea` to view and change settings.
- A `Secret Server authentication failed` error usually means the account is not an Application
  Account, or the URL or password is wrong.
