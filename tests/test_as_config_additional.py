import json
import os
from pathlib import Path

import pytest

from delinea_mcp.auth import as_config


def test_init_keys_invalid_file(tmp_path, monkeypatch):
    bad = tmp_path / "jwt.json"
    bad.write_text("{")
    # should fallback to new keys without raising
    as_config.init_keys(bad)
    assert as_config._PRIVATE_KEY is not None


def test_init_keys_write_error(tmp_path, monkeypatch):
    target = tmp_path / "jwt.json"

    def fail_write(self, data):
        raise OSError("boom")

    monkeypatch.setattr(Path, "write_text", fail_write)
    as_config.init_keys(target)
    assert as_config._PRIVATE_KEY is not None


def test_verify_token_errors(monkeypatch):
    token = as_config.issue_token("cid", ["mcp.read"], "aud")
    with pytest.raises(ValueError):
        as_config.verify_token(token, audience="other")

    monkeypatch.setattr(as_config.time, "time", lambda: 0)
    exp = as_config.issue_token("cid", ["mcp.read"], "aud", expires_in=1)
    monkeypatch.setattr(as_config.time, "time", lambda: 2)
    with pytest.raises(ValueError):
        as_config.verify_token(exp, audience="aud")
