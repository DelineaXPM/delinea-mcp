---
name: setup
description: Install and verify what the Delinea plugin needs to start its MCP server in Claude Code, which is uv (it also provides Python). Use when the Delinea MCP server fails to start or connect, when uv or uvx is missing or not on PATH, or when the user asks to set up or repair the Delinea plugin.
---

# Set up the Delinea plugin

The Delinea MCP server starts with `uvx delinea-mcp==2.0.0`. That needs one
tool on the machine: **uv**, which provides `uvx` and downloads the Python
version the server runs on. Nothing else is required. The credential
handoff tools use the server's own Python, not curl or jq.

**Never install or change anything without the user's explicit approval.**
Explain each step, show the exact command, and run it only after the user
agrees. Claude Code's permission prompt shows every command before it runs.

## 1. Check what's there

Run these read-only checks and report the results:

```bash
command -v uvx && uvx --version
ls ~/.local/bin/uvx ~/.cargo/bin/uvx /opt/homebrew/bin/uvx 2>/dev/null
```

On Windows, also check `where.exe uvx` and `%USERPROFILE%\.local\bin\uvx.exe`.

- **`uvx` runs**: skip to [step 4](#4-download-the-server-ahead-of-time).
- **`uvx` exists but isn't on PATH**: go to [step 3](#3-make-uvx-visible-to-claude-code).
- **Not installed**: go to step 2.

## 2. Install uv, with the user's choice

Ask the user which method to use. Offer only the ones available on their
machine, and recommend the first that applies:

<!-- markdownlint-disable MD013 -->

| Method                                         | macOS                                                    | Linux                                      | Windows                                                                               |
| ---------------------------------------------- | -------------------------------------------------------- | ------------------------------------------ | ------------------------------------------------------------------------------------- |
| Package manager (recommended)                  | `brew install uv`                                        | Your distribution's package, if it has one | `winget install --id=astral-sh.uv -e` or `scoop install main/uv`                      |
| Python package, if Python is already installed | `pipx install uv`, or `python3 -m pip install --user uv` | Same                                       | `pipx install uv`, or `py -m pip install --user uv`                                   |
| uv's official installer                        | `curl -LsSf https://astral.sh/uv/install.sh \| sh`       | Same                                       | `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` |

<!-- markdownlint-enable MD013 -->

- The official installer downloads a script from astral.sh, uv's
  publisher, and runs it. Say so plainly before asking.
- If the user declines every option, go to [No uv](#no-uv-install-the-package-directly).
- On a managed work machine, suggest the user checks whether IT provides uv
  through their software portal first.

After installing, confirm with `uvx --version`.

## 3. Make `uvx` visible to Claude Code

Claude Code starts the MCP server with the PATH it was launched with. If
uv was just installed, or lives in a folder that isn't on that PATH:

1. Tell the user which folder holds `uvx`. It's usually `~/.local/bin`,
   or `%USERPROFILE%\.local\bin` on Windows.
2. Offer to add it to their shell profile (`~/.zshrc`, `~/.bashrc`, or the
   Windows user PATH). Show the exact line before changing anything.
3. Ask the user to quit Claude Code and start it again from a new terminal,
   so it picks up the new PATH.

## 4. Download the server ahead of time

The first start downloads the server package from PyPI and, if needed,
Python 3.13. Doing that now surfaces network problems before the user
relies on the plugin:

```bash
uvx delinea-mcp==2.0.0 --help
```

If it fails:

- **Proxy or TLS errors on a corporate network**: uv honors `HTTPS_PROXY`.
  Setting `UV_NATIVE_TLS=1` in the user's environment makes uv trust the
  operating system's certificate store. The variable must be set where
  Claude Code is started.
- **Python downloads blocked** (for example `UV_PYTHON_DOWNLOADS=never`):
  install Python 3.13 from python.org or the system package manager. uv uses
  it automatically.
- **PyPI blocked**: the user's IT team needs to allow `pypi.org` and
  `files.pythonhosted.org`, or provide an internal package mirror.

## 5. Reconnect

In Claude Code, run `/mcp` and reconnect the **delinea** server, or restart
Claude Code. Then call the `health_check` tool to confirm the connection.

If sign-in fails, the settings are wrong rather than the install. The user
can re-enter them with `/plugin` → Delinea → configure.

## No uv: install the package directly

Offer this only if the user declines to install uv. It needs Python 3.13 or
newer. The plugin's own server entry keeps failing, so the user should
disable it in `/mcp`.

1. Create a virtual environment and install the package:

   ```bash
   python3 -m venv ~/.delinea-mcp
   ~/.delinea-mcp/bin/pip install delinea-mcp==2.0.0
   ```

   On Windows: `py -3.13 -m venv %USERPROFILE%\.delinea-mcp`, then
   `%USERPROFILE%\.delinea-mcp\Scripts\pip install delinea-mcp==2.0.0`.

2. Register the server. **The user runs this themselves**, because it
   includes their password. Don't ask for the password in the chat:

   ```bash
   claude mcp add delinea-local --scope user \
     -e DELINEA_BASE_URL=https://example.secretservercloud.com \
     -e DELINEA_USERNAME=<username> \
     -e DELINEA_PASSWORD=<password> \
     -- ~/.delinea-mcp/bin/delinea-mcp
   ```

   Warn the user that this stores the password in plain text in Claude
   Code's user configuration. The plugin keeps it in the operating system's
   credential store, which is why the plugin with uv is the recommended
   setup.
