"""Behaviour added for the 2.0 directory-readiness pass.

Covers actionable API errors, password masking and the elicitation-gated
reveal, the private script handoff, tool titles, env-only configuration
and paging limits.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
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
def reveal_on(monkeypatch):
    """Plaintext reveal is off by default; these tests opt in explicitly."""
    monkeypatch.setitem(tools._CFG, "secret_reveal_mode", "elicit")


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


@pytest.fixture
def fresh_api():
    """A private copy of delinea_mcp.api.

    Some older suites replace ``delinea_api.DelineaSession`` at import time
    and never restore it, so sign-in tests load their own module instance.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("_fresh_delinea_api", api.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _SignInSession:
    """Stands in for requests.Session during DelineaSession sign-in."""

    response: Resp | None = None

    def __init__(self):
        self.headers = {}

    def post(self, url, data=None, **kwargs):
        return type(self).response


@pytest.mark.parametrize(
    ("status", "body", "detail"),
    [
        (400, {"error": "Login failed."}, "Login failed."),
        (
            401,
            {"error": "invalid_grant", "error_description": "Account is locked"},
            "Account is locked",
        ),
        (403, {"message": "Forbidden"}, "Forbidden"),
    ],
)
def test_sign_in_rejection_explains_direct_api_setting(
    fresh_api, monkeypatch, status, body, detail
):
    api = fresh_api
    monkeypatch.setattr(_SignInSession, "response", Resp(body, status, "Rejected"))
    monkeypatch.setattr(api.requests, "Session", _SignInSession)
    monkeypatch.setenv("DELINEA_USERNAME", "svc-mcp")
    monkeypatch.setenv("DELINEA_PASSWORD", "very-secret-pw")
    monkeypatch.delenv("PLATFORM_HOSTNAME", raising=False)
    with pytest.raises(api.DelineaAPIError) as info:
        api.DelineaSession(base_url="https://ss.example.com/SecretServer")
    msg = str(info.value)
    assert msg.startswith(f"Secret Server sign-in as 'svc-mcp' failed: HTTP {status}")
    assert detail in msg
    assert "Application Account" in msg and "Prevent direct API authentication" in msg
    assert "very-secret-pw" not in msg
    assert info.value.status_code == status


def test_sign_in_server_error_has_no_direct_api_hint(fresh_api, monkeypatch):
    api = fresh_api
    monkeypatch.setattr(
        _SignInSession,
        "response",
        Resp(
            ValueError("no json"), 503, "Service Unavailable", text="<html>down</html>"
        ),
    )
    monkeypatch.setattr(api.requests, "Session", _SignInSession)
    monkeypatch.setenv("DELINEA_USERNAME", "svc-mcp")
    monkeypatch.setenv("DELINEA_PASSWORD", "pw")
    monkeypatch.delenv("PLATFORM_HOSTNAME", raising=False)
    with pytest.raises(api.DelineaAPIError) as info:
        api.DelineaSession(base_url="https://ss.example.com/SecretServer")
    assert "Application Account" not in str(info.value)
    assert "<html>down</html>" in str(info.value)


def test_raise_for_status_ok_is_noop():
    api.raise_for_status(Resp({}, 204), "anything")


# --------------------------------------------------------------------------- #
# Masking and reveal                                                          #
# --------------------------------------------------------------------------- #


def test_get_secret_masks_password_fields(fake_session, monkeypatch):
    monkeypatch.delitem(tools._CFG, "secret_reveal_mode", raising=False)
    monkeypatch.delenv("DELINEA_SECRET_REVEAL_MODE", raising=False)
    result = tools.get_secret(7)
    by_slug = {i["slug"]: i["itemValue"] for i in result["items"]}
    assert by_slug == {"username": "sa", "password": tools.MASK, "notes": "prod"}
    assert result["maskedFields"] == ["password"]
    # Reveal is off by default, so the note doesn't offer it.
    assert "reveal_secret_field" not in result["maskedNote"]
    assert "disabled" in result["maskedNote"]


def test_masked_note_offers_reveal_only_when_enabled(fake_session, reveal_on):
    assert "reveal_secret_field" in tools.get_secret(7)["maskedNote"]


def test_reveal_is_off_by_default(monkeypatch):
    monkeypatch.delitem(tools._CFG, "secret_reveal_mode", raising=False)
    monkeypatch.delenv("DELINEA_SECRET_REVEAL_MODE", raising=False)
    assert tools._reveal_mode() == "disabled"
    mcp = MCPServer("t")
    tools.register(mcp)
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert "reveal_secret_field" not in names and "get_secret" in names


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ("true", "elicit"),
        ("false", "disabled"),
        ("", "disabled"),
        ("elicit", "elicit"),
        ("client_approval", "client_approval"),
        ("bogus", "disabled"),
    ],
)
def test_reveal_mode_from_env(monkeypatch, env, expected):
    monkeypatch.delitem(tools._CFG, "secret_reveal_mode", raising=False)
    monkeypatch.setenv("DELINEA_SECRET_REVEAL_MODE", env)
    assert tools._reveal_mode() == expected


