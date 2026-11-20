"""Live end-to-end test of the server exactly as the Claude Code plugin runs it.

Each scenario launches ``uvx --no-config --python 3.13 --from <repo>
delinea-mcp`` in an empty directory with env-only settings and drives it
through a real MCP client (both protocol generations), against the tenant in
``DELINEA_BASE_URL``. Assertions use counts, masks and lengths only, so no
secret value or token is ever printed.

Needs ``DELINEA_BASE_URL``, ``DELINEA_USERNAME``, ``DELINEA_PASSWORD`` and
``LIVE_SECRET_ID`` (a secret with username and password fields), plus
``uvx`` on PATH. Set ``DELINEA_E2E_PACKAGE=delinea-mcp==<version>`` to test
a published release instead of the repo source. Writes are attempted only on
the ``notes`` field and
pass either when they succeed or when the tenant refuses them with an
actionable error that doesn't echo the value.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from delinea_mcp.api import platform_host

REPO = Path(__file__).resolve().parents[2]
NEEDED = ("DELINEA_BASE_URL", "DELINEA_USERNAME", "DELINEA_PASSWORD", "LIVE_SECRET_ID")

pytestmark = pytest.mark.skipif(
    not all(os.getenv(v) for v in NEEDED) or shutil.which("uvx") is None,
    reason=f"needs {', '.join(NEEDED)} and uvx",
)

WRITE_TOOLS = {
    "delete_folder",
    "update_folder",
    "update_secret_fields",
    "delete_platform_user",
}


def _server_env(**extra: str) -> dict[str, str]:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ["HOME"],
        "DELINEA_BASE_URL": os.environ["DELINEA_BASE_URL"],
        "DELINEA_USERNAME": os.environ["DELINEA_USERNAME"],
        "DELINEA_PASSWORD": os.environ["DELINEA_PASSWORD"],
        # Empty optional plugin settings, exactly as userConfig substitutes them;
        # LIVE_SS_VIA_PLATFORM=1 signs in through the Platform instead.
        "PLATFORM_HOSTNAME": (
            os.environ.get("PLATFORM_HOSTNAME", "")
            if os.getenv("LIVE_SS_VIA_PLATFORM") == "1"
            else ""
        ),
        "PLATFORM_SERVICE_ACCOUNT": "",
        "PLATFORM_SERVICE_PASSWORD": "",
        "PLATFORM_TENANT_ID": "",
    }
    env.update(extra)
    return env


def _run(scenario, *, mode: str = "auto", answer: str = "accept", **env: str):
    from mcp import types
    from mcp.client import Client
    from mcp.client.stdio import StdioServerParameters, stdio_client

    # DELINEA_E2E_PACKAGE (e.g. "delinea-mcp==2.0.0rc1") tests a published
    # release from PyPI instead of the repo source.
    package = os.getenv("DELINEA_E2E_PACKAGE")
    source = [package] if package else ["--from", str(REPO), "delinea-mcp"]
    params = StdioServerParameters(
        command="uvx",
        args=[
            "--quiet",
            "--no-config",
            "--python",
            "3.13",
            "--refresh-package",
            "delinea-mcp",
            *source,
        ],
        env=_server_env(**env),
        cwd=tempfile.mkdtemp(prefix="dmcp-e2e-"),
    )
    prompts: list[str] = []

    async def elicit(context, request):
        prompts.append(request.message)
        if answer == "accept":
            return types.ElicitResult(action="accept", content={"confirm": True})
        return types.ElicitResult(action="decline")

    async def main():
        async with Client(
            stdio_client(params), elicitation_callback=elicit, mode=mode
        ) as client:

            async def call(name, args=None):
                result = await client.call_tool(name, args or {})
                text = result.content[0].text if result.content else "{}"
                try:
                    return json.loads(text)
                except ValueError:
                    return text

            tools = {t.name: t for t in (await client.list_tools()).tools}
            return await scenario(call, tools, prompts)

    return asyncio.run(main())


SID = int(os.getenv("LIVE_SECRET_ID", "0"))


def test_plugin_mode_defaults():
    """Plugin mode: every tool by default, reveal off, masked results."""

    async def scenario(call, tools, prompts):
        assert all(t.title and t.annotations for t in tools.values())
        assert {"get_secret_environment_variable", "run_report"} <= set(tools)
        assert WRITE_TOOLS <= set(tools)
        assert "reveal_secret_field" not in tools
        assert not any(n.startswith(("sdm_", "ai_")) for n in tools)
        secret = await call("get_secret", {"id": SID})
        assert "disabled" in secret.get("maskedNote", "")

    _run(scenario, DELINEA_MCP_PLUGIN="1")


def test_plugin_enabled_tools_setting_narrows():
    async def scenario(call, tools, prompts):
        assert set(tools) == {"get_secret", "search_secrets"}

    _run(
        scenario,
        DELINEA_MCP_PLUGIN="1",
        DELINEA_ENABLED_TOOLS="get_secret,search_secrets",
    )


def test_plugin_custom_preset_uses_tool_list():
    async def scenario(call, tools, prompts):
        assert set(tools) == {"get_secret", "search_secrets"}

    _run(
        scenario,
        DELINEA_MCP_PLUGIN="1",
        DELINEA_TOOL_PRESET="Custom",
        DELINEA_ENABLED_TOOLS="get_secret,search_secrets",
    )


@pytest.mark.skipif(
    os.getenv("LIVE_SS_VIA_PLATFORM") != "1",
    reason="needs a vault on the Delinea Platform (LIVE_SS_VIA_PLATFORM=1)",
)
def test_plugin_platform_url_only_read_only_preset():
    """The default plugin setup: Platform URL only, vault found from it."""

    async def scenario(call, tools, prompts):
        assert "get_secret" in tools and "run_report" in tools
        assert not WRITE_TOOLS & set(tools)
        assert "error" not in await call("health_check")
        secret = await call("get_secret", {"id": SID})
        assert secret.get("id") == SID

    _run(
        scenario,
        DELINEA_MCP_PLUGIN="1",
        DELINEA_BASE_URL="",
        # Pasted as a full URL, as users do; works whether the env holds a
        # bare host or a URL.
        PLATFORM_HOSTNAME=f"https://{platform_host(os.getenv('PLATFORM_HOSTNAME'))}/",
        DELINEA_TOOL_PRESET="Read-only",
    )


def test_read_paths_reports_and_errors():
    async def scenario(call, tools, prompts):
        assert "error" not in await call("health_check")
        secret = await call("get_secret", {"id": SID})
        passwords = [i for i in secret.get("items", []) if i.get("isPassword")]
        assert passwords and all(
            i["itemValue"] in ("********", "", None) for i in passwords
        )
        assert "********" in (await call("fetch", {"id": f"secret/{SID}"}))["text"]
        page = await call("search_secrets", {"query": "", "take": 2})
        assert "error" not in page and len(page.get("records", [])) <= 2
        # Use a folder this account can see; fixed IDs drift as tenant
        # permissions change.
        visible = (await call("search_folders", {"query": "", "take": 5})).get(
            "records", []
        )
        if visible:
            folder = await call("get_folder", {"id": visible[0]["id"]})
            assert "error" not in folder and folder.get("childFolders") is None
        assert "tbSecret" in await call("list_example_reports")
        report = await call(
            "run_report",
            {"sql_query": "SELECT u.UserId, u.Username FROM tbUser u", "max_rows": 1},
        )
        assert "error" not in report and len(report["rows"]) <= 1
        bad = await call("run_report", {"sql_query": "SELECT nope FROM tbNope"})
        assert "list_example_reports" in bad["error"]
        missing = await call("get_secret", {"id": 99999999})
        assert "can't access it" in missing["error"]

    _run(scenario)


def test_credential_handoff_needs_no_tools():
    """The env file works with only /bin on PATH and never holds a token."""

    async def scenario(call, tools, prompts):
        handoff = await call(
            "get_secret_environment_variable",
            {"secret_id": SID, "environment": "bash"},
        )
        path = Path(handoff["script_path"])
        body = path.read_text()
        assert oct(path.stat().st_mode & 0o777) == "0o600"
        assert "Bearer" not in json.dumps(handoff) + body
        # The file names itself (to self-delete); ignore its random name.
        commands = body.replace(str(path), "")
        assert "curl" not in commands and "jq" not in commands
        out = subprocess.run(
            [
                "/bin/bash",
                "-c",
                f"source '{path}' && printf '%s' "
                f'"${{#SECRET_PASSWORD_{SID}}}:${{#SECRET_USERNAME_{SID}}}"',
            ],
            capture_output=True,
            text=True,
            env={"PATH": "/bin"},
        )
        assert out.returncode == 0 and re.fullmatch(r"[1-9]\d*:\d+", out.stdout)
        assert not path.exists()  # self-deleted

        # The uploads below write the secret's notes field; put it back after.
        notes = [
            item
            for item in (await call("get_secret", {"id": SID})).get("items", [])
            if item.get("slug") == "notes"
        ]
        assert notes, "LIVE_SECRET_ID needs a notes field"
        original = notes[0].get("itemValue") or ""
        wrote = []
        try:
            marker = "dmcp-e2e-marker"
            src = Path(tempfile.mkdtemp()) / "v.txt"
            src.write_text(marker + "\n")
            result = await call(
                "set_secret_field_environment_variable",
                {
                    "secret_id": SID,
                    "field_slug": "notes",
                    "environment": "bash",
                    "source": f"file:{src}",
                },
            )
            error = result.get("error", "")
            if result.get("result", {}).get("updated"):
                wrote.append("file")
            else:
                assert "Access denied" in error and marker not in error
            result = await call(
                "set_secret_field_environment_variable",
                {
                    "secret_id": SID,
                    "field_slug": "notes",
                    "environment": "bash",
                    "source": "env:DMCP_E2E",
                },
            )
            command = result["command"]
            assert "field_push" in command and "Bearer" not in json.dumps(result)
            first = subprocess.run(
                ["/bin/bash", "-c", command],
                capture_output=True,
                text=True,
                env={"PATH": "/bin", "DMCP_E2E": marker},
            )
            output = first.stdout + first.stderr
            if first.returncode == 0:
                wrote.append("env")
            else:
                assert "Access denied" in output and marker not in output
            again = subprocess.run(
                ["/bin/bash", "-c", command], capture_output=True, text=True
            )
            assert again.returncode == 1 and "already used" in again.stderr
        finally:
            if wrote:
                restored = await call(
                    "update_secret_fields",
                    {"secret_id": SID, "field_updates": {"notes": original}},
                )
                assert "error" not in restored, restored
                after = await call("get_secret", {"id": SID})
                value = next(
                    i.get("itemValue") for i in after["items"] if i["slug"] == "notes"
                )
                assert (value or "") == original

    _run(scenario)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("answer", ["accept", "decline"])
def test_reveal_when_enabled(mode, answer):
    async def scenario(call, tools, prompts):
        assert "reveal_secret_field" in tools
        result = await call(
            "reveal_secret_field", {"secret_id": SID, "field_slug": "password"}
        )
        assert len(prompts) == 1
        if answer == "accept":
            value = result.get("value")
            assert isinstance(value, str) and value and value != "********"
        else:
            assert "value" not in result and "declined" in result["error"]

    _run(scenario, mode=mode, answer=answer, DELINEA_SECRET_REVEAL_MODE="elicit")
