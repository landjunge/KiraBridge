"""Private original-transport/native-read metadata profile, without any OS child.

Actual trusted-layout fixture files exercise _private_file, stat and SHA checks.
Only the child protocol endpoint is in memory; no worker executable is launched.
"""

import argparse
import asyncio
import cProfile
import hashlib
import json
import math
import plistlib
import pstats
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

import kirabridge
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.platform_adapters.macos import system_transport as native
from kirabridge.read_query import ReadQuery, read_query_async

COMMIT = "a" * 40
GENERATION = "12345678-1234-1234-1234-123456789012"
SOURCE_FILES = (
    "native_queries.py",
    "read_query.py",
    "platform_adapters/macos/provider.py",
    "platform_adapters/macos/capabilities.py",
    "platform_adapters/macos/system_transport.py",
    "platform_adapters/macos/system_models.py",
    "permissions.py",
)


def fingerprint():
    root = Path(kirabridge.__file__).parent
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def summary(values):
    return {
        "n": len(values),
        "p50": statistics.median(values),
        "p95": sorted(values)[math.ceil(len(values) * 0.95) - 1],
        "min": min(values),
        "max": max(values),
        "sum": sum(values),
    }


class Writer:
    def __init__(self, child):
        self.child, self.closed = child, False

    def write(self, packet):
        request = json.loads(packet)
        self.child.requests.append(request)
        response = {
            "protocol": 1,
            "revision": "system-v1:" + COMMIT,
            "request_id": request["request_id"],
            "helper": self.child.helper,
            "result": {"effect": "none", "applications": [], "fixture": "same native JSON"},
        }
        self.child.stdout.feed_data(json.dumps(response).encode() + b"\n")

    async def drain(self):
        await asyncio.sleep(0)

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


class Child:
    pid = 123

    def __init__(self, executable):
        self.helper = {
            "pid": self.pid,
            "executable": executable,
            "bundle_id": native.BUNDLE_ID,
            "source_commit": COMMIT,
            "generation": GENERATION,
        }
        self.stdout = asyncio.StreamReader(limit=native.MAX_RESPONSE_BYTES + 1)
        self.stderr, self.returncode = None, None
        self.requests = []
        self.stdin = Writer(self)
        self.finished = asyncio.Event()

    def kill(self):
        self.returncode = -9
        self.stdout.feed_eof()
        self.finished.set()

    async def wait(self):
        await self.finished.wait()
        return self.returncode


