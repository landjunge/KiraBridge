#!/usr/bin/env python3
"""Compare RC26/current proxy discovery using 20 authenticated read-only health calls.

Run from the checkout with PYTHONPATH=src using a Python environment containing
project dependencies. Never posts native input, reads clipboard, or changes config.
"""

import asyncio
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
old = types.ModuleType("baseline_proxy")
exec(
    compile(
        subprocess.check_output(
            ["git", "show", "78b182b:src/kirabridge/mcp_gateway/proxy.py"], cwd=ROOT
        ),
        "baseline_proxy",
        "exec",
    ),
    old.__dict__,
)


def summary(xs):
    return {
        "count": len(xs),
        "p50_ms": statistics.median(xs),
        "min_ms": min(xs),
        "max_ms": max(xs),
        "sum_ms": sum(xs),
    }


async def main():
    cfg = load_config(str(Path.home() / ".config/kirabridge/config.toml"))
    async with MCPClientPool(call_timeout=10) as pool:
        endpoint = peer(cfg, "codex")
        await pool.connect(endpoint)
        initialized = pool.initializations[endpoint.id]
        catalog = await pool.list_tools(endpoint.id)
        count = 0
        original = pool.list_tools

        async def counted(*args, **kwargs):
            nonlocal count
            count += 1
            return await original(*args, **kwargs)

        pool.list_tools = counted
        result = {
            "observed_at_utc": datetime.now(timezone.utc).isoformat(),
            "scope": (
                "local authenticated loopback MCP read-only bridge_health; "
                "no keyboard/clipboard/UI; not ChatGPT cloud/stdio timing"
            ),
            "baseline_commit": "78b182b",
            "protocolVersion": initialized.protocolVersion,
            "sdk_version": __import__("importlib.metadata").metadata.version("mcp"),
            "tools": len(catalog),
            "catalog_json_bytes": len(
                json.dumps(
                    [t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in catalog],
                    separators=(",", ":"),
                ).encode()
            ),
            "samples": [],
        }
        for label, cls in [("before", old.DaemonConnection), ("after", DaemonConnection)]:
            connection = cls(pool, endpoint)
            timings = []
            previous = count
            for _i in range(10):
                start = time.perf_counter()
                response = await connection.call_tool("bridge_health", {}, routine_health=True)
                timings.append((time.perf_counter() - start) * 1000)
                assert not response.isError
            result["samples"].append(
                {
                    "variant": label,
                    "operation": "bridge_health",
                    "call_ms": timings,
                    "summary": summary(timings),
                    "metadata_list_requests": count - previous,
                    "actual_tool_dispatches": 10,
                }
            )
        path = ROOT / "docs/evidence/rc26-catalog-cache-benchmark-20261102.json"
        path.write_text(json.dumps(result, indent=2) + "\n")
        print(
            json.dumps(
                {
                    **{k: v for k, v in result.items() if k != "samples"},
                    "samples": [
                        {k: v for k, v in r.items() if k != "call_ms"} for r in result["samples"]
                    ],
                }
            )
        )


asyncio.run(main())
