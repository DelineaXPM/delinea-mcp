# Delinea Secret Server plugin for Claude

Connect Claude to [Delinea Secret Server](https://delinea.com/products/secret-server)
and the Delinea Platform. Claude can find and use privileged credentials
without the passwords ever entering the conversation, run SQL reports, and
manage folders, users, groups, roles and access requests.

## What's included

- **The Delinea MCP server** ([`delinea-mcp`](https://pypi.org/project/delinea-mcp/)
  on PyPI), started on your machine with `uvx --no-config delinea-mcp==3.0.0`.
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
  (`hooks/check-deps.sh`) checks that the plugin's settings were entered
  and that `uvx` can be found. It installs nothing and prints nothing when
  all is well; otherwise it tells Claude how to fix it, such as offering
  `/delinea:setup`.

## Requirements

<!-- markdownlint-disable MD013 -->

| Requirement                                                   | Why                                                                                                                           | How you get it                                                                                                                                                              |
| ------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Claude Code 2.1.271 or later                                  | The MCP server runs on your machine. Claude chat on the web and mobile doesn't load local servers; the skills load everywhere | [Install Claude Code](https://code.claude.com/docs/en/setup). Earlier versions can't show the plugin's Tool access picker                                                   |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Provides `uvx`, which starts the server                                                                                       | Run `/delinea:setup`, or install it yourself: `brew install uv`, `winget install --id=astral-sh.uv -e`, `pipx install uv`, or uv's official installer                       |
| Python 3.13                                                   | The server's runtime                                                                                                          | If Python 3.13 isn't installed, uv downloads it from GitHub (`astral-sh/python-build-standalone`). Where downloads are blocked, install Python 3.13 yourself and uv uses it |
| Network access to PyPI                                        | First start of each version downloads `delinea-mcp`                                                                           | Allow `pypi.org` and `files.pythonhosted.org`. Behind a TLS-inspecting proxy, set `UV_NATIVE_TLS=1`                                                                         |
| A Delinea Platform tenant and service account                 | Signing in. The plugin finds your Secret Server from the Platform                                                             | A `<tenant>.delinea.app` tenant and a service account with only the permissions you want Claude to have                                                                     |
| Or: a standalone Secret Server account                        | Only for a Secret Server that isn't on the Delinea Platform (Cloud or on-premises)                                            | A dedicated **Application Account**. Secret Server 12.1+ blocks password sign-in for regular users by default                                                               |

<!-- markdownlint-enable MD013 -->

Nothing else is needed. The credential tools use the server's own Python,
not curl, jq or other command-line tools.

## Platform support

macOS and Linux are supported. **Windows support is experimental**: the
server and skills are platform-neutral, but the startup check and the
`/delinea:setup` helper are shell scripts that run under Git Bash and
haven't been verified on Windows yet.

## Configuration

When you enable the plugin, Claude Code asks for its settings. The required
ones come first, titled **Required:**; everything below them is titled
**Optional:** and can be left as it is.

### Required settings

<!-- markdownlint-disable MD013 -->

| Setting              | Notes                                                                                                                                                                 |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Delinea Platform URL | For example `https://example.delinea.app`. The plugin signs in through the Platform and looks up your Secret Server from it, so you don't enter a Secret Server URL   |
| Client ID            | Your Platform service account's client ID                                                                                                                             |
| Client secret        | Stored in your operating system's credential store                                                                                                                    |
| Tool access          | **Read-only**, **All tools** (the default) or **Custom**. See below                                                                                                   |
| Custom tool list     | Only with **Custom** tool access: comma-separated tool names, for example `get_secret,search_secrets,get_secret_environment_variable`. Ignored with the other choices |

### Optional settings

| Setting                                      | Notes                                                                                                                                                         |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Secret Server URL override                   | Leave empty. Set it to use a different vault than the one your Platform tenant reports, or for a standalone Secret Server (then leave the Platform URL empty) |
| Allow revealing passwords                    | Off by default. When on, each reveal still needs your approval                                                                                                |
| Separate Platform service account and secret | Leave empty to use the client ID above for the Platform user, role and report tools too                                                                       |
| Platform secondary tenant ID                 | Leave empty unless your service account must act inside a specific child tenant                                                                               |

<!-- markdownlint-enable MD013 -->

### Tool access

- **Read-only**: search and browse secrets, folders, users and roles; view
  secrets with passwords masked; run Secret Server and Platform reports; and
  hand credentials to programs without showing them
  (`get_secret_environment_variable`). Nothing in Secret Server or the
  Platform is changed. (A Secret Server report runs as a temporary report
  that's deleted afterwards. A secret that requires check-out is checked out
  and back in when its credential is handed over, so a secret set to change
  its password on check-in gets a new password.)
- **All tools**: everything in read-only, plus creating, updating, rotating
  and deleting secrets, folders, users, groups and roles, and answering
  access requests.
- **Custom**: only the tools in **Custom tool list**. If the list is empty,
  the plugin falls back to read-only.

**Allow revealing passwords** is separate: no choice above shows a password
in plaintext unless that setting is on.

## How your secrets stay private

- `get_secret` masks password fields as `********`.
- `get_secret_environment_variable` writes a self-deleting file, readable
  only by you, that loads a credential into environment variables. Claude
  receives the file path, never the value.
- `set_secret_field_environment_variable` stores a value from a file,
  environment variable or hidden prompt on your machine, without Claude
  seeing it.
- Showing a password in plaintext is **off by default**. If you turn on
  **Allow revealing passwords**, `reveal_secret_field` shows a value only
  after you approve a confirmation prompt that the server sends to your
  client.

## Privacy policy

The MCP server runs on your machine and connects only to the Delinea
Platform URL you configure and the Secret Server that your Platform tenant
reports (or the Secret Server URL you set instead), using the credentials
you provide.
It sends no data to Delinea or any other third party, and it collects no
telemetry. Tool results that you or Claude request are shown to Claude and
become part of your conversation. To start the server, `uvx` downloads
`delinea-mcp` from PyPI the first time each version runs. If Python 3.13
isn't installed, `uvx` also downloads it from GitHub. Credential handoff
files are written to a private temporary folder and are deleted when
they're used, after 15 minutes, or when the server shuts down. The startup check only looks for
`uvx` on your machine; `/delinea:setup` installs nothing until you approve
it, and then contacts only your chosen package source (Homebrew, WinGet,
Scoop, PyPI, or astral.sh for uv's official installer).

Delinea's full privacy policy, including how to contact Delinea about
privacy, is at <https://delinea.com/privacy-policy>.

## Support

- Documentation: <https://github.com/DelineaXPM/delinea-mcp#readme>
- Questions and bugs: <https://github.com/DelineaXPM/delinea-mcp/issues>
- Security vulnerabilities: report privately at
  <https://github.com/DelineaXPM/delinea-mcp/security/advisories/new>

StrongDM, a Delinea company, will be supported in a future release.
