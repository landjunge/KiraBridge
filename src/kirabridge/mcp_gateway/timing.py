"""Content-free per-call spans carried in standard MCP result metadata.

No store, logging, request arguments, credentials or cross-clock subtraction.
The span ends before the final JSON-RPC serialization/transport write.
"""

import json
import time
import uuid
from decimal import Decimal, DecimalException

from mcp import types

TIMING_KEY = "de.netzwerkpunkt.kirabridge/timing"


class ToolSpan:
    def __init__(self):
        self.started_unix_ns = time.time_ns()
        self.started_ns = time.perf_counter_ns()

    @property
    def elapsed_ms(self):
        return (time.perf_counter_ns() - self.started_ns) / 1_000_000

    def result(self, result, layer, **measurements):
        if not isinstance(result, types.CallToolResult):
            return result
        meta = dict(result.meta or {})
        previous = meta.get(TIMING_KEY)
        timing = dict(previous) if isinstance(previous, dict) else {}
        timing.setdefault("trace_id", uuid.uuid4().hex)
        timing["schema"] = 1
        timing[layer] = {
            "handler_started_unix_ns": self.started_unix_ns,
            "result_ready_unix_ns": time.time_ns(),
            "duration_ms": self.elapsed_ms,
            **measurements,
        }
        meta[TIMING_KEY] = timing
        return result.model_copy(update={"meta": meta})


def _unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON object key")
        value[key] = item
    return value


def _json_integer(token):
    if token == "-0":
        raise ValueError("Preserve a signed integer zero text fallback")
    return int(token)


def _json_constant(token):
    raise ValueError("Non-JSON numeric constant")


def _typed_equal(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _typed_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _typed_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    if isinstance(left, Decimal) and left.is_zero() and right.is_zero():
        return left.is_signed() == right.is_signed()
    return left == right


def equivalent_structured_text(result):
    """True only for a single JSON text block identical in value and JSON types."""
    if not (
        isinstance(result, types.CallToolResult)
        and result.structuredContent is not None
        and len(result.content) == 1
        and isinstance(result.content[0], types.TextContent)
    ):
        return False
    try:
        parse = dict(
            parse_float=Decimal,
            parse_int=_json_integer,
            parse_constant=_json_constant,
            object_pairs_hook=_unique_pairs,
        )
        decoded = json.loads(result.content[0].text, **parse)
        structured = json.loads(
            json.dumps(
                result.structuredContent, ensure_ascii=False, allow_nan=False, sort_keys=True
            ),
            **parse,
        )
        # Keep exact decimal values and JSON types; never round custom text to float.
        return _typed_equal(decoded, structured)
    except (ValueError, TypeError, UnicodeError, RecursionError, DecimalException):
        return False


def compact_structured_text(result):
    """Keep complete JSON fallback; preserve custom prose, images and JSON types."""
    if not equivalent_structured_text(result):
        return result
    try:
        compact = json.dumps(
            result.structuredContent, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return result
    if len(compact.encode("utf-8")) >= len(result.content[0].text.encode("utf-8")):
        return result
    return result.model_copy(
        update={"content": [result.content[0].model_copy(update={"text": compact})]}
    )


def instrument_server(server, layer):
    """Wrap the registered normalized handler, preserving content and error semantics."""
    original = server.request_handlers[types.CallToolRequest]

    async def timed(request):
        span = ToolSpan()
        result = await original(request)
        if isinstance(result.root, types.CallToolResult):
            payload = compact_structured_text(result.root) if layer == "daemon" else result.root
            return types.ServerResult(span.result(payload, layer))
        return result

    server.request_handlers[types.CallToolRequest] = timed
