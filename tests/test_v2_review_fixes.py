"""Behaviour added for the 2.0 directory-readiness pass.

Covers actionable API errors, password masking and the elicitation-gated
reveal, the private script handoff, tool titles, env-only configuration
and paging limits.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from mcp import types
from mcp.client import Client
from mcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
)
from mcp.server.mcpserver import Elicit, MCPServer

from delinea_mcp import annotations, api, server, tools
from delinea_mcp.session import SessionManager


class Resp:
    def __init__(self, data, status=200, reason="OK", text=None):
        self._data = data
        self.status_code = status
        self.reason = reason
        self.text = text if text is not None else json.dumps(data)

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


SECRET = {
    "id": 7,
    "name": "db-admin",
    "items": [
        {"slug": "username", "fieldName": "Username", "itemValue": "sa"},
        {
            "slug": "password",
            "fieldName": "Password",
            "itemValue": "hunter2",
            "isPassword": True,
        },
        {"slug": "notes", "fieldName": "Notes", "itemValue": "prod"},
    ],
}


class FakeSession:
    token = "short-lived-token"
    base_url = "https://ss.example.com/SecretServer"

    def __init__(self, summary=None):
        self.calls = []
        self.summary = summary or {}

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if path.endswith("/summary"):
            return Resp(self.summary)
        if path == "/v2/secrets/7":
            return Resp(json.loads(json.dumps(SECRET)))
        if path == "/v1/secrets/7/fields/password":
            return Resp("hunter2")
        raise AssertionError(f"unexpected {method} {path}")


@pytest.fixture
def fake_session(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(SessionManager, "_session", session)
    return session


# --------------------------------------------------------------------------- #
# Actionable API errors                                                       #
# --------------------------------------------------------------------------- #


def test_raise_for_status_includes_api_message_and_hint():
    resp = Resp(
        {"errorCode": "API_AccessDenied", "message": "Access Denied"},
        status=403,
        reason="Forbidden",
    )
    with pytest.raises(api.DelineaAPIError) as info:
        api.raise_for_status(resp, "GET /v1/secrets/5")
    msg = str(info.value)
    assert "GET /v1/secrets/5 failed: HTTP 403 Forbidden" in msg
    assert "Access Denied" in msg and "API_AccessDenied" in msg
    # errorCode beats the status: SS sends API_AccessDenied for missing IDs too.
    assert "doesn't exist or the configured account can't access it" in msg
    # Still an HTTPError, so existing handlers keep catching it.
    assert isinstance(info.value, requests.HTTPError)
    assert info.value.status_code == 403


def test_raise_for_status_reports_model_state_and_non_json():
    resp = Resp(
        {"message": "The request is invalid.", "modelState": {"take": ["bad"]}},
        400,
        "Bad Request",
    )
    with pytest.raises(api.DelineaAPIError, match=r"take: bad.*parameter names"):
        api.raise_for_status(resp, "GET /v1/folders")
    html = Resp(ValueError("no json"), 502, "Bad Gateway", text="<html>upstream</html>")
    with pytest.raises(api.DelineaAPIError, match=r"502.*upstream.*health_check"):
        api.raise_for_status(html, "GET /v1/healthcheck")


def test_raise_for_status_status_hint_without_error_code():
    with pytest.raises(api.DelineaAPIError, match="lacks permission"):
        api.raise_for_status(Resp({"message": "nope"}, 403, "Forbidden"), "GET /x")
    sql = Resp(
        {
            "message": "The SQL that was provided is not valid",
            "errorCode": "API_InvalidSql",
        },
        500,
        "Internal Server Error",
    )
    with pytest.raises(api.DelineaAPIError, match="list_example_reports") as info:
        api.raise_for_status(sql, "POST /v1/reports")
    assert "retry" not in str(info.value)


def test_raise_for_status_ok_is_noop():
    api.raise_for_status(Resp({}, 204), "anything")


# --------------------------------------------------------------------------- #
# Masking and reveal                                                          #
# --------------------------------------------------------------------------- #


def test_get_secret_masks_password_fields(fake_session):
    result = tools.get_secret(7)
    by_slug = {i["slug"]: i["itemValue"] for i in result["items"]}
    assert by_slug == {"username": "sa", "password": tools.MASK, "notes": "prod"}
    assert result["maskedFields"] == ["password"]
    assert "reveal_secret_field" in result["maskedNote"]


def test_fetch_secret_never_contains_plaintext(fake_session):
    result = tools.fetch("secret/7")
    assert "hunter2" not in result["text"]
    assert "hunter2" not in json.dumps(result["metadata"])


def test_fetch_rejects_bad_identifier_with_guidance():
    with pytest.raises(ValueError, match="e.g. 'secret/42'"):
        tools.fetch("7")


class FakeCtx:
    def __init__(self, supports=True):
        self.session = SimpleNamespace(check_client_capability=lambda cap: supports)


def _gate(ctx=None, **kw):
    return tools._confirm_reveal(7, "password", ctx or FakeCtx(), **kw)


def test_confirm_reveal_asks_the_user_by_default(fake_session):
    marker = _gate()
    assert isinstance(marker, Elicit)
    assert "transcript" in marker.message and "secret 7" in marker.message


def test_confirm_reveal_gates(fake_session, monkeypatch):
    assert "cannot show a confirmation prompt" in _gate(FakeCtx(supports=False)).error
    monkeypatch.setitem(tools._CFG, "secret_reveal_mode", "disabled")
    assert "disabled" in _gate().error
    monkeypatch.setitem(tools._CFG, "secret_reveal_mode", "client_approval")
    assert _gate(FakeCtx(supports=False)) == tools._RevealGate()


def test_confirm_reveal_checks_comment_before_asking(monkeypatch):
    monkeypatch.setattr(
        SessionManager, "_session", FakeSession(summary={"requiresComment": True})
    )
    assert "requires a comment" in _gate().error
    assert isinstance(_gate(comment="INC-42"), Elicit)


def _body(approval, **kw):
    return asyncio.run(tools.reveal_secret_field(7, "password", approval, **kw))


def test_reveal_body_releases_only_on_approval(fake_session):
    ok = AcceptedElicitation(data=tools.RevealConfirmation(confirm=True))
    assert _body(ok) == {"secret_id": 7, "field": "password", "value": "hunter2"}
    for refused in (
        AcceptedElicitation(data=tools.RevealConfirmation(confirm=False)),
        DeclinedElicitation(),
        CancelledElicitation(),
        AcceptedElicitation(data=tools._RevealGate("nope")),
    ):
        fake_session.calls.clear()
        assert "error" in _body(refused)
        assert not any(p.endswith("/fields/password") for _, p, _ in fake_session.calls)


def test_reveal_body_passes_audit_comment(fake_session):
    _body(AcceptedElicitation(data=tools._RevealGate()), comment="INC-42 restore")
    _, _, kwargs = fake_session.calls[-1]
    assert kwargs["params"]["autoComment"] == "INC-42 restore"


def _mcp_reveal(mode, answer):
    mcp = MCPServer("t")
    tools.register(mcp, {"get_secret", "reveal_secret_field"})
    seen = []

    async def respond(context, params):
        seen.append(params.message)
        return answer

    async def run():
        async with Client(mcp, elicitation_callback=respond, mode=mode) as client:
            listed = {t.name: t for t in (await client.list_tools()).tools}
            reveal = listed["reveal_secret_field"]
            assert reveal.title and reveal.annotations.read_only_hint is False
            assert set(reveal.input_schema["properties"]) == {
                "secret_id",
                "field_slug",
                "comment",
            }
            return await client.call_tool(
                "reveal_secret_field", {"secret_id": 7, "field_slug": "password"}
            )

    return asyncio.run(run()), seen


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_reveal_end_to_end_over_mcp(fake_session, mode):
    """Real client sessions on both protocol generations (input-required and
    server-to-client request): the prompt reaches the human's client."""
    accept = types.ElicitResult(action="accept", content={"confirm": True})
    result, seen = _mcp_reveal(mode, accept)
    assert "hunter2" in result.content[0].text
    assert len(seen) == 1 and "secret 7" in seen[0]

    decline = types.ElicitResult(action="decline")
    result, seen = _mcp_reveal(mode, decline)
    assert "hunter2" not in result.content[0].text
    assert "declined" in result.content[0].text


