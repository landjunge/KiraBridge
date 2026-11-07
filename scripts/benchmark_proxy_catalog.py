#!/usr/bin/env python3
"""Compare RC26/current proxy using allowlisted authenticated read-only calls.

Run with PYTHONPATH=src in an existing project environment. No native input,
clipboard contents, terminal reads, configuration changes, or application launch.
Response contents are discarded; only timings, counts, and sizes are saved.
"""

import argparse
import asyncio
import importlib.metadata
import json
import statistics
import subprocess
import time
import types
from datetime import datetime, timezone
from pathlib import Path

from kirabridge.bridge_core.config import load_config
from kirabridge.local_runtime import peer
from kirabridge.mcp_gateway.client import MCPClientPool
from kirabridge.mcp_gateway.proxy import DaemonConnection

ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = {
    "bridge_health": ("bridge_health", {}),
    "operation_catalog": ("operation_catalog", {}),
    "clipboard_info": ("clipboard_info", {}),
    "policy_inspect": ("policy_inspect", {}),
    "task_list": ("task_list", {"limit": 1}),
    "macos_status": ("macos_status", {"check_helpers": False}),
    "platform_query": (
        "read_query",
        {
            "query": {
                "operation": "platform.status",
                "check_helpers": False,
            }
        },
    ),
}


def summary(values):
    if not values:
        return {"count": 0, "sum_ms": 0}
    return {
        "count": len(values),
        "p50_ms": statistics.median(values),
        "min_ms": min(values),
        "max_ms": max(values),
        "sum_ms": sum(values),
    }


def baseline_class():
    module = types.ModuleType("baseline_proxy")
    source = subprocess.check_output(
        ["git", "show", "78b182b:src/kirabridge/mcp_gateway/proxy.py"],
        cwd=ROOT,
    )
    exec(compile(source, "baseline_proxy", "exec"), module.__dict__)
    return module.DaemonConnection


async def main(args):
    cfg = load_config(str(Path.home() / ".config/kirabridge/config.toml"))
    async with MCPClientPool(call_timeout=10) as pool:
        endpoint = peer(cfg, "codex")
        await pool.connect(endpoint)
        initialized = pool.initializations[endpoint.id]
        catalog = await pool.list_tools(endpoint.id)
        available = {tool.name for tool in catalog}
        metadata_times, dispatch_times = [], []
        list_tools, call_tool = pool.list_tools, pool.call

        async def timed_list(*positional, **kwargs):
            started = time.perf_counter()
            try:
                return await list_tools(*positional, **kwargs)
            finally:
                metadata_times.append((time.perf_counter() - started) * 1000)

        async def timed_dispatch(*positional, **kwargs):
            started = time.perf_counter()
            try:
                return await call_tool(*positional, **kwargs)
            finally:
                dispatch_times.append((time.perf_counter() - started) * 1000)

        pool.list_tools, pool.call = timed_list, timed_dispatch
        result = {
            "observed_at_utc": datetime.now(timezone.utc).isoformat(),
            "scope": (
                "own authenticated loopback MCP; before/after changes proxy only, "
                "same running daemon; no ChatGPT cloud/model/stdio/native input timing"
            ),
            "response_contents_saved": False,
            "order": "each domain before then after, cold catalog each variant",
            "baseline_commit": "78b182b",
            "protocolVersion": initialized.protocolVersion,
            "sdk_version": importlib.metadata.version("mcp"),
            "tools": len(catalog),
            "catalog_json_bytes": len(
                json.dumps(
                    [t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in catalog],
                    separators=(",", ":"),
                ).encode()
            ),
            "samples": [],
            "skipped": [],
            "not_measured": ["model orchestration", "ChatGPT ingress", "remote tunnel", "stdio"],
        }
        for domain in args.tools:
            tool, arguments = OPERATIONS[domain]
            if tool not in available:
                result["skipped"].append({"domain": domain, "reason": "not_advertised"})
                continue
            for label, cls in [("before", baseline_class()), ("after", DaemonConnection)]:
                connection = cls(pool, endpoint)
                timings, encoding_times, response_bytes, errors = [], [], [], []
                list_start, call_start = len(metadata_times), len(dispatch_times)
                for _index in range(args.repeat):
                    started = time.perf_counter()
                    response = await connection.call_tool(
                        tool,
                        arguments,
                        routine_health=(tool == "bridge_health"),
                    )
                    timings.append((time.perf_counter() - started) * 1000)
                    encoding_started = time.perf_counter()
                    response_bytes.append(len(response.model_dump_json().encode()))
                    encoding_times.append((time.perf_counter() - encoding_started) * 1000)
                    data = response.structuredContent
                    error = data.get("error") if isinstance(data, dict) else None
                    errors.append(
                        {
                            "isError": bool(response.isError),
                            "error_code": error.get("code") if isinstance(error, dict) else None,
                        }
                    )
                result["samples"].append(
                    {
                        "variant": label,
                        "domain": domain,
                        "operation": tool,
                        "call_ms": timings,
                        "summary": summary(timings),
                        "metadata_list_requests": len(metadata_times) - list_start,
                        "metadata_list_ms": metadata_times[list_start:],
                        "metadata_summary": summary(metadata_times[list_start:]),
                        "actual_tool_dispatches": len(dispatch_times) - call_start,
                        "dispatch_ms": dispatch_times[call_start:],
                        "dispatch_summary": summary(dispatch_times[call_start:]),
                        "client_result_encoding_ms": encoding_times,
                        "response_json_bytes": response_bytes,
                        "errors": errors,
                    }
                )
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "saved": str(args.output),
                    "protocolVersion": result["protocolVersion"],
                    "samples": [
                        {
                            "domain": r["domain"],
                            "variant": r["variant"],
                            "p50_ms": r["summary"]["p50_ms"],
                            "list_calls": r["metadata_list_requests"],
                            "dispatch_calls": r["actual_tool_dispatches"],
                            "errors": r["errors"],
                        }
                        for r in result["samples"]
                    ],
                }
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools", nargs="+", choices=list(OPERATIONS), default=["bridge_health"])
    parser.add_argument("--repeat", type=int, choices=range(1, 11), default=10)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs/evidence/rc26-catalog-cache-benchmark-20261102.json",
    )
    asyncio.run(main(parser.parse_args()))