def test_reveal_config_beats_env(monkeypatch):
    monkeypatch.setenv("DELINEA_SECRET_REVEAL_MODE", "true")
    monkeypatch.setitem(tools._CFG, "secret_reveal_mode", "disabled")
    assert tools._reveal_mode() == "disabled"


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


def test_confirm_reveal_asks_the_user_when_enabled(reveal_on, fake_session):
    marker = _gate()
    assert isinstance(marker, Elicit)
    assert "transcript" in marker.message and "secret 7" in marker.message


def test_confirm_reveal_gates(reveal_on, fake_session, monkeypatch):
    assert "cannot show a confirmation prompt" in _gate(FakeCtx(supports=False)).error
    monkeypatch.setitem(tools._CFG, "secret_reveal_mode", "disabled")
    assert "disabled" in _gate().error
    monkeypatch.setitem(tools._CFG, "secret_reveal_mode", "client_approval")
    assert _gate(FakeCtx(supports=False)) == tools._RevealGate()


def test_confirm_reveal_checks_comment_before_asking(reveal_on, monkeypatch):
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
def test_reveal_end_to_end_over_mcp(fake_session, reveal_on, mode):
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
# Credential handoff                                                          #
# --------------------------------------------------------------------------- #

TRICKY = 'it\'s $HOME "q" `x` 100%'


@pytest.fixture
def file_mode(monkeypatch, fake_session, tmp_path):
    monkeypatch.setitem(tools._CFG, "script_delivery", "file")
    monkeypatch.setattr(tools, "_SCRIPT_DIR", None)
    monkeypatch.setattr(tools.tempfile, "tempdir", str(tmp_path))
    return fake_session


@pytest.mark.parametrize("shell", ["bash", "powershell", "cmd"])
def test_env_file_is_private_and_holds_no_token(file_mode, shell):
    result = tools.get_secret_environment_variable(7, shell)
    assert "hunter2" not in json.dumps(result)
    path = Path(result["script_path"])
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    body = path.read_text()
    assert "hunter2" in body and FakeSession.token not in body
    assert "curl" not in body and "jq" not in body
    if shell == "bash":
        assert body.startswith(f"rm -f '{path}'")
    elif shell == "powershell":
        assert body.startswith("Remove-Item")
    else:
        assert body.rstrip().endswith('del "%~f0"')


def test_env_file_passes_audit_comment(file_mode):
    tools.get_secret_environment_variable(7, "bash", comment="CHG-9")
    reads = file_mode.calls[-2:]  # after the approval check
    assert [(m, p) for m, p, _ in reads] == [
        ("GET", "/v2/secrets/7"),
        ("GET", "/v1/secrets/7/fields/password"),
    ]
    for _, _, kwargs in reads:
        assert kwargs["params"]["autoComment"] == "CHG-9"


def test_field_text_handles_json_plain_text_and_null():
    assert tools._field_text(Resp("pw")) == "pw"
    assert tools._field_text(Resp(None)) == ""
    assert tools._field_text(Resp(ValueError("no json"), text="raw pw")) == "raw pw"


@pytest.mark.parametrize("omitted", [{"itemValue": ""}, {"itemValue": None}, {}])
def test_env_file_password_comes_from_field_endpoint(file_mode, monkeypatch, omitted):
    """Secret GETs may leave password values out (per the API spec)."""
    secret = json.loads(json.dumps(SECRET))
    del secret["items"][1]["itemValue"]
    secret["items"][1].update(omitted)

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if path == "/v2/secrets/7":
            return Resp(secret)
        assert path == "/v1/secrets/7/fields/password"
        return Resp("from-field-endpoint")

    monkeypatch.setattr(FakeSession, "request", request)
    body = Path(tools.get_secret_environment_variable(7, "bash")["script_path"])
    text = body.read_text()
    assert "SECRET_PASSWORD_7='from-field-endpoint'" in text
    assert "SECRET_USERNAME_7='sa'" in text


