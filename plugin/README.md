# Delinea plugin for Claude Code

This plugin connects Claude Code to Delinea Secret Server and Delinea Platform through the
delinea-mcp server. The server runs locally on your machine via `uvx`, installed from PyPI, and
talks only to the Secret Server and Platform hosts you configure. By default it exposes only the
read-only tools; set the enabled tools option to opt in to more.

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
