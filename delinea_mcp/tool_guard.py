"""Registration-time guard that keeps tool errors model-readable.

MCP SDK 2.1 (modelcontextprotocol/python-sdk#3314) stops forwarding the
text of unexpected handler exceptions to the client: the model sees only
``Error executing tool <name>``. Most tools in this project already report
failures as ``{"error": ...}`` payloads; this wrapper closes the remaining
gaps (uninitialised sessions, invalid JSON arguments, unsupported enum
values) so upgrading the SDK does not silently degrade error messages.

It also enforces the optional ``max_result_bytes`` limit. SDK HTTP clients
parse SSE events with a fixed 1 MiB cap (python-sdk#3803), so a larger tool
result sent over the legacy ``/mcp/sse`` transport kills the client's whole
session with an error that never mentions size. With the limit set, an
oversized result is replaced by an ``{"error": ...}`` payload asking the
caller to narrow the request.

Because the wrapper may return ``{"error": ...}`` in place of the declared
result, every registered tool's return annotation must admit a ``dict``
(``dict``, ``X | dict``, ``Any``). The MCP server derives an output schema
from that annotation and validates results against it; a tool annotated
``-> str`` or ``-> dict[str, list[dict]]`` would make the SDK reject the
error payload and the model would again see only ``Error executing tool``.
``tests/test_tool_guard.py`` checks the whole registry for this.
"""

from __future__ import annotations

import functools
import json
import logging
from typing import Any, Callable

import pydantic_core

logger = logging.getLogger(__name__)

_max_result_bytes: int | None = None


def configure(max_result_bytes: Any = None) -> None:
    """Set the result size limit; ``None`` or ``0`` disables it."""
    global _max_result_bytes
    if max_result_bytes in (None, 0, ""):
        _max_result_bytes = None
        return
    if isinstance(max_result_bytes, bool):
        raise ValueError("max_result_bytes must be a positive integer")
    try:
        limit = int(max_result_bytes)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_result_bytes must be a positive integer") from exc
    if limit < 0:
        raise ValueError("max_result_bytes must be a positive integer")
    _max_result_bytes = limit or None


def result_size(result: Any) -> int:
    """Approximate bytes ``result`` occupies in a ``tools/call`` response.

    Mirrors how the SDK turns a return value into text content (strings
    verbatim, anything else as indented JSON) and then counts that text
    once JSON-escaped, as it appears inside the JSON-RPC envelope.
    """
    if isinstance(result, str):
        text = result
    else:
        text = pydantic_core.to_json(result, fallback=str, indent=2).decode()
    return len(json.dumps(text).encode("utf-8"))


def _check_size(name: str, result: Any) -> Any:
    limit = _max_result_bytes
    if limit is None:
        return result
    size = result_size(result)
    if size <= limit:
        return result
    logger.warning(
        "Tool %s result is %d bytes, over max_result_bytes=%d", name, size, limit
    )
    return {
        "error": (
            f"Result too large: {size} bytes exceeds the server's "
            f"max_result_bytes limit of {limit}. Narrow the request (add "
            "filters, select fewer columns or rows, or search with a more "
            "specific term) and try again."
        )
    }


def guard_tool(func: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap ``func`` so an escaping exception becomes an error payload.

    ``functools.wraps`` preserves the name, docstring, and signature that
    the MCP server introspects for the tool schema, so wrapping does not
    change how the tool is advertised.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            logger.exception("Tool %s failed", func.__name__)
            return {"error": str(exc)}
        return _check_size(func.__name__, result)

    return wrapper
