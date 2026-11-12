"""Bounded JSON-only reads through the unchanged authenticated MCP tool path.

The whitelist is an audited contract, independent of advisory MCP annotations.
This module never caches results, submits work, retries, or replaces request context.
"""

from __future__ import annotations

import asyncio
import json
import math

from mcp import types
from pydantic import ValidationError
from pydantic_core import to_json

from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.timing import equivalent_structured_text
from kirabridge.read_query import ReadQuery

MAX_CALLS = 8
MAX_ARGUMENT_BYTES = 65536
MAX_RESULT_BYTES = 2 * 1024 * 1024
MAX_DEADLINE_SECONDS = 12.0
READ_TOOLS = frozenset(
    {
        "bridge_health",
        "clipboard_info",
        "coordinator_status",
        "operation_catalog",
        "task_get",
        "task_events",
        "task_diagnose",
        "task_list",
        "policy_inspect",
        "bridge_readiness",
        "agent_inventory",
        "macos_status",
        "live_logs",
        "live_status",
        "session_catalog",
        "session_read",
        "whiteboard_read",
        "read_query",
    }
)


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _validated_calls(server, calls):
    if type(calls) is not list or not 1 <= len(calls) <= MAX_CALLS:
        raise BridgeError("invalid_arguments", "A read tool batch requires 1–8 calls")
    checked, argument_bytes = [], 0
    for item in calls:
        if type(item) is not dict or set(item) - {"tool", "arguments"}:
            raise BridgeError("invalid_arguments", "Invalid read tool call envelope")
        name, arguments = item.get("tool"), item.get("arguments", {})
        if type(name) is not str or name not in READ_TOOLS:
            raise BridgeError("tool_batch_denied", "Tool is not in the read batch whitelist")
        if type(arguments) is not dict:
            raise BridgeError("invalid_arguments", "Tool arguments must be an object")
        try:
            encoded = _json(arguments)
            argument_bytes += len(encoded.encode("utf-8"))
            if argument_bytes > MAX_ARGUMENT_BYTES:
                raise BridgeError("invalid_arguments", "Combined arguments exceed 64 KiB")
            # Freeze JSON data without sharing mutable caller dictionaries across reads.
            arguments = json.loads(encoded)
            tool = server._tool_manager.get_tool(name)
            if tool is None:
                raise BridgeError("tool_batch_denied", "Read tool is not registered")
            if set(arguments) - set(tool.parameters.get("properties", {})):
                raise BridgeError("invalid_arguments", "Unknown read tool argument")
            validated = tool.fn_metadata.arg_model.model_validate(
                tool.fn_metadata.pre_parse_json(arguments)
            )
            if name == "read_query":
                # Never admit a recursive read.batch/tool.batch or generic dispatch.
                query = ReadQuery.model_validate(validated.model_dump_one_level()["query"])
                if query.operation == "task.observe":
                    arguments["query"] = query.model_dump(exclude_none=True)
        except (ValidationError, TypeError, ValueError, RecursionError):
            raise BridgeError("invalid_arguments", "Invalid read tool arguments") from None
        checked.append((name, arguments))
    return checked


def _response(results, *, complete, **extra):
    failed = sum(
        bool(
            row.get("error")
            or row.get("result", {}).get("isError")
            or (row.get("result", {}).get("structuredContent") or {}).get("error")
        )
        for row in results
    )
    return {
        "results": results,
        "read_only": True,
        "complete": complete,
        "all_succeeded": complete and failed == 0,
        "errors": failed,
        **extra,
    }


def _wire_size(value):
    """Bound the compact MCP JSON envelope, reserving room for outer timing metadata."""
    result = types.CallToolResult(
        content=[types.TextContent(type="text", text=_json(value))], structuredContent=value
    )
    return len(result.model_dump_json(by_alias=True).encode("utf-8")) + 2048


def _row_wire_bytes(row):
    # The outer MCP object carries a structured copy and one JSON-text copy.
    # Measure one new row in both encodings, instead of serializing every prefix.
    return len(to_json(row)) + len(to_json(_json(row))) - 2


