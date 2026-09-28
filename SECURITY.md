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
- Credential scripts from `get_secret_environment_variable` and
  `set_secret_field_environment_variable` contain a short-lived Secret Server
  access token. With the local stdio transport they're written to a `0600`
  file in a `0700` directory, delete themselves when run, and expire after
  15 minutes; only the path is returned to the model.
- The server connects only to the Secret Server, Delinea Platform (and,
  when explicitly enabled, StrongDM) endpoints you configure. It sends no
  telemetry.
