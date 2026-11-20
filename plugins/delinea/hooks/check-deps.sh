#!/bin/sh
# Delinea plugin startup check. The Delinea MCP server starts through uvx
# (part of uv), which also provides the Python it runs on. This script only
# checks that the plugin's settings were entered and that uvx can be found;
# it never installs or changes anything. It prints nothing when all is well,
# and otherwise leaves Claude a note on how to fix it.

# Claude Code exports each plugin setting as CLAUDE_PLUGIN_OPTION_<KEY>. If
# the required connection settings were never entered, the Delinea server
# is left out or can't sign in, so say how to fix it. The Platform URL is
# needed unless a standalone Secret Server URL is set instead. Only
# non-sensitive settings are read here.
if { [ -z "${CLAUDE_PLUGIN_OPTION_PLATFORM_HOSTNAME-}" ] && [ -z "${CLAUDE_PLUGIN_OPTION_DELINEA_BASE_URL-}" ]; } || [ -z "${CLAUDE_PLUGIN_OPTION_DELINEA_USERNAME-}" ]; then
    echo "Delinea plugin: the required settings (Delinea Platform URL and client ID) haven't been set, so the Delinea MCP server can't connect. To fix it, open /plugin, choose the Delinea plugin and fill in the settings marked Required (the client secret is stored in the operating system's credential store), then run /mcp to connect."
fi

if command -v uvx >/dev/null 2>&1; then
    exit 0
fi

if [ -x ~/.local/bin/uvx ] || [ -x ~/.local/bin/uvx.exe ] || [ -x ~/.cargo/bin/uvx ] || [ -x /opt/homebrew/bin/uvx ] || [ -x /usr/local/bin/uvx ]; then
    echo "Delinea plugin: uv is installed but its folder isn't on Claude Code's PATH, so the Delinea MCP server can't start in Claude Code. The /delinea:setup skill can make uv available, after the user approves."
    exit 0
fi

echo "Delinea plugin: uv (which provides uvx) isn't installed, so the Delinea MCP server can't start in Claude Code. The /delinea:setup skill can install uv and prepare the server, after the user approves."
exit 0
