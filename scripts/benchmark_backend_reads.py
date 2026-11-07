"""Private real-HTTP MCP read comparison. Select RC27/candidate through PYTHONPATH.

No production service/config/credentials, UI input, clipboard contents or native
worker launch. Four domains plus identical three-query groups. P95 is nearest rank.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import socket
import time
import uuid
from pathlib import Path

import uvicorn
from keyboard_sequence_benchmark import run_read_rounds, stable_permission_observations, summary

import kirabridge
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.http import create_http_app
from kirabridge.mcp_gateway.proxy import DaemonConnection
from kirabridge.operations_service import installed_source_sha


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def run(args):
    root = args.state_root.absolute()
    if root.exists() or root.is_symlink():
        raise RuntimeError("A fresh private state directory is required")
    root.mkdir(mode=0o700, parents=True)
    payload = root / "payload"
    payload.mkdir(mode=0o700)
    (payload / "fixture.txt").write_text("Owned bounded read comparison\n")
    envname = "KIRABRIDGE_READ_BENCH_" + uuid.uuid4().hex.upper()
    token = uuid.uuid4().hex + uuid.uuid4().hex
    os.environ[envname] = token
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(64)
    port = sock.getsockname()[1]
    config = Config(
        data_dir=str(root / "state"),
        port=port,
        concurrency=1,
        principals={
            "acceptance": PrincipalConfig(
                token_env=envname,
                approval_mode="automatic",
                permission_level="full",
                capabilities=[
                    "bridge.health",
                    "clipboard.info",
                    "policy.inspect",
                    "file.read",
                    "file.list",
                    "platform.status",
                    "task.read",
                ],
                roots=[str(payload)],
            )
        },
        agents={},
    )
    records, http_records = [], []
    evidence = {
        "source_label": args.source_label,
        "package": str(Path(kirabridge.__file__).parent),
        "source_sha256": installed_source_sha(),
        "version": kirabridge.__version__,
        "scope": (
            "private loopback MCP, same bounded grants and payload; excludes cloud/model/voice"
        ),
        "response_contents_saved": False,
        "passed": False,
    }
    evidence["rpc_samples"] = records
    evidence["http_post_samples"] = http_records
    bridge = Bridge(config)
    server = server_task = None
    try:
        async with bridge:
            app = create_http_app(bridge)

            async def observed(scope, receive, send):
                started = time.perf_counter_ns()
                try:
                    return await app(scope, receive, send)
                finally:
                    if scope["type"] == "http" and scope["method"] == "POST":
                        http_records.append(
                            {"duration_ms": (time.perf_counter_ns() - started) / 1e6}
                        )

            server = uvicorn.Server(
                uvicorn.Config(observed, log_level="critical", access_log=False)
            )
            server_task = asyncio.create_task(server.serve(sockets=[sock]))
            async with asyncio.timeout(10):
                while not server.started:  # noqa: ASYNC110 -- private external listener startup
                    if server_task.done():
                        await server_task
                    await asyncio.sleep(0.01)
            async with MCPClientPool() as pool:
                await pool.connect(Peer("owned", url=f"http://127.0.0.1:{port}/mcp", token=token))
                evidence["protocol_version"] = pool.initializations["owned"].protocolVersion
                proxy = DaemonConnection(pool, Peer("owned"))
                advertised = {tool.name for tool in await proxy.list_tools()}
                evidence["read_queries_advertised"] = "read_queries" in advertised

                async def call(tool, arguments):
                    started = time.perf_counter_ns()
                    response = await proxy.call_tool(tool, arguments)
                    elapsed = (time.perf_counter_ns() - started) / 1e6
                    wire = response.model_dump_json(by_alias=True)
                    data = response.structuredContent
                    if response.isError or not isinstance(data, dict) or data.get("error"):
                        raise RuntimeError("Read benchmark call failed: " + tool)
                    records.append(
                        {
                            "tool": tool,
                            "elapsed_ms": elapsed,
                            "response_bytes": len(wire.encode()),
                            "meta": json.loads(wire).get("_meta"),
                        }
                    )
                    return data

                if not args.groups_only:
                    evidence["domains"] = await run_read_rounds(
                        call=call, repeat=args.repeat, record=lambda *_: None
                    )
                evidence["semantic_comparison_exclusion"] = (
                    "platform.status OS-permission observed_at only"
                )
                queries = [
                    {
                        "operation": "file.read",
                        "path": str(payload / "fixture.txt"),
                        "max_bytes": 1024,
                    },
                    {
                        "operation": "file.list",
                        "path": str(payload),
                        "limit": 10,
                        "max_bytes": 1024,
                    },
                    {"operation": "platform.status", "max_bytes": 1024},
                ]
                groups = []
                for index in range(args.repeat):
                    modes = ["single", "batch"] if index % 2 == 0 else ["batch", "single"]
                    if "read_queries" not in advertised:
                        modes = ["single"]
                    reference = None
                    for mode in modes:
                        started = time.perf_counter_ns()
                        if mode == "single":
                            result = [
                                await call("read_query", {"query": query}) for query in queries
                            ]
                            count = 3
                        else:
                            response = await call("read_queries", {"queries": queries})
                            if (
                                response.get("complete") is not True
                                or response.get("read_only") is not True
                            ):
                                raise RuntimeError("Incomplete bounded read batch")
                            result = [item["result"] for item in response["results"]]
                            if any(value.get("error") for value in result):
                                raise RuntimeError("Batch member was rejected")
                            count = 1
                        elapsed = (time.perf_counter_ns() - started) / 1e6
                        result_hashes = [
                            digest(value)
                            if i != 2
                            else digest(stable_permission_observations(value))
                            for i, value in enumerate(result)
                        ]
                        if reference is not None and result_hashes != reference:
                            raise RuntimeError(
                                "Single and batched reads returned different semantic results"
                            )
                        reference = result_hashes
                        groups.append(
                            {
                                "index": index,
                                "mode": mode,
                                "elapsed_ms": elapsed,
                                "tool_calls": count,
                                "read_operations": 3,
                                "result_sha256": result_hashes,
                            }
                        )
                evidence["read_groups"] = {
                    "samples": groups,
                    "summary": {
                        mode: summary(
                            [sample["elapsed_ms"] for sample in groups if sample["mode"] == mode]
                        )
                        for mode in ("single", "batch")
                    },
                }
                evidence["rpc_samples"] = records
                evidence["http_post_samples"] = http_records
                evidence["tasks_created"] = bridge.store.db.execute(
                    "SELECT count(*) FROM tasks"
                ).fetchone()[0]
                if (
                    evidence["tasks_created"] != 0
                    or bridge.system_modules.transport.process is not None
                ):
                    raise RuntimeError("Read comparison unexpectedly started work/native helper")
                evidence["passed"] = True
    finally:
        if server is not None:
            server.should_exit = True
        if server_task is not None:
            await asyncio.wait_for(server_task, 10)
        sock.close()
        os.environ.pop(envname, None)
        with socket.socket() as probe:
            probe.settimeout(0.5)
            evidence["private_endpoint_absent"] = probe.connect_ex(("127.0.0.1", port)) != 0
        evidence["passed"] = bool(evidence["passed"] and evidence["private_endpoint_absent"])
        args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    if not evidence["passed"]:
        raise RuntimeError("Read comparison failed; original evidence preserved")
    print(
        json.dumps(
            {
                "saved": str(args.output),
                "passed": True,
                "domains": evidence.get("domains", {}).get("summary"),
                "groups": evidence["read_groups"]["summary"],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-label", required=True)
    parser.add_argument("--groups-only", action="store_true")
    parser.add_argument("--repeat", type=int, choices=range(10, 31), default=10)
    asyncio.run(run(parser.parse_args()))
