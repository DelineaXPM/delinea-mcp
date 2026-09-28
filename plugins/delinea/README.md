# Delinea Secret Server plugin for Claude

Connect Claude to [Delinea Secret Server](https://delinea.com/products/secret-server)
and the Delinea Platform. Claude can find and use privileged credentials
without the passwords ever entering the conversation, run SQL reports, and
manage folders, users, groups, roles and access requests.

## What's included

- **The Delinea MCP server** ([`delinea-mcp`](https://pypi.org/project/delinea-mcp/)
  on PyPI), started on your machine with `uvx delinea-mcp==2.0.0`.
- **no-secret-visibility skill**: teaches Claude to hand credentials straight
  to the programs that need them, and to reveal a password only after you
  approve it in your client.
- **building-reports skill**: teaches Claude to build Secret Server SQL
  reports from the tested examples and schema the server provides.
- **setup skill** (`/delinea:setup`): checks for uv, asks you once how to
  install it, then installs it, makes it available to Claude Code and
  downloads the server. The work is done by `scripts/setup-uv.sh`, a
  readable script that never uses `sudo`.
- **A startup check**: when a Claude Code session starts, a small script
  (`hooks/check-deps.sh`) looks for `uvx`. It installs nothing and prints
  nothing when `uvx` is found; otherwise it asks Claude to offer
  `/delinea:setup`.

## Requirements

<!-- markdownlint-disable MD013 -->

| Requirement                                                   | Why                                                                                                                           | How you get it                                                                                                                                        |
| ------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Claude Code                                                   | The MCP server runs on your machine. Claude chat on the web and mobile doesn't load local servers; the skills load everywhere | [Install Claude Code](https://code.claude.com/docs/en/setup)                                                                                          |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Provides `uvx`, which starts the server                                                                                       | Run `/delinea:setup`, or install it yourself: `brew install uv`, `winget install --id=astral-sh.uv -e`, `pipx install uv`, or uv's official installer |
| Python 3.13                                                   | The server's runtime                                                                                                          | uv downloads it automatically. Where downloads are blocked, install Python 3.13 yourself and uv uses it                                               |
| Network access to PyPI                                        | First start of each version downloads `delinea-mcp`                                                                           | Allow `pypi.org` and `files.pythonhosted.org`. Behind a TLS-inspecting proxy, set `UV_NATIVE_TLS=1`                                                   |
| A Delinea Secret Server account                               | Signing in (Cloud or on-premises)                                                                                             | We recommend a dedicated account with only the permissions you want Claude to have                                                                    |
| Optional: Delinea Platform tenant                             | Platform user and role tools                                                                                                  | A `<tenant>.delinea.app` tenant and service account                                                                                                   |

<!-- markdownlint-enable MD013 -->

Nothing else is needed. The credential tools use the server's own Python,
not curl, jq or other command-line tools.

## Configuration

When you enable the plugin, Claude Code asks for:

| Setting                                                 | Required | Notes                                                                                         |
| ------------------------------------------------------- | -------- | --------------------------------------------------------------------------------------------- |
| Secret Server URL                                       | Yes      | For example `https://example.secretservercloud.com`                                           |
| Username                                                | Yes      | The account the plugin signs in as, or the Platform client ID when a Platform hostname is set |
| Password                                                | Yes      | Stored in your operating system's secure credential store                                     |
| Platform hostname, service account, password, tenant ID | No       | Only for Platform-integrated tenants                                                          |

## How your secrets stay private

- `get_secret` masks password fields as `********`.
- `get_secret_environment_variable` writes a self-deleting file, readable
  only by you, that loads a credential into environment variables. Claude
  receives the file path, never the value.
- `set_secret_field_environment_variable` stores a value from a file,
  environment variable or hidden prompt on your machine, without Claude
  seeing it.
- `reveal_secret_field` shows a plaintext value only after you approve a
  confirmation prompt that the server sends to your client. Claude can't
  answer that prompt for you.

## Data and network use

The MCP server runs on your machine and connects only to the Secret Server
and Delinea Platform URLs you configure, using the credentials you provide.
It sends no data to Delinea or any other third party, and it collects no
telemetry. Tool results that you or Claude request are shown to Claude and
become part of your conversation. Credential handoff files are written
to a private temporary folder and are deleted when they're used, after 15
minutes, or when the server shuts down. The startup check only looks for
`uvx` on your machine; `/delinea:setup` installs nothing until you approve
it, and then contacts only your chosen package source (Homebrew, WinGet,
Scoop, PyPI, or astral.sh for uv's official installer).

Privacy policy: <https://delinea.com/privacy-policy>

## Support

- Documentation: <https://github.com/DelineaXPM/delinea-mcp#readme>
- Questions and bugs: <https://github.com/DelineaXPM/delinea-mcp/issues>
- Security vulnerabilities: report privately at
  <https://github.com/DelineaXPM/delinea-mcp/security/advisories/new>

StrongDM, a Delinea company, will be supported in a future release.