def test_bash_env_file_exports_exact_values(file_mode, monkeypatch):
    """Sourcing the file needs only bash, and survives shell metacharacters."""
    import shutil
    import subprocess

    if not shutil.which("bash"):
        pytest.skip("bash required")
    secret = json.loads(json.dumps(SECRET))
    del secret["items"][1]["itemValue"]  # GETs may omit password values
    monkeypatch.setattr(
        FakeSession,
        "request",
        lambda self, m, p, **kw: Resp(TRICKY if p.endswith("/password") else secret),
    )
    result = tools.get_secret_environment_variable(7, "bash")
    out = subprocess.run(
        [
            "bash",
            "-c",
            f"source '{result['script_path']}' && "
            'printf "%s|%s" "$SECRET_USERNAME_7" "$SECRET_PASSWORD_7"',
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
        check=True,
    )
    assert out.stdout == f"sa|{TRICKY}"
    assert not Path(result["script_path"]).exists()  # self-deleted


def test_assignment_quoting():
    assert tools._assignments({"A": "it's"}, "powershell") == "$env:A = 'it''s'"
    assert tools._assignments({"A": "50%"}, "cmd") == 'set "A=50%%"'
    with pytest.raises(ValueError, match="powershell"):
        tools._assignments({"A": 'say "hi"'}, "cmd")


def test_env_file_reports_missing_fields(file_mode, monkeypatch):
    monkeypatch.setattr(
        FakeSession,
        "request",
        lambda self, m, p, **kw: Resp(
            {"items": [{"slug": "api-key", "itemValue": "x"}]}
        ),
    )
    assert "api-key" in tools.get_secret_environment_variable(7, "bash")["error"]


def test_expired_handoffs_are_swept(file_mode):
    first = Path(tools.get_secret_environment_variable(7, "bash")["script_path"])
    os.utime(first, (0, 0))
    tools.get_secret_environment_variable(7, "bash")
    assert not first.exists()


def test_handoff_expires_without_further_calls(file_mode, monkeypatch):
    import time

    monkeypatch.setattr(tools, "_SCRIPT_TTL_SECONDS", 0.05)
    path = Path(tools.get_secret_environment_variable(7, "bash")["script_path"])
    assert path.exists()
    time.sleep(0.3)
    assert not path.exists()


def test_set_field_from_file_uploads_directly(file_mode, tmp_path):
    src = tmp_path / "key.txt"
    src.write_text("AKIA-SECRET\n")
    put = []
    file_mode.request = lambda m, p, **kw: put.append((m, p, kw)) or Resp({})
    result = tools.set_secret_field_environment_variable(
        7, "api-key", "bash", source=f"file:{src}", comment="CHG-9"
    )
    assert result["result"]["updated"] and "AKIA" not in json.dumps(result)
    method, path, kwargs = put[-1]
    assert (method, path) == ("PUT", "/v1/secrets/7/fields/api-key")
    assert kwargs["json"] == {"value": "AKIA-SECRET"}
    assert kwargs["params"]["autoComment"] == "CHG-9"


def test_set_field_from_missing_file(file_mode, tmp_path):
    result = tools.set_secret_field_environment_variable(
        7, "api-key", "bash", source=f"file:{tmp_path}/nope"
    )
    assert "Can't read" in result["error"]


@pytest.mark.parametrize("source", ["stdin", "env:MY_KEY"])
def test_set_field_env_or_stdin_returns_python_command(file_mode, source):
    import sys

    result = tools.set_secret_field_environment_variable(
        7, "api-key", "bash", source=source
    )
    assert FakeSession.token not in json.dumps(result)
    assert sys.executable in result["command"]
    assert "delinea_mcp.field_push" in result["command"]
    assert ("user must run it" in result["purpose"]) == (source == "stdin")


@pytest.mark.parametrize("shell", ["bash", "powershell", "cmd"])
def test_push_command_runs_python_isolated(shell):
    command = tools._python_command(shell, Path("/tmp/job.json"))
    assert " -I -m delinea_mcp.field_push " in command


def test_push_command_ignores_project_shadow_packages(tmp_path):
    """A project-local delinea_mcp/requests must not see the job file."""
    import shutil
    import subprocess

    if not shutil.which("bash"):
        pytest.skip("bash required")
    marker = tmp_path / "shadow-ran"
    shadow = f"open({str(marker)!r}, 'w').write('x')\n"
    (tmp_path / "delinea_mcp").mkdir()
    (tmp_path / "delinea_mcp" / "__init__.py").write_text(shadow)
    (tmp_path / "delinea_mcp" / "field_push.py").write_text(shadow)
    (tmp_path / "requests.py").write_text(shadow)
    command = tools._python_command("bash", tmp_path / "missing-job.json")
    out = subprocess.run(
        ["bash", "-c", command],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(tmp_path)},
    )
    assert not marker.exists()
    assert out.returncode == 1 and "already used" in out.stderr


