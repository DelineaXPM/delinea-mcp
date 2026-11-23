---
name: setup
description: Install and verify what the Delinea plugin needs to start its MCP server in Claude Code, which is uv (it also provides Python). Use when the Delinea MCP server fails to start or connect, when uv or uvx is missing or not on PATH, or when the user asks to set up or repair the Delinea plugin.
---

# Set up the Delinea plugin

The Delinea MCP server starts with `uvx --no-config delinea-mcp==3.0.0`. That needs one
tool: **uv**, which provides `uvx` and downloads the Python version the
server runs on. Nothing else is required.

All the work is done by the plugin's helper script,
`${CLAUDE_PLUGIN_ROOT}/scripts/setup-uv.sh`. It never uses `sudo`. Ask the
user **once** before installing anything; after they approve, run the
remaining steps without asking again.

## 1. Check the machine (read-only, no approval needed)

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/setup-uv.sh" check
```

It prints `uvx=`, `uvx_on_path=`, `uv_version=`, `methods=` (the install
methods this machine supports, most recommended first) and `recommended=`:
`none` when uv is ready, `link` when it's installed but not on PATH, otherwise
the install method to offer first.

- `uvx_on_path=yes`: uv is fine. Skip to [step 4](#4-download-the-server).
- `uvx` is set but `uvx_on_path=no`: ask the user whether to make it
  available to Claude Code, then run only the `link` command in step 3.
- `uvx` is empty: go to step 2.
- `methods` is empty: the machine has no supported package manager, no curl
  or wget, and no Python. Tell the user, and point them to
  <https://docs.astral.sh/uv/getting-started/installation/>.

## 2. Ask once

Ask the user a single question. Offer the `recommended` method first, the
other entries from `methods` as alternatives, and "I'll install it myself".
Describe each option in one line so the user knows what it changes:

<!-- markdownlint-disable MD013 -->

| Method     | What it does                                                                                                                                      |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `brew`     | Installs uv with Homebrew                                                                                                                         |
| `winget`   | Installs uv with WinGet, accepting the package and source agreements                                                                              |
| `scoop`    | Installs uv with Scoop                                                                                                                            |
| `pipx`     | Installs uv from PyPI with pipx                                                                                                                   |
| `pip-venv` | Installs uv from PyPI into a private folder (`~/.local/share/delinea-uv`) and links it into `~/.local/bin`. No admin rights or other tools needed |
| `official` | Downloads uv's official installer from astral.sh and runs it; it installs to `~/.local/bin` and adds that folder to your shell profile            |

<!-- markdownlint-enable MD013 -->

Make it clear that approving also covers steps 3 and 4. If the user picks
"I'll install it myself", show the commands from
[Manual install](#manual-install) and stop.

## 3. Install and link

After the user approves, run:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/setup-uv.sh" install <method>
sh "${CLAUDE_PLUGIN_ROOT}/scripts/setup-uv.sh" link
```

`link` puts `uvx` into a folder that's already on PATH, when one is
writable, so Claude Code can start the server without a restart. If it
exits with code 3, no such folder exists: tell the user to quit Claude Code
and start it again from a new terminal. On Windows, `link` explains how to
add the folder to the user PATH instead.

## 4. Download the server

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/setup-uv.sh" prewarm delinea-mcp==3.0.0
```

This downloads the server package and, if needed, Python 3.13, so network
problems show up now. If it fails:

- **Proxy or TLS errors on a corporate network**: uv honors `HTTPS_PROXY`,
  and `UV_NATIVE_TLS=1` makes it trust the operating system's certificate
  store. Both must be set in the environment Claude Code starts from.
- **Python downloads blocked**: install Python 3.13 from python.org or the
  system package manager. uv uses it automatically.
- **PyPI blocked**: IT needs to allow `pypi.org` and
  `files.pythonhosted.org`, or provide a package mirror.

## 5. Reconnect

Ask the user to run `/mcp` and reconnect the **delinea** server, or to
restart Claude Code if step 3 said so. Then call `health_check` to confirm
the connection. If sign-in fails, the settings are wrong rather than the
install: the user can re-enter them with `/plugin` → Delinea → configure.

## Manual install

<!-- markdownlint-disable MD013 -->

| Method             | macOS / Linux                                      | Windows                                                                               |
| ------------------ | -------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Package manager    | `brew install uv`                                  | `winget install --id=astral-sh.uv -e` or `scoop install main/uv`                      |
| Python package     | `pipx install uv`                                  | `pipx install uv`                                                                     |
| Official installer | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` |

<!-- markdownlint-enable MD013 -->

## No uv: install the package directly

Offer this only if the user refuses uv entirely. It needs Python 3.13 or
newer, and the plugin's own server entry keeps failing, so the user should
disable it in `/mcp`.

1. Install the package into a virtual environment:

   ```bash
   python3 -I -m venv ~/.delinea-mcp
   ~/.delinea-mcp/bin/pip install delinea-mcp==3.0.0
   ```

2. Register the server. **The user runs this themselves**, because it
   includes their password; don't ask for the password in the chat:

   ```bash
   claude mcp add delinea-local --scope user \
     -e DELINEA_MCP_PLUGIN=1 \
     -e PLATFORM_HOSTNAME=example.delinea.app \
     -e DELINEA_USERNAME=<client-id> \
     -e DELINEA_PASSWORD=<client-secret> \
     -- ~/.delinea-mcp/bin/delinea-mcp
   ```

   Keep `DELINEA_MCP_PLUGIN=1`: like the plugin, it makes the server ignore
   config files in whatever project Claude Code opens, so a project can't
   redirect the sign-in. For a standalone Secret Server without the Delinea
   Platform, replace the `PLATFORM_HOSTNAME` line with
   `-e DELINEA_BASE_URL=https://example.secretservercloud.com` and use that
   account's username and password.

   Warn the user that this stores the password in plain text in Claude
   Code's user configuration, unlike the plugin, which keeps it in the
   operating system's credential store.
