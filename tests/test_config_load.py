from pathlib import Path
from delinea_mcp.config import load_config


def test_load_config_missing(tmp_path):
    missing = tmp_path / "no.json"
    assert load_config(missing) == {}


def test_load_config_invalid(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    assert load_config(bad) == {}

