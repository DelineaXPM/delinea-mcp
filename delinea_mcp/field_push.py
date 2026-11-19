"""Upload a locally held value into a Secret Server field.

Run by the command that ``set_secret_field_environment_variable`` returns
when the MCP server runs locally::

    <python> -I -m delinea_mcp.field_push <job.json>

The job file (0600, written by the server) holds the field URL, a
short-lived access token and the value's source. It is deleted as soon as
it's read. The value itself comes from an environment variable or a hidden
prompt on the user's terminal, so it never passes through the AI assistant.
Using the server's own Python means nothing else has to be installed.
"""

from __future__ import annotations

import getpass
import json
import os
import sys
import time
from pathlib import Path

import requests

from delinea_mcp.api import DelineaAPIError, raise_for_status, redact
from delinea_mcp.tls import use_system_trust_store


def _fail(message: str, code: int = 1) -> int:
    print(f"delinea-mcp: {message}", file=sys.stderr)
    return code


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    use_system_trust_store()
    if len(args) != 1:
        return _fail("usage: python -I -m delinea_mcp.field_push <job.json>", 2)
    job_path = Path(args[0])
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _fail(
            "this command was already used or has expired; ask the assistant "
            "to prepare it again"
        )
    finally:
        job_path.unlink(missing_ok=True)

    if time.time() > float(job.get("expires", 0)):
        return _fail("this command has expired; ask the assistant to prepare it again")

    field, secret_id = job["field"], job["secret_id"]
    source = job["source"]
    if source.startswith("env:"):
        name = source[4:]
        value = os.environ.get(name)
        if value is None:
            return _fail(f"environment variable {name} is not set in this shell")
    else:
        value = getpass.getpass(
            f"Value for field '{field}' on secret {secret_id} (input hidden): "
        )
    if not value:
        return _fail("empty value; nothing was changed")

    try:
        response = requests.put(
            job["url"],
            params=job.get("params") or None,
            json={"value": value},
            headers={"Authorization": f"Bearer {job['token']}"},
            timeout=30,
        )
        raise_for_status(response, f"Updating field '{field}' on secret {secret_id}")
    except DelineaAPIError as exc:
        hint = ""
        if exc.status_code == 401:
            hint = " The access token expired; ask the assistant to prepare the command again."
        return _fail(redact(f"{exc}{hint}", value))
    except requests.RequestException as exc:
        return _fail(redact(f"couldn't reach Secret Server: {exc}", value))
    print(f"Field '{field}' updated on secret {secret_id}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
