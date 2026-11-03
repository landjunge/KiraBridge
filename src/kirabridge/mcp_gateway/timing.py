"""Content-free per-call spans carried in standard MCP result metadata.

No store, logging, request arguments, credentials or cross-clock subtraction.
The span ends before the final JSON-RPC serialization/transport write.
"""

import json
import time
import uuid

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


def compact_structured_text(result):
    """Keep the complete JSON fallback but remove its redundant whitespace.

    Images, custom prose and deliberately different text fallbacks are preserved.
    Both the structured result and a complete backwards-compatible text result remain.
    """
    if not (
        isinstance(result, types.CallToolResult)
        and result.structuredContent is not None
        and len(result.content) == 1
        and isinstance(result.content[0], types.TextContent)
    ):
        return result
    try:
        decoded = json.loads(result.content[0].text)
        canonical = dict(ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        # JSON types matter: Python equality equates True/1 and 1/1.0.
        if json.dumps(decoded, **canonical) != json.dumps(result.structuredContent, **canonical):
            return result
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
