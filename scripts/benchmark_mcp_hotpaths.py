"""Three reproducible local MCP hotpaths; no production config, UI or cloud calls.

Run the same script with PYTHONPATH pointing to baseline/candidate src directories.
All latency samples, including the first, are retained. Each domain has one
additional allocation-only observation, excluded from its latency distribution.
"""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import math
import os
import plistlib
import socket
import statistics
import tempfile
import time
import tracemalloc
import uuid
from pathlib import Path

import uvicorn
from jsonschema import validate

import kirabridge
from kirabridge.bridge_core.bridge import INPUTS, Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.http import create_http_app
from kirabridge.mcp_gateway.proxy import DaemonConnection
from kirabridge.mcp_gateway.server import create_server

SOURCE_FILES = (
    "discovery.py",
    "mcp_gateway/client.py",
    "mcp_gateway/proxy.py",
    "mcp_gateway/server.py",
    "mcp_gateway/schema_validation.py",
    "platform_adapters/macos/system_transport.py",
)


def source_fingerprints():
    root = Path(kirabridge.__file__).parent
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        if (root / name).is_file()
        else None
        for name in SOURCE_FILES
    }


def configure_private_native_fixture(bridge, root):
    """Same checked metadata contract on archives and development worktrees.

    Mutating the existing private transport preserves all already-bound keyboard,
    module and provider references. A factory guard makes execution impossible.
    """
    commit = "1" * 40
    app = root / "MetadataFixture.app"
    contents = app / "Contents"
    executable = contents / "MacOS/KiraBridge"
    executable.parent.mkdir(parents=True)
    binary = b"KiraBridge metadata-only profiling fixture; never execute.\n"
    executable.write_bytes(binary)
    executable.chmod(0o755)
    metadata = {
        "CFBundleIdentifier": "de.netzwerkpunkt.kirabridge",
        "CFBundleExecutable": "KiraBridge",
        "KiraBridgeSystemProtocol": 1,
        "KiraBridgeKeyboardProtocol": 1,
        "KiraBridgeSourceCommit": commit,
    }
    info = plistlib.dumps(metadata, sort_keys=True)
    (contents / "Info.plist").write_bytes(info)
    binary_hash = hashlib.sha256(binary).hexdigest()
    transport = bridge.system_modules.transport
    transport.app_path = app
    transport.expected_commit = commit
    transport.expected_binary_sha256 = binary_hash
    launches = []

    async def never_execute(*args, **kwargs):
        launches.append(True)
        raise RuntimeError("The metadata-only profiling fixture must never execute")

    transport.factory = never_execute
    bridge.macos.capability_probe.native_metadata = bridge.system_modules.snapshot_metadata
    if (
        bridge.keyboard.transport is not transport
        or bridge.sessions.terminal_app.system_transport is not transport
        or bridge.macos.capability_probe.native_metadata.__self__ is not bridge.system_modules
        or any(
            getattr(module, "transport", transport) is not transport
            for module in bridge.macos.leaves.values()
        )
    ):
        raise RuntimeError("A private provider retained a stale transport reference")
    observed = bridge.macos.capability_probe.native_metadata()
    if (
        observed.get("available") is not True
        or observed.get("source_commit") != commit
        or observed.get("binary_sha256") != binary_hash
    ):
        raise RuntimeError("Private native metadata fixture was not accepted")
    return {
        "same_contract_on_both_variants": True,
        "expected_commit": commit,
        "binary_sha256": binary_hash,
        "binary_bytes": len(binary),
        "binary_mode": "0755",
        "info_plist_sha256": hashlib.sha256(info).hexdigest(),
        "metadata_available": True,
        "provider_references_verified": True,
        "metadata_preflight_before_timed_calls": True,
    }, launches


async def measure(fn, count):
    times, cpus, sizes = [], [], []
    for _ in range(count):
        started, cpu = time.perf_counter_ns(), time.process_time_ns()
        result = await fn()
        times.append((time.perf_counter_ns() - started) / 1e6)
        cpus.append((time.process_time_ns() - cpu) / 1e6)
        if result is not None:
            sizes.append(len(result.model_dump_json(by_alias=True).encode("utf-8")))
    tracemalloc.start()
    try:
        await fn()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {
        "n": count,
        "latency_ms": times,
        "cpu_ms": cpus,
        "total_ms": sum(times),
        "p50_ms": statistics.median(times),
        "p95_nearest_rank_ms": sorted(times)[math.ceil(count * 0.95) - 1],
        "cpu_total_ms": sum(cpus),
        "peak_allocation_bytes_additional_observation": peak,
        "additional_allocation_only_calls": 1,
        "reserialized_mcp_result_utf8_bytes": sizes,
    }


