#!/usr/bin/env bash
# Simple setup script for running the Delinea MCP server locally.

set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv via pip" >&2
    pip install uv
fi

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment" >&2
    uv venv
fi

echo "Activating virtual environment" >&2
source .venv/bin/activate

echo "Installing Python requirements" >&2
uv pip install -r requirements.txt

if ! command -v node >/dev/null 2>&1; then
    echo "Node.js not found - attempting apt install" >&2
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update && sudo apt-get install -y nodejs npm
    else
        echo "Please install Node.js and npm manually" >&2
    fi
fi

echo "Installation complete" >&2
