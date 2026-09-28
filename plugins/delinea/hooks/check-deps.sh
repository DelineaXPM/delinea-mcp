#!/bin/sh
# Delinea plugin startup check. The Delinea MCP server starts through uvx
# (part of uv), which also provides the Python it runs on. This script only
# looks for uvx; it never installs or changes anything. It prints nothing
# when uvx is found, and otherwise leaves Claude a note to offer the
# consent-based /delinea:setup skill.

if command -v uvx >/dev/null 2>&1; then
    exit 0
fi

if [ -x ~/.local/bin/uvx ] || [ -x ~/.local/bin/uvx.exe ] || [ -x ~/.cargo/bin/uvx ] || [ -x /opt/homebrew/bin/uvx ] || [ -x /usr/local/bin/uvx ]; then
    echo "Delinea plugin: uv is installed but its folder isn't on Claude Code's PATH, so the Delinea MCP server can't start in Claude Code. Tell the user, and offer to run the /delinea:setup skill to fix it. Don't change anything without the user's approval."
    exit 0
fi

echo "Delinea plugin: uv (which provides uvx) isn't installed, so the Delinea MCP server can't start in Claude Code. Tell the user, and offer to run the /delinea:setup skill, which installs uv only after the user picks a method and approves it. Don't install anything without the user's approval."
exit 0
