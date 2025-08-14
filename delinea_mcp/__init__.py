"""Resources and tools for integrating Delinea Secret Server with MCP."""

import logging
import os

logger = logging.getLogger(__name__)
if os.getenv("DELINEA_DEBUG") and not logging.getLogger().handlers:
    logging.basicConfig(level=logging.DEBUG)  # pragma: no cover - config
logger.debug("delinea_mcp package initialised")

__all__ = [
    "constants",
    "tools",
]
