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
caller to narrow the request, and an oversized exception message is
truncated. Sizes are measured on the ``CallToolResult`` the SDK actually
builds, so tools that also emit ``structuredContent`` are counted in full.

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
import math
from typing import Any, Callable

import pydantic_core

logger = logging.getLogger(__name__)

_max_result_bytes: int | None = None

# Bytes the server adds around the CallToolResult built here: the JSON-RPC
# envelope (``{"jsonrpc":"2.0","id":...,"result":...}``), SSE framing
# (``event: message`` / ``data: ``) and the fields the lowlevel server sets on
# every result (``_meta.io.modelcontextprotocol/serverInfo``, ``isError``,
# ``resultType``) - about 200 bytes today; rounded up so the cap errs low.
_ENVELOPE_OVERHEAD = 512

# An exception message is never cut below this many characters, so a cap
# set unreasonably low still leaves the model a usable diagnostic.
_MIN_ERROR_CHARS = 200

_INVALID = "max_result_bytes must be a positive integer"


def configure(max_result_bytes: Any = None) -> None:
    """Set the result size limit; ``None`` or ``0`` disables it.

    Accepts an int, an integral float (``524288.0``) or a string of digits.
    Fractions, negatives, booleans and anything else raise ``ValueError`` so a
    malformed setting fails at startup instead of silently removing the cap.
    """
    global _max_result_bytes
    value = max_result_bytes
    if isinstance(value, str):
        value = value.strip()
        if value in ("", "0"):
            _max_result_bytes = None
            return
        if not value.isdigit():
            raise ValueError(_INVALID)
        value = int(value)
    if value is None:
        _max_result_bytes = None
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(_INVALID)
    if isinstance(value, float) and not (math.isfinite(value) and value.is_integer()):
        raise ValueError(_INVALID)
    if value < 0:
        raise ValueError(_INVALID)
    _max_result_bytes = int(value) or None


def _tool_metadata(func: Callable[..., Any]) -> Any | None:
    """The SDK's own metadata for ``func`` (same call ``MCPServer.tool`` makes)."""
    try:
        from mcp.server.mcpserver.utilities.func_metadata import func_metadata

        return func_metadata(func)
    except Exception:  # pragma: no cover - SDK layout changed
        logger.debug("func_metadata unavailable for %s", func, exc_info=True)
        return None


def _fallback_size(result: Any) -> int:
    """Upper-bound estimate: text content plus a structured-content copy."""
    if isinstance(result, str):
        text = result
    else:
        text = pydantic_core.to_json(result, fallback=str, indent=2).decode()
    text_bytes = len(json.dumps(text).encode("utf-8"))
    structured = len(pydantic_core.to_json({"result": result}, fallback=str))
    return text_bytes + structured + _ENVELOPE_OVERHEAD


def result_size(result: Any, metadata: Any | None = None) -> int:
    """Bytes ``result`` occupies in the ``tools/call`` response on the wire.

    With the tool's SDK metadata this builds the exact ``CallToolResult`` the
    server will send - text content *and*, for tools with an output schema,
    the duplicated ``structuredContent`` - and serialises it the way the SSE
    and streamable HTTP transports do, plus the JSON-RPC/SSE envelope. Without
    metadata (or if the SDK cannot convert the value) it falls back to a
    conservative estimate that assumes both copies are sent.
    """
    if metadata is not None:
        try:
            call_result = metadata.convert_result(result)
            body = call_result.model_dump_json(by_alias=True, exclude_unset=True)
            return len(body.encode("utf-8")) + _ENVELOPE_OVERHEAD
        except Exception:
            logger.debug("convert_result failed; using size estimate", exc_info=True)
    return _fallback_size(result)


def _too_large_error(size: int, limit: int) -> dict[str, str]:
    return {
        "error": (
            f"Result too large: {size} bytes exceeds the server's "
            f"max_result_bytes limit of {limit}. Narrow the request (add "
            "filters, select fewer columns or rows, or search with a more "
            "specific term) and try again."
        )
    }


def _check_size(name: str, result: Any, metadata: Any | None = None) -> Any:
    limit = _max_result_bytes
    if limit is None:
        return result
    size = result_size(result, metadata)
    if size <= limit:
        return result
    logger.warning(
        "Tool %s result is %d bytes, over max_result_bytes=%d", name, size, limit
    )
    return _too_large_error(size, limit)


def _bounded_error(name: str, message: str, metadata: Any | None = None) -> dict:
    """``{"error": message}``, shortened if it would exceed the size limit.

    Short diagnostics pass through untouched; an oversized message (one that
    echoes a huge argument or backend response) keeps its head and gains a
    ``[truncated N chars]`` marker so the response still fits.
    """
    payload = {"error": message}
    limit = _max_result_bytes
    if limit is None or result_size(payload, metadata) <= limit:
        return payload
    keep = len(message)
    while keep > _MIN_ERROR_CHARS:
        keep = max(_MIN_ERROR_CHARS, keep // 2)
        cut = len(message) - keep
        payload = {"error": f"{message[:keep]}... [truncated {cut} chars]"}
        if result_size(payload, metadata) <= limit:
            break
    logger.warning(
        "Tool %s error message truncated from %d chars for max_result_bytes=%d",
        name,
        len(message),
        limit,
    )
    return payload


def guard_tool(func: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap ``func`` so an escaping exception becomes an error payload.

    ``functools.wraps`` preserves the name, docstring, and signature that
    the MCP server introspects for the tool schema, so wrapping does not
    change how the tool is advertised. Both successful results and error
    payloads are held to ``max_result_bytes`` when it is set.
    """
    metadata = _tool_metadata(func)

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            logger.exception("Tool %s failed", func.__name__)
            return _bounded_error(func.__name__, str(exc), metadata)
        return _check_size(func.__name__, result, metadata)

    return wrapper