async def run(args):
    evidence = {
        "label": args.label,
        "version": kirabridge.__version__,
        "sdk_version": importlib.metadata.version("mcp"),
        "scope": (
            "Private loopback HTTP Bridge and actual MCP SDK. Same bounded grants, no tasks, "
            "native input, clipboard contents, cloud or production configuration. Keyboard "
            "domain validates schema only and never dispatches. CPU is this process. "
            "Allocation observation uses tracemalloc separately, not during latency samples."
        ),
        "response_contents_saved": False,
        "first_latency_sample_omitted": False,
        "domains": {},
        "source_file_sha256": source_fingerprints(),
        "baseline_commit": "adf69e0",
    }
    with tempfile.TemporaryDirectory(prefix="rc30-mcp-hotpaths-") as directory:
        root = Path(directory).resolve()
        envname = "KIRABRIDGE_PRIVATE_HOTPATH_" + uuid.uuid4().hex.upper()
        token = uuid.uuid4().hex + uuid.uuid4().hex
        os.environ[envname] = token
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(64)
        config = Config(
            data_dir=str(root / "state"),
            port=sock.getsockname()[1],
            principals={
                "profile": PrincipalConfig(
                    capabilities=[*INPUTS, "bridge.health", "task.read"],
                    permission_level="full",
                    approval_mode="automatic",
                    token_env=envname,
                    roots=[str(root)],
                )
            },
        )
        bridge = Bridge(config)
        evidence["native_metadata_fixture"], launch_attempts = configure_private_native_fixture(
            bridge, root
        )
        evidence["grants"] = {
            "capabilities_sha256": hashlib.sha256(
                json.dumps(sorted(config.principals["profile"].capabilities)).encode()
            ).hexdigest(),
            "permission_level": "full",
            "approval_mode": "automatic",
            "root_scope": "owned private temporary directory",
        }
        http = task = None
        try:
            async with bridge:
                http = uvicorn.Server(
                    uvicorn.Config(create_http_app(bridge), log_level="critical", access_log=False)
                )
                task = asyncio.create_task(http.serve(sockets=[sock]))
                async with asyncio.timeout(10):
                    while not http.started:
                        if task.done():
                            await task
                        await asyncio.sleep(0.01)
                async with MCPClientPool() as pool:
                    endpoint = Peer(
                        "private", url=f"http://127.0.0.1:{config.port}/mcp", token=token
                    )
                    await pool.connect(endpoint)

                    async def listing():
                        # Use the SDK directly to keep its complete ListToolsResult
                        # and model serialization available for size measurement.
                        return await pool.sessions["private"].list_tools()

                    evidence["domains"]["explicit_tools_list"] = await measure(listing, args.repeat)
                    tools = pool.sessions["private"]._tool_output_schemas
                    schema = (await listing()).tools
                    registered = await create_server(bridge, principal="profile").list_tools()
                    keyboard = next(tool for tool in registered if tool.name == "keyboard_control")
                    arguments = {
                        "request": {"key": {"named": "space"}},
                        "task_id": "validation-only",
                        "idempotency_key": "validation-only",
                    }
                    try:
                        from kirabridge.mcp_gateway.schema_validation import SchemaValidatorCache
                    except ImportError:
                        cache = None
                    else:
                        cache = SchemaValidatorCache()

                    async def input_validation():
                        if cache is None:
                            validate(arguments, keyboard.inputSchema)
                        else:
                            cache.validate(arguments, keyboard.inputSchema)

                    evidence["domains"]["keyboard_input_validation_only"] = await measure(
                        input_validation, args.repeat
                    )
                    evidence["domains"]["keyboard_input_validation_only"]["schema_checks"] = (
                        args.repeat + 1 if cache is None else cache.schema_checks
                    )
                    proxy = DaemonConnection(pool, endpoint)
                    health_tool = "bridge_epoch" if "bridge_epoch" in tools else "bridge_health"

                    async def polling():
                        result = await proxy.call_tool(health_tool, {}, routine_health=True)
                        data = result.structuredContent
                        if (
                            result.isError
                            or not isinstance(data, dict)
                            or data.get("error")
                            or data.get("dispatcher_active") is not True
                            or data.get("discovery", {}).get("principal") != "profile"
                        ):
                            raise RuntimeError("Private passive monitor read failed")
                        return result

                    evidence["domains"]["passive_monitor_rpc"] = await measure(polling, args.repeat)
                    evidence["domains"]["passive_monitor_rpc"]["tool"] = health_tool
                    evidence["extra_catalog_setup_calls"] = 1
                    evidence["tool_count"] = len(schema)
                    evidence["tasks_created"] = bridge.store.db.execute(
                        "SELECT count(*) FROM tasks"
                    ).fetchone()[0]
                    evidence["native_worker_started"] = (
                        bridge.system_modules.transport.process is not None
                    )
                    evidence["native_execution_attempts"] = len(launch_attempts)
                    evidence["tool_names"] = sorted(tool.name for tool in schema)
        finally:
            if http is not None:
                http.should_exit = True
            if task is not None:
                await task
            sock.close()
            bridge.store.close()
            os.environ.pop(envname, None)
    evidence["source_files_unchanged_during_run"] = (
        evidence["source_file_sha256"] == source_fingerprints()
    )
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: {
                    key: value
                    for key, value in domain.items()
                    if key not in {"latency_ms", "cpu_ms", "reserialized_mcp_result_utf8_bytes"}
                }
                for k, domain in evidence["domains"].items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 100:
        parser.error("repeat must be between 1 and 100")
    asyncio.run(run(args))
