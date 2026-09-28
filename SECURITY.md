# Security policy

## Reporting a vulnerability

Please report security vulnerabilities privately through GitHub:
<https://github.com/DelineaXPM/delinea-mcp/security/advisories/new>.

Don't open a public issue for a vulnerability. Include the affected version,
the configuration (transport and auth mode), and steps to reproduce.

## Supported versions

Security fixes land on the latest release line (currently 2.x).

## Design notes for reviewers

- Password-type secret fields are masked in tool results. A plaintext value
  is released only through `reveal_secret_field`, after the user approves an
  MCP elicitation prompt sent by the server (configurable with
  `secret_reveal_mode`).
- With the local stdio transport, `get_secret_environment_variable` fetches
  the secret server-side and writes the username/password as shell
  assignments to a `0600` file in a `0700` directory; the file deletes itself
  when run and expires after 15 minutes, and only its path is returned to the
  model. `set_secret_field_environment_variable` uploads `file:` sources
  directly, or returns a command whose `0600` job file (holding a
  short-lived access token) is deleted as soon as it's read. Over HTTP
  transports both tools return scripts that call the API with a short-lived
  token.
- The plugin's `SessionStart` hook only checks whether `uvx` is on PATH.
  The `/delinea:setup` skill installs uv, through
  `plugins/delinea/scripts/setup-uv.sh` (no `sudo`), only after the user
  approves the install method.
- The server connects only to the Secret Server, Delinea Platform (and,
  when explicitly enabled, StrongDM) endpoints you configure. It sends no
  telemetry.
