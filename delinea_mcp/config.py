import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path("config.json")


def load_config(path: str | Path = DEFAULT_PATH) -> dict[str, Any]:
    file = Path(path)
    if not file.exists():
        return {}
    try:
        return json.loads(file.read_text())
    except Exception:
        logger.exception("Failed to load config from %s", file)
        return {}
