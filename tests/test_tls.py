"""OS certificate store for outbound TLS (delinea_mcp.tls)."""

from __future__ import annotations

import sys
import types

import pytest

from delinea_mcp import tls


@pytest.fixture
def fake_truststore(monkeypatch):
    calls = []
    module = types.SimpleNamespace(inject_into_ssl=lambda: calls.append(1))
    monkeypatch.setitem(sys.modules, "truststore", module)
    monkeypatch.setattr(tls, "_applied", False)
    monkeypatch.delenv("DELINEA_TLS_TRUST", raising=False)
    return calls


def test_uses_system_store_by_default_once(fake_truststore):
    assert tls.use_system_trust_store() is True
    assert tls.use_system_trust_store() is True
    assert fake_truststore == [1]  # injected once


@pytest.mark.parametrize("value", ["bundled", "certifi", " Bundled "])
def test_opt_out_keeps_bundled_certificates(fake_truststore, monkeypatch, value):
    monkeypatch.setenv("DELINEA_TLS_TRUST", value)
    assert tls.use_system_trust_store() is False
    assert fake_truststore == []


def test_server_and_field_push_apply_it(fake_truststore, monkeypatch, tmp_path):
    from delinea_mcp import field_push, server

    monkeypatch.setattr(server.mcp, "run", lambda **kw: None)
    monkeypatch.setattr(server, "CURRENT_CONFIG", {})
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DELINEA_MCP_CONFIG", raising=False)
    server.run_server([])
    assert fake_truststore == [1]
    monkeypatch.setattr(tls, "_applied", False)
    field_push.main([str(tmp_path / "missing.json")])
    assert fake_truststore == [1, 1]
