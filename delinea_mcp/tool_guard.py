"""Registration-time guard that keeps tool errors model-readable.

MCP SDK 2.1 (modelcontextprotocol/python-sdk#3314) stops forwarding the
text of unexpected handler exceptions to the client: the model sees only
``Error executing tool <name>``. Most tools in this project already report
failures as ``{"error": ...}`` payloads; this wrapper closes the remaining
gaps (uninitialised sessions, invalid JSON arguments, unsupported enum
values) so upgrading the SDK does not silently degrade error messages.
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def guard_tool(func: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap ``func`` so an escaping exception becomes an error payload.

    ``functools.wraps`` preserves the name, docstring, and signature that
    the MCP server introspects for the tool schema, so wrapping does not
    change how the tool is advertised.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            logger.exception("Tool %s failed", func.__name__)
            return {"error": str(exc)}

    return wrapper
