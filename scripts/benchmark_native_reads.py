"""Private real-HTTP MCP comparison of task-backed and direct native JSON reads.

Run this same script with baseline/candidate PYTHONPATH and mode task/direct.
The fake native transport returns identical JSON and invokes the real before-send
authorization callback. No native worker, UI query, keyboard or clipboard runs.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import math
import os
import socket
import statistics
import tempfile
import time
import uuid
from pathlib import Path

import uvicorn

import kirabridge
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.http import create_http_app

SOURCE_FILES = (
    "bridge_core/bridge.py",
    "task_manager/store.py",
    "task_manager/manager.py",
    "task_observation.py",
    "read_query.py",
    "native_queries.py",
    "mcp_gateway/client.py",
    "mcp_gateway/server.py",
    "mcp_gateway/http.py",
    "mcp_gateway/schema_validation.py",
    "platform_adapters/macos/system_models.py",
    "platform_adapters/macos/system_transport.py",
    "platform_adapters/macos/provider.py",
)
PAYLOAD = {
    "effect": "none",
    "revision": "owned-synthetic-read-v1",
    "offset": 0,
    "eof": True,
    "applications": [
        {
            "name": f"Owned synthetic application {index}",
            "pid": 222 + index,
            "started_at": 123.0 + index,
            "bundle_id": f"fixture.owned.application{index}",
            "app_path": f"/fixture/Application{index}.app",
            "active": index == 0,
        }
        for index in range(12)
    ],
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def source_fingerprints():
    root = Path(kirabridge.__file__).parent
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        if (root / name).is_file()
        else None
        for name in SOURCE_FILES
    }


def summary(values):
    return {
        "n": len(values),
        "p50_ms": statistics.median(values),
        "p95_ms": sorted(values)[math.ceil(0.95 * len(values)) - 1],
        "total_ms": sum(values),
        "min_ms": min(values),
        "max_ms": max(values),
    }


class FixtureTransport:
    """Mirrors the tested fake native before-send boundary without touching macOS."""

    timeout = 12
    process = None

    def __init__(self):
        self.calls = []
        self.before_send_calls = 0
        self.metadata_calls = 0
        self.closed = False
        self.release = asyncio.Event()
        self.release.set()

    def snapshot_metadata(self):
        self.metadata_calls += 1
        return {"available": True, "revision": "fixture-v1", "keyboard_protocol": 1}

    async def request(self, operation, arguments, *, principal, before_send=None):
        await self.release.wait()
        if before_send is None:
            raise RuntimeError("The private native read lost its before-send authorization")
        before_send()
        self.before_send_calls += 1
        self.calls.append((principal, operation, arguments))
        # Same independent JSON result object, as with a decoded native response.
        return json.loads(canonical(PAYLOAD))

    async def close(self):
        self.closed = True


def configure_fixture(bridge):
    original = bridge.system_modules.transport
    launches = []

    async def never_execute(*_args, **_kwargs):
        launches.append(True)
        raise RuntimeError("A private read benchmark must never start a native worker")

    original.factory = never_execute
    fixture = FixtureTransport()
    bridge.system_modules.transport = fixture
    bridge.macos.capability_probe.facts = {
        "platform": "darwin",
        "os_version": "15.7.4",
        "os_build": "fixture",
        "architecture": "x86_64",
        "process": {"pid": 999, "executable": "/fixture/python"},
    }
    bridge.macos.capability_probe.executable = lambda _path: True

    def never_check_permissions(_resource):
        raise RuntimeError("No public native permission API belongs in this synthetic benchmark")

    bridge.macos.permission_probe.reader = never_check_permissions
    # The provider retains the modules object; its metadata method must resolve
    # the same replacement transport on both archived and candidate source.
    if bridge.macos.capability_probe.native_metadata.__self__ is not bridge.system_modules:
        raise RuntimeError("Native metadata fixture is not shared by the provider")
    metadata = bridge.system_modules.snapshot_metadata()
    if metadata != {"available": True, "revision": "fixture-v1", "keyboard_protocol": 1}:
        raise RuntimeError("Mismatched native metadata fixture")
    bridge.macos.require("apps.list")
    return fixture, original, launches


def inventory(bridge):
    return {
        table: bridge.store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("tasks", "events", "completion_routes", "completion_notices")
    }


async def run(args):
    source_before = source_fingerprints()
    evidence = {
        "label": args.label,
        "mode": args.mode,
        "baseline_commit": "21a6abda85aadc8d0c361b4106d328953af9aa02",
        "version": kirabridge.__version__,
        "sdk_version": importlib.metadata.version("mcp"),
        "scope": (
            "private loopback HTTP with actual MCP SDK, fake native JSON transport; "
            "no production state, native worker/OS query, keyboard, clipboard, cloud or voice"
        ),
        "native_execution_scope": (
            "fixture return and before-send authorization only; real native target/OS permission "
            "guards are not exercised or certified by this timing comparison"
        ),
        "schema_cache": "one explicit setup tools/list; no read warmup omitted",
        "percentiles": "P50 median, P95 nearest rank",
        "source_file_sha256": source_before,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "expected_result_sha256": digest(PAYLOAD),
        "native_fixture_payload": PAYLOAD,
        "native_fixture_metadata": {
            "available": True,
            "revision": "fixture-v1",
            "keyboard_protocol": 1,
        },
        "grants": {
            "capabilities": ["apps.list", "task.read"],
            "permission_level": "full",
            "approval_mode": "automatic",
            "root_scope": "owned private temporary directory only",
        },
        "samples": [],
        "cleanup_mcp_calls": 0,
        "completion_receive_calls": 0,
        "completion_ack_calls": 0,
        "passed": False,
    }
    with tempfile.TemporaryDirectory(prefix="kirabridge-private-native-read-") as directory:
        root = Path(directory).resolve()
        envname = "KIRABRIDGE_NATIVE_READ_BENCH_" + uuid.uuid4().hex.upper()
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
            read_concurrency=1,
            principals={
                "bench": PrincipalConfig(
                    token_env=envname,
                    capabilities=evidence["grants"]["capabilities"],
                    permission_level="full",
                    approval_mode="automatic",
                    roots=[str(root)],
                )
            },
            agents={},
        )
        bridge = Bridge(config)
        fixture, original_transport, launch_attempts = configure_fixture(bridge)
        server = server_task = None
        posts = []
        try:
            async with bridge:
                app = create_http_app(bridge)

                async def observed(scope, receive, send):
                    row = None
                    if scope["type"] == "http" and scope["method"] == "POST":
                        row = {"duration_ms": None}
                        posts.append(row)
                    started = time.perf_counter_ns()
                    try:
                        return await app(scope, receive, send)
                    finally:
                        if row is not None:
                            row["duration_ms"] = (time.perf_counter_ns() - started) / 1e6

                server = uvicorn.Server(
                    uvicorn.Config(observed, log_level="critical", access_log=False)
                )
                server_task = asyncio.create_task(server.serve(sockets=[sock]))
                async with asyncio.timeout(10):
                    while not server.started:
                        if server_task.done():
                            await server_task
                        await asyncio.sleep(0.01)
                async with MCPClientPool() as pool:
                    await pool.connect(
                        Peer("private", url=f"http://127.0.0.1:{port}/mcp", token=token)
                    )
                    tools = await pool.list_tools("private")
                    advertised = {tool.name for tool in tools}
                    tool = "task_request" if args.mode == "task" else "read_query"
                    if tool not in advertised:
                        raise RuntimeError("Expected existing tool not advertised: " + tool)
                    evidence["protocol_version"] = pool.initializations["private"].protocolVersion
                    evidence["setup_http_posts"] = len(posts)
                    evidence["setup_catalog_calls"] = 1
                    evidence["initial_inventory"] = inventory(bridge)
                    for index in range(args.repeat):
                        if args.mode == "task":
                            task_id = f"native-read-fixture-{index:03}"
                            arguments = {
                                "request": {
                                    "api_version": "1",
                                    "task_id": task_id,
                                    "idempotency_key": task_id,
                                    "operation": "apps.list",
                                    "arguments": {},
                                },
                                "completion_target": "private-native-read-benchmark",
                            }
                        else:
                            arguments = {
                                "query": {
                                    "operation": "native.read",
                                    "native_operation": "apps.list",
                                    "arguments": {},
                                }
                            }
                        native_before, auth_before, post_before = (
                            len(fixture.calls),
                            fixture.before_send_calls,
                            len(posts),
                        )
                        started, cpu = time.perf_counter_ns(), time.process_time_ns()
                        response = await pool.call("private", tool, arguments)
                        cpu_ms = (time.process_time_ns() - cpu) / 1e6
                        wall_ms = (time.perf_counter_ns() - started) / 1e6
                        data = response.structuredContent
                        if response.isError or not isinstance(data, dict) or data.get("error"):
                            raise RuntimeError("Native read failed; no task or read is retried")
                        if args.mode == "task" and (
                            data.get("id") != task_id or data.get("state") != "completed"
                        ):
                            raise RuntimeError(
                                "Task did not complete inline; no status poll or retry"
                            )
                        if args.mode == "direct" and (
                            data.get("read_only") is not True
                            or data.get("native_operation") != "apps.list"
                        ):
                            raise RuntimeError("Direct native response contract changed")
                        result = data.get("result")
                        result_hash = digest(result)
                        if result != PAYLOAD or result_hash != evidence["expected_result_sha256"]:
                            raise RuntimeError("Native result JSON differs from the shared fixture")
                        if (
                            len(fixture.calls) - native_before != 1
                            or fixture.before_send_calls - auth_before != 1
                            or len(posts) - post_before != 1
                        ):
                            raise RuntimeError("Native read unexpectedly used additional calls")
                        evidence["samples"].append(
                            {
                                "index": index,
                                "tool": tool,
                                "wall_ms": wall_ms,
                                "process_cpu_ms": cpu_ms,
                                "http_posts": len(posts) - post_before,
                                "native_fixture_calls": len(fixture.calls) - native_before,
                                "before_send_auth_calls": fixture.before_send_calls - auth_before,
                                "result_sha256": result_hash,
                                "mcp_result_reserialized_utf8_bytes": len(
                                    response.model_dump_json(by_alias=True).encode("utf-8")
                                ),
                            }
                        )
                    evidence["final_inventory"] = inventory(bridge)
                    evidence["task_states"] = {
                        row["state"]: row["count"]
                        for row in bridge.store.db.execute(
                            "SELECT state,count(*) AS count FROM tasks GROUP BY state"
                        )
                    }
                    evidence["completion_delivery"] = dict(
                        bridge.store.db.execute(
                            "SELECT count(delivered) AS delivered,"
                            "count(acknowledged) AS acknowledged "
                            "FROM completion_notices"
                        ).fetchone()
                    )
                    expected_inventory = (
                        {
                            "tasks": args.repeat,
                            "events": 5 * args.repeat,
                            "completion_routes": args.repeat,
                            "completion_notices": args.repeat,
                        }
                        if args.mode == "task"
                        else dict.fromkeys(evidence["initial_inventory"], 0)
                    )
                    if any(evidence["initial_inventory"].values()) or (
                        evidence["final_inventory"] != expected_inventory
                    ):
                        raise RuntimeError("Native read produced unexpected persistent traffic")
                    expected_call = ("bench", "apps.list", {"offset": 0, "limit": 100})
                    if fixture.calls != [expected_call] * args.repeat:
                        raise RuntimeError("Native operation/principal/validated arguments differ")
                    evidence["native_call_contract_sha256"] = digest(expected_call)
                    evidence["native_fixture_calls_total"] = len(fixture.calls)
                    evidence["before_send_auth_calls_total"] = fixture.before_send_calls
                    evidence["native_metadata_calls_total_including_setup"] = fixture.metadata_calls
                    evidence["native_worker_launch_attempts"] = len(launch_attempts)
                    evidence["native_worker_running"] = original_transport.process is not None
                    if launch_attempts or original_transport.process is not None:
                        raise RuntimeError("A real native worker was unexpectedly used")
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
            evidence["fixture_closed"] = fixture.closed
            evidence["source_files_unchanged_during_run"] = source_before == source_fingerprints()
            evidence["passed"] = bool(
                evidence["passed"]
                and evidence["source_files_unchanged_during_run"]
                and evidence["private_endpoint_absent"]
                and evidence["fixture_closed"]
            )
            evidence["all_http_posts"] = posts
            if evidence["samples"]:
                evidence["wall"] = summary([s["wall_ms"] for s in evidence["samples"]])
                evidence["process_cpu"] = summary(
                    [s["process_cpu_ms"] for s in evidence["samples"]]
                )
            args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    if not evidence["passed"]:
        raise RuntimeError("Native-read comparison invalid; evidence saved, no automatic rerun")
    print(
        json.dumps(
            {
                key: evidence[key]
                for key in ("label", "mode", "passed", "wall", "process_cpu", "final_inventory")
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--mode", choices=("task", "direct"), required=True)
    parser.add_argument("--repeat", type=int, choices=range(10, 101), default=30)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
