"""Local MCP JSON work only; no daemon, native helper, Cloud, clipboard or user data."""

import argparse
import asyncio
import inspect
import json
import math
import statistics
import time
import tracemalloc
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from mcp import types
from mcp.server.fastmcp import FastMCP

from kirabridge.mcp_gateway.timing import instrument_server
from kirabridge.read_tool_batch import read_tool_batch


def stats(values):
    return {
        "n": len(values),
        "p50": statistics.median(values),
        "p95": sorted(values)[math.ceil(0.95 * len(values)) - 1],
    }


async def measure(format_name, rounds):
    server = FastMCP("serialization-fixture")
    payload = "x" * 65536
    executions = []

    @server.tool(name="task_get")
    async def task_get(task_id: str) -> dict[str, Any]:
        executions.append(task_id)
        return {"id": task_id, "state": "completed", "result": {"text": payload}}

    instrument_server(server._mcp_server, "daemon")
    bridge = SimpleNamespace(security=SimpleNamespace(principal=lambda name: None))
    calls = [{"tool": "task_get", "arguments": {"task_id": f"fixture_{i}"}} for i in range(8)]
    kwargs = {"result_format": format_name} if format_name != "full" else {}

    async def one():
        executions.clear()
        received, rpc_count, encoded_bytes, remaining = {}, 0, 0, calls
        while remaining:
            response = await read_tool_batch(server, bridge, "fixture", remaining, **kwargs)
            rpc_count += 1
            outer = types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=json.dumps(response, ensure_ascii=False, separators=(",", ":")),
                    )
                ],
                structuredContent=response,
            )
            encoded_bytes += len(outer.model_dump_json(by_alias=True).encode())
            for row in response["results"]:
                result = row["result"]["structuredContent"]
                assert result["result"]["text"] == payload and result["state"] == "completed"
                received[result["id"]] = True
            if response["complete"]:
                remaining = []
            else:
                assert response["error"]["code"] == "read_result_limit"
                resume = response.get("resume_index", response["omitted_index"])
                assert resume > 0
                remaining = remaining[resume:]
            assert rpc_count <= 8
        assert len(received) == 8
        return {
            "outer_replies": rpc_count,
            "inner_reads": len(executions),
            "encoded_bytes": encoded_bytes,
        }

    samples = []
    for _ in range(rounds):
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        result = await one()
        samples.append(
            {
                "wall_ms": (time.perf_counter_ns() - wall) / 1e6,
                "cpu_ms": (time.process_time_ns() - cpu) / 1e6,
                **result,
            }
        )
    tracemalloc.start()
    await one()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "format": format_name,
        "samples": samples,
        "peak_bytes": peak,
        "wall_ms": stats([s["wall_ms"] for s in samples]),
        "cpu_ms": stats([s["cpu_ms"] for s in samples]),
    }


async def main(output, rounds):
    formats = ["full"]
    if "result_format" in inspect.signature(read_tool_batch).parameters:
        formats.append("structured")
    result = {
        "scope": "Controlled local normalized MCP replies: eight distinct fixture task IDs, "
        "each a 64-KiB text result. Full semantic payload checked. No warmup omitted; "
        "separate traced memory sample. These are not Cloud roundtrips.",
        "results": [await measure(fmt, rounds) for fmt in formats],
    }
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            [
                {k: row[k] for k in ("format", "wall_ms", "cpu_ms", "peak_bytes")}
                for row in result["results"]
            ]
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=10, choices=range(1, 101))
    options = parser.parse_args()
    asyncio.run(main(options.output, options.rounds))