async def read_tool_batch(
    server, bridge, principal, calls, *, deadline_seconds=12.0, result_format="full"
) -> dict:
    """Run serial existing tools within one request's auth/context and global budget.

    Validate the complete whitelist/argument contract before any read. Each child
    uses the registered low-level handler, retaining FastMCP validation, current
    identity/capabilities, output normalization and timing metadata. MCP images,
    audio and resource blocks require the original tool and stop this JSON batch
    explicitly. Twelve seconds is cooperative; synchronous reads may overrun it.
    Structured format omits only proven redundant child JSON text, retaining the
    complete structured value, error flag and metadata. Full is the RC29 contract.
    """
    if type(result_format) is not str or result_format not in {"full", "structured"}:
        raise BridgeError("invalid_arguments", "Choose full or structured batch results")
    if (
        isinstance(deadline_seconds, bool)
        or not isinstance(deadline_seconds, (int, float))
        or not math.isfinite(deadline_seconds)
        or not 0 < deadline_seconds <= MAX_DEADLINE_SECONDS
    ):
        raise BridgeError("invalid_arguments", "Read deadline must be within 0–12 seconds")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + deadline_seconds
    checked = _validated_calls(server, calls)
    bridge.security.principal(principal)
    results = []
    row_bytes = 0

    def response(rows, *, complete, **extra):
        if result_format == "structured":
            extra["result_format"] = "structured"
        return _response(rows, complete=complete, **extra)

    for index, (name, arguments) in enumerate(checked):
        if loop.time() >= deadline:
            return response(
                results,
                complete=False,
                next_index=index,
                read_executed=False,
                error={"code": "read_timeout"},
            )
        if name == "read_query" and arguments["query"].get("operation") == "task.observe":
            arguments["query"]["wait_seconds"] = min(
                arguments["query"]["wait_seconds"], max(0.0, deadline - loop.time())
            )
        try:
            async with asyncio.timeout_at(deadline):
                bridge.security.principal(principal)
                request = types.CallToolRequest(
                    params=types.CallToolRequestParams(name=name, arguments=arguments)
                )
                wire_response = await server._mcp_server.request_handlers[types.CallToolRequest](
                    request
                )
        except TimeoutError:
            results.append(
                {
                    "index": index,
                    "tool": name,
                    "read_executed": True,
                    "completed": "unknown",
                    "error": {"code": "read_timeout"},
                }
            )
            return response(
                results,
                complete=False,
                next_index=index + 1,
                error={"code": "read_timeout"},
            )
        result = wire_response.root
        if not isinstance(result, types.CallToolResult) or any(
            not isinstance(block, types.TextContent) for block in result.content
        ):
            results.append(
                {
                    "index": index,
                    "tool": name,
                    "read_executed": True,
                    "result_omitted": True,
                    "error": {
                        "code": "tool_batch_unsupported_content",
                        "message": "Call the original tool separately for non-text MCP content",
                    },
                }
            )
            return response(
                results,
                complete=False,
                next_index=index + 1,
                error={"code": "tool_batch_unsupported_content"},
            )
        row = {
            "index": index,
            "tool": name,
            "read_executed": True,
            "result": result.model_dump(mode="json", by_alias=True),
        }
        plain_text = (
            len(result.content) == 1
            and not result.content[0].model_extra
            and not set(result.content[0].model_dump(mode="json", by_alias=True, exclude_none=True))
            - {"type", "text"}
        )
        if result_format == "structured" and plain_text and equivalent_structured_text(result):
            row["result"]["content"] = []
            row["content_omitted"] = "equivalent_structured_json"
        added_bytes = _row_wire_bytes(row) + (2 if results else 0)
        candidate = response([*results, row], complete=True)
        base = response([], complete=True)
        base.update(errors=candidate["errors"], all_succeeded=candidate["all_succeeded"])
        if _wire_size(base) + row_bytes + added_bytes > MAX_RESULT_BYTES:
            return response(
                results,
                complete=False,
                omitted_index=index,
                omitted_read_executed=True,
                next_index=index + 1,
                resume_index=index,
                error={"code": "read_result_limit"},
            )
        results.append(row)
        row_bytes += added_bytes
        if loop.time() >= deadline:
            return response(
                results,
                complete=False,
                next_index=index + 1,
                read_executed=True,
                error={"code": "read_timeout"},
            )
    return response(results, complete=True)