def test_field_push_command_uploads_value(file_mode):
    """Run the returned command for real against a local stub server."""
    import http.server
    import subprocess
    import threading

    received = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_PUT(self):
            received["path"] = self.path
            received["auth"] = self.headers["Authorization"]
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received["body"] = json.loads(body)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    file_mode.base_url = f"http://127.0.0.1:{httpd.server_address[1]}/SecretServer"
    try:
        result = tools.set_secret_field_environment_variable(
            7, "api-key", "bash", source="env:MY_KEY", comment="CHG 9"
        )
        out = subprocess.run(
            ["bash", "-c", result["command"]],
            capture_output=True,
            text=True,
            env={**os.environ, "MY_KEY": TRICKY},
        )
        assert out.returncode == 0, out.stderr
        assert "updated" in out.stdout
        assert received["body"] == {"value": TRICKY}
        assert received["auth"] == f"Bearer {FakeSession.token}"
        assert received["path"].startswith(
            "/SecretServer/api/v1/secrets/7/fields/api-key?"
        )
        assert "autoComment=CHG+9" in received["path"]
        again = subprocess.run(
            ["bash", "-c", result["command"]], capture_output=True, text=True
        )
        assert again.returncode != 0 and "already used" in again.stderr
    finally:
        httpd.shutdown()


def test_field_push_rejects_expired_and_unset(tmp_path, monkeypatch):
    from delinea_mcp import field_push

    job = tmp_path / "job.json"
    job.write_text(
        json.dumps({"expires": 0, "source": "env:X", "field": "f", "secret_id": 1})
    )
    assert field_push.main([str(job)]) == 1 and not job.exists()
    job.write_text(
        json.dumps(
            {"expires": 9e12, "source": "env:NOT_SET_X", "field": "f", "secret_id": 1}
        )
    )
    monkeypatch.delenv("NOT_SET_X", raising=False)
    assert field_push.main([str(job)]) == 1


def test_delivery_defaults_follow_transport(monkeypatch):
    monkeypatch.delitem(tools._CFG, "script_delivery", raising=False)
    monkeypatch.setitem(tools._CFG, "transport_mode", "stdio")
    assert tools._script_delivery() == "file"
    monkeypatch.setitem(tools._CFG, "transport_mode", "sse")
    assert tools._script_delivery() == "inline"


def test_inline_scripts_state_requirements(monkeypatch, fake_session):
    monkeypatch.setitem(tools._CFG, "script_delivery", "inline")
    bash = tools.get_secret_environment_variable(7, "bash", comment="CHG 9")
    assert bash.startswith("# Requires: curl, jq")
    password_url = "/api/v1/secrets/7/fields/password?autoCheckout=true"
    assert password_url in bash
    assert password_url in tools.get_secret_environment_variable(
        7, "powershell", comment="CHG 9"
    )
    assert "powershell" in tools.get_secret_environment_variable(7, "cmd")["error"]
    assert tools.set_secret_field_environment_variable(7, "k", "cmd").startswith(
        "REM Requires: curl"
    )


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
    assert re.search(r"https://docs\.delinea\.com/\S+", doc)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_reveal_over_mcp_without_prompt_support(
    fake_session, reveal_on, monkeypatch, mode
):
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


def test_redact_masks_submitted_value():
    assert (
        api.redact("bad value 'hunter22' given", "hunter22")
        == "bad value '********' given"
    )
    assert api.redact("nothing here", "hunter22") == "nothing here"
    assert api.redact("a b c", "a") == "a b c"  # too short to mask safely
    assert api.redact("x", None) == "x"


def test_field_push_error_never_echoes_value(tmp_path, monkeypatch, capsys):
    """Even if the server echoes the submitted value, stderr shows a mask."""
    from delinea_mcp import field_push

    job = tmp_path / "job.json"
    job.write_text(
        json.dumps(
            {
                "expires": 9e12,
                "source": "env:DMCP_SECRET",
                "field": "api-key",
                "secret_id": 7,
                "url": "https://ss.example.com/api/v1/secrets/7/fields/api-key",
                "token": "t",
                "params": None,
            }
        )
    )
    monkeypatch.setenv("DMCP_SECRET", "S3cr3t-Value")
    monkeypatch.setattr(field_push, "use_system_trust_store", lambda: False)
    echo = Resp({"message": "Value 'S3cr3t-Value' is invalid"}, 400, "Bad Request")
    monkeypatch.setattr(field_push.requests, "put", lambda *a, **k: echo)
    assert field_push.main([str(job)]) == 1
    err = capsys.readouterr().err
    assert "S3cr3t-Value" not in err and "********" in err
