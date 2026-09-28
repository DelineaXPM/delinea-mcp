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

## Requirements

- Claude Code. The MCP server runs locally, so it isn't loaded in Claude chat
  on the web or mobile; the skills load everywhere.
- [uv](https://docs.astral.sh/uv/getting-started/installation/), which
  provides `uvx`.
- A Delinea Secret Server (Cloud or on-premises) account. We recommend a
  dedicated account with only the permissions you want Claude to have.
- Optional: a Delinea Platform tenant (`<tenant>.delinea.app`) and service
  account for the Platform user and role tools.

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
- `get_secret_environment_variable` writes a self-deleting script, readable
  only by you, that loads a credential into environment variables. Claude
  receives the file path, not the value or the access token inside it.
- `reveal_secret_field` shows a plaintext value only after you approve a
  confirmation prompt that the server sends to your client. Claude can't
  answer that prompt for you.

## Data and network use

The MCP server runs on your machine and connects only to the Secret Server
and Delinea Platform URLs you configure, using the credentials you provide.
It sends no data to Delinea or any other third party, and it collects no
telemetry. Tool results that you or Claude request are shown to Claude and
become part of your conversation. Generated credential scripts are written
to a private temporary folder and are deleted when they run, after 15
minutes, or when the server shuts down.

Privacy policy: <https://delinea.com/privacy-policy>

## Support

- Documentation: <https://github.com/DelineaXPM/delinea-mcp#readme>
- Questions and bugs: <https://github.com/DelineaXPM/delinea-mcp/issues>
- Security vulnerabilities: report privately at
  <https://github.com/DelineaXPM/delinea-mcp/security/advisories/new>

StrongDM, a Delinea company, will be supported in a future release.