# --------------------------------------------------------------------------- #
# Script handoff                                                              #
# --------------------------------------------------------------------------- #


@pytest.fixture
def file_mode(monkeypatch, fake_session, tmp_path):
    monkeypatch.setitem(tools._CFG, "script_delivery", "file")
    monkeypatch.setattr(tools, "_SCRIPT_DIR", None)
    monkeypatch.setattr(tools.tempfile, "tempdir", str(tmp_path))
    return fake_session


@pytest.mark.parametrize("shell", ["bash", "powershell", "cmd"])
def test_env_script_written_privately_and_token_not_returned(file_mode, shell):
    result = tools.get_secret_environment_variable(7, shell)
    assert isinstance(result, dict)
    assert FakeSession.token not in json.dumps(result)
    path = Path(result["script_path"])
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    body = path.read_text()
    assert FakeSession.token in body
    if shell == "bash":
        assert body.startswith(f"rm -f '{path}'")
    elif shell == "powershell":
        assert body.startswith("Remove-Item")
    else:
        assert body.rstrip().endswith('del "%~f0"')


def test_bash_env_script_runs(file_mode, tmp_path):
    """The generated bash script is valid and exports both variables."""
    import shutil
    import subprocess

    if not (shutil.which("bash") and shutil.which("jq")):
        pytest.skip("bash and jq required")
    result = tools.get_secret_environment_variable(7, "bash")
    fake_curl = tmp_path / "bin" / "curl"
    fake_curl.parent.mkdir()
    fake_curl.write_text(f"#!/bin/sh\necho '{json.dumps(SECRET)}'\n")
    fake_curl.chmod(0o755)
    out = subprocess.run(
        [
            "bash",
            "-c",
            f"source '{result['script_path']}' && "
            'echo "$SECRET_USERNAME_7:$SECRET_PASSWORD_7"',
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{fake_curl.parent}:{os.environ['PATH']}"},
        check=True,
    )
    assert out.stdout.strip() == "sa:hunter2"
    assert not Path(result["script_path"]).exists()  # self-deleted


def test_set_field_script_uses_file_mode(file_mode):
    result = tools.set_secret_field_environment_variable(7, "api-key", "bash")
    assert "user must run it" in result["purpose"]
    assert "jq -n --arg v" in Path(result["script_path"]).read_text()


def test_expired_scripts_are_swept(file_mode):
    first = Path(tools.get_secret_environment_variable(7, "bash")["script_path"])
    os.utime(first, (0, 0))
    tools.get_secret_environment_variable(7, "bash")
    assert not first.exists()


def test_delivery_defaults_follow_transport(monkeypatch):
    monkeypatch.delitem(tools._CFG, "script_delivery", raising=False)
    monkeypatch.setitem(tools._CFG, "transport_mode", "stdio")
    assert tools._script_delivery() == "file"
    monkeypatch.setitem(tools._CFG, "transport_mode", "sse")
    assert tools._script_delivery() == "inline"


def test_inline_cmd_uses_single_percent(monkeypatch, fake_session):
    monkeypatch.setitem(tools._CFG, "script_delivery", "inline")
    script = tools.get_secret_environment_variable(7, "cmd")
    assert "%%" not in script and "%p" in script


# --------------------------------------------------------------------------- #
# Titles, registration and configuration                                      #
# --------------------------------------------------------------------------- #


def test_every_annotated_tool_has_a_title():
    assert set(annotations.TOOL_TITLES) == set(annotations.TOOL_ANNOTATIONS)
    for name in annotations.TOOL_ANNOTATIONS:
        meta = annotations.tool_metadata(name)
        assert meta["title"] and meta["annotations"].title == meta["title"]


def test_registered_tools_all_have_title_and_hint(monkeypatch):
    mcp = MCPServer("t")
    monkeypatch.setattr(server, "mcp", mcp)
    monkeypatch.setattr(SessionManager, "_session", None)
    server._init_from_config({"strongdm_enabled": True})
    listed = asyncio.run(mcp.list_tools())
    assert len(listed) > 30
    for tool in listed:
        assert tool.title, tool.name
        hints = tool.annotations
        assert hints.read_only_hint or hints.destructive_hint is not None, tool.name
        assert len(tool.name) <= 64
    assert "ai_generate_and_run_report" not in {t.name for t in listed}


def test_strongdm_is_opt_in(monkeypatch):
    mcp = MCPServer("t")
    monkeypatch.setattr(server, "mcp", mcp)
    monkeypatch.setattr(SessionManager, "_session", None)
    server._init_from_config({})
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert "get_secret" in names and not any(n.startswith("sdm_") for n in names)


def test_env_fallbacks_fill_missing_settings(monkeypatch):
    monkeypatch.setenv("DELINEA_USERNAME", "svc")
    monkeypatch.setenv("DELINEA_BASE_URL", "https://t.secretservercloud.com")
    monkeypatch.setenv("PLATFORM_HOSTNAME", "acme.delinea.app")
    merged = server._with_env_fallbacks(
        {"delinea_username": "<username>", "platform_hostname": "cfg.delinea.app"}
    )
    assert merged["delinea_username"] == "svc"
    assert merged["delinea_base_url"] == "https://t.secretservercloud.com"
    assert merged["platform_hostname"] == "cfg.delinea.app"  # config wins


def test_env_only_launch_initialises_session(monkeypatch):
    created = {}

    class Session:
        def __init__(self, **kw):
            created.update(kw)

    monkeypatch.setattr(server, "DelineaSession", Session)
    monkeypatch.setattr(server, "mcp", MCPServer("t"))
    monkeypatch.setattr(SessionManager, "_session", None)
    monkeypatch.setenv("DELINEA_USERNAME", "svc")
    monkeypatch.setenv("DELINEA_PASSWORD", "pw")
    monkeypatch.setenv("DELINEA_BASE_URL", "https://t.secretservercloud.com")
    monkeypatch.delenv("PLATFORM_HOSTNAME", raising=False)
    server._init_from_config({})
    assert created["username"] == "svc"
    assert created["base_url"] == "https://t.secretservercloud.com"
    assert isinstance(SessionManager._session, Session)


# --------------------------------------------------------------------------- #
# Paging and limits                                                           #
# --------------------------------------------------------------------------- #


def test_paged_caps_page_size():
    assert tools._paged(None) == {"take": 50, "skip": 0}
    assert tools._paged({"take": 10_000})["take"] == tools.MAX_PAGE_SIZE
    assert tools._paged({"take": "abc"})["take"] == tools.DEFAULT_PAGE_SIZE
    assert tools._paged({"filter.searchText": "x"}, take=5, skip=10) == {
        "filter.searchText": "x",
        "take": 5,
        "skip": 10,
    }


def test_run_report_truncates(monkeypatch):
    rows = [[i] for i in range(300)]

    class S:
        def request(self, method, path, **kw):
            if path == "/v1/reports":
                return Resp({"id": 1})
            if path == "/v1/reports/execute":
                return Resp({"columns": ["n"], "rows": rows})
            return Resp(True)

    monkeypatch.setattr(SessionManager, "_session", S())
    out = tools.run_report("SELECT 1", max_rows=25)
    assert len(out["rows"]) == 25 and out["total_rows"] == 300 and out["truncated"]
    assert len(tools.run_report("SELECT 1")["rows"]) == tools.DEFAULT_REPORT_ROWS


def test_run_report_description_points_at_examples_and_api_docs():
    doc = tools.run_report.__doc__
    assert "list_example_reports" in doc
    assert "docs.delinea.com" in doc


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_reveal_over_mcp_without_prompt_support(fake_session, monkeypatch, mode):
    """No elicitation callback: refuse with guidance, or rely on the client's
    own tool-approval prompt when the admin chose client_approval."""
    mcp = MCPServer("t")
    tools.register(mcp, {"reveal_secret_field"})

    async def call():
        async with Client(mcp, mode=mode) as client:
            return await client.call_tool(
                "reveal_secret_field", {"secret_id": 7, "field_slug": "password"}
            )

    text = asyncio.run(call()).content[0].text
    assert "cannot show a confirmation prompt" in text and "hunter2" not in text
    monkeypatch.setitem(tools._CFG, "secret_reveal_mode", "client_approval")
    assert "hunter2" in asyncio.run(call()).content[0].text


def test_script_expires_without_further_calls(file_mode, monkeypatch):
    monkeypatch.setattr(tools, "_SCRIPT_TTL_SECONDS", 0.05)
    path = Path(tools.get_secret_environment_variable(7, "bash")["script_path"])
    assert path.exists()
    import time

    time.sleep(0.3)
    assert not path.exists()