async def case(root, size, repeat):
    app = root / (str(size) + ".app")
    executable = app / "Contents/MacOS/KiraBridge"
    executable.parent.mkdir(parents=True)
    # Real filesystem bytes and real digest/stat validation, not a fake metadata
    # method. These synthetic bytes are deliberately never executable by the OS.
    block = b"KiraBridge private integrity profiling fixture.\n"
    binary = (block * ((size + len(block) - 1) // len(block)))[:size]
    executable.write_bytes(binary)
    executable.chmod(0o700)
    metadata = {
        "CFBundleIdentifier": native.BUNDLE_ID,
        "CFBundleExecutable": "KiraBridge",
        "KiraBridgeSystemProtocol": 1,
        "KiraBridgeKeyboardProtocol": 1,
        "KiraBridgeSourceCommit": COMMIT,
    }
    info = plistlib.dumps(metadata, sort_keys=True)
    (app / "Contents/Info.plist").write_bytes(info)
    (app / "Contents/Info.plist").chmod(0o600)
    expected_binary_sha = hashlib.sha256(binary).hexdigest()
    config = Config(
        data_dir=str(root / (str(size) + "-state")),
        principals={
            "bench": PrincipalConfig(
                capabilities=["apps.list", "task.read"],
                permission_level="full",
                approval_mode="automatic",
                roots=[str(root)],
            )
        },
        agents={},
    )
    bridge = Bridge(config)
    transport = bridge.system_modules.transport
    transport.app_path, transport.expected_commit = app, COMMIT
    transport.expected_binary_sha256 = expected_binary_sha
    child = Child(str(executable))
    creations = []

    async def spawn(*args, **kwargs):
        creations.append((args, sorted(kwargs)))
        assert args == (str(executable), "--system-operation")
        return child  # No OS process factory is invoked.

    transport.factory = spawn
    bridge.macos.capability_probe.executable = lambda _path: True
    bridge.macos.capability_probe.facts.update(platform="darwin", os_version="15.7.4")
    fixture = transport.snapshot_metadata()
    assert fixture["available"] and fixture["binary_sha256"] == expected_binary_sha
    reads, snapshots, hashes, authorizations = [], [], [], []
    original_read, original_metadata, original_hashlib = (
        native._private_file,
        transport.snapshot_metadata,
        native.hashlib,
    )
    original_auth = bridge.system_modules.authorize

    def read(path, limit):
        started = time.perf_counter_ns()
        result = original_read(path, limit)
        reads.append(
            {
                "file": path.name,
                "bytes": len(result[0]),
                "ms": (time.perf_counter_ns() - started) / 1e6,
            }
        )
        return result

    def sha256(data=b""):
        started = time.perf_counter_ns()
        result = original_hashlib.sha256(data)
        hashes.append({"bytes": len(data), "ms": (time.perf_counter_ns() - started) / 1e6})
        return result

    def metadata_snapshot():
        started = time.perf_counter_ns()
        value = original_metadata()
        snapshots.append((time.perf_counter_ns() - started) / 1e6)
        return value

    def authorize(principal, operation):
        value = original_auth(principal, operation)
        authorizations.append((principal, operation))
        return value

    native._private_file = read
    native.hashlib = SimpleNamespace(sha256=sha256)
    transport.snapshot_metadata = metadata_snapshot
    bridge.system_modules.authorize = authorize
    request = ReadQuery(operation="native.read", native_operation="apps.list", arguments={})
    samples, reference = [], None
    before_source = fingerprint()
    try:
        for index in range(repeat):
            reads.clear()
            snapshots.clear()
            hashes.clear()
            authorizations.clear()
            started, cpu = time.perf_counter_ns(), time.process_time_ns()
            result = await read_query_async(bridge, "bench", request)
            elapsed, cpu_ms = (
                (time.perf_counter_ns() - started) / 1e6,
                (time.process_time_ns() - cpu) / 1e6,
            )
            if reference is None:
                reference = result
            assert result == reference and result["result"]["native_helper"] == child.helper
            assert result["result"]["provider_revision"] == "system-v1:" + COMMIT
            assert authorizations == [("bench", "apps.list")]
            samples.append(
                {
                    "index": index,
                    "wall_ms": elapsed,
                    "cpu_ms": cpu_ms,
                    "private_file_reads": list(reads),
                    "snapshot_ms": list(snapshots),
                    "hashes": list(hashes),
                    "result_sha256": digest(result),
                }
            )
        reads.clear()
        snapshots.clear()
        hashes.clear()
        tracemalloc.start()
        try:
            assert await read_query_async(bridge, "bench", request) == reference
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        profiler = cProfile.Profile()
        profiler.enable()
        try:
            assert await read_query_async(bridge, "bench", request) == reference
        finally:
            profiler.disable()
        stats = pstats.Stats(profiler)
        functions = [
            {
                "file": key[0],
                "line": key[1],
                "function": key[2],
                "primitive_calls": value[0],
                "calls": value[1],
                "self_ms": value[2] * 1000,
                "cumulative_ms": value[3] * 1000,
            }
            for key, value in stats.stats.items()
        ]
        inventory = {
            table: bridge.store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("tasks", "events", "completion_notices")
        }
        assert not any(inventory.values())
        return {
            "fixture_binary_bytes": size,
            "fixture_info_bytes": len(info),
            "fixture_binary_sha256": expected_binary_sha,
            "fixture_info_sha256": hashlib.sha256(info).hexdigest(),
            "metadata_fixture_contract_validated": True,
            "guarded_private_file_implementation_unchanged": True,
            "source_hashes_before": before_source,
            "source_hashes_after": fingerprint(),
            "source_unchanged": before_source == fingerprint(),
            "samples": samples,
            "wall_ms": summary([s["wall_ms"] for s in samples]),
            "cpu_ms": summary([s["cpu_ms"] for s in samples]),
            "metadata_ms_per_call": summary([sum(s["snapshot_ms"]) for s in samples]),
            "private_read_ms_per_call": summary(
                [sum(r["ms"] for r in s["private_file_reads"]) for s in samples]
            ),
            "binary_hash_ms_per_call": summary(
                [sum(h["ms"] for h in s["hashes"]) for s in samples]
            ),
            "metadata_snapshots_per_call": sorted({len(s["snapshot_ms"]) for s in samples}),
            "file_reads_per_call": sorted({len(s["private_file_reads"]) for s in samples}),
            "binary_hashes_per_call": sorted({len(s["hashes"]) for s in samples}),
            "additional_allocation_only_call_peak_bytes": peak,
            "additional_profiler_only_calls": 1,
            "profiler_top_cumulative": sorted(
                functions, key=lambda x: x["cumulative_ms"], reverse=True
            )[:25],
            "in_memory_child_creations": len(creations),
            "native_protocol_requests_including_extra_calls": len(child.requests),
            "os_child_process_creations": 0,
            "inventory": inventory,
        }
    finally:
        native._private_file, native.hashlib = original_read, original_hashlib
        transport.snapshot_metadata = original_metadata
        bridge.system_modules.authorize = original_auth
        await bridge.system_modules.close()
        bridge.store.close()
        assert child.returncode == -9 and child.stdin.closed


async def main(args):
    with tempfile.TemporaryDirectory(prefix="rc32-native-integrity-profile-") as directory:
        root = Path(directory).resolve()
        records = []
        for size in (32768, 1048576, 4194304):
            records.append(await case(root, size, args.repeat))
    result = {
        "label": args.label,
        "version": kirabridge.__version__,
        "scope": (
            "Direct Python native.read, original transport and real metadata/stat/SHA checks; "
            "fake in-memory protocol child only, no HTTP/cloud/native OS query"
        ),
        "state_scope": "owned temporary fixtures only; removed after explicit transport close",
        "warmup": "none excluded; files are newly written so no claim of cold disk cache",
        "percentiles": "P50 median, P95 nearest rank; all first samples retained",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "records": records,
        "passed": all(r["source_unchanged"] for r in records),
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "records": [
                    {
                        k: r[k]
                        for k in (
                            "fixture_binary_bytes",
                            "wall_ms",
                            "metadata_ms_per_call",
                            "private_read_ms_per_call",
                            "binary_hash_ms_per_call",
                            "metadata_snapshots_per_call",
                            "file_reads_per_call",
                            "binary_hashes_per_call",
                        )
                    }
                    for r in records
                ],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=30)
    asyncio.run(main(parser.parse_args()))
