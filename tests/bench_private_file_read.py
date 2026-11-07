"""Local allocation/timing comparison on owned temporary files, never native apps.

Run with Python 3.11, --before-source ORIGINAL_SYSTEM_TRANSPORT.py --output PRIVATE_JSON.
Only the _private_file function is compiled from each source; no bridge modules,
native helpers, network, Terminal, installed files or user contents are accessed.
"""

import argparse
import ast
import hashlib
import json
import math
import os
import stat
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path

LIMIT = 32 * 1024 * 1024


def reader(path):
    tree = ast.parse(path.read_text())
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_private_file"
    )
    namespace = {"os": os, "stat": stat}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["_private_file"], hashlib.sha256(ast.unparse(function).encode()).hexdigest()


def summary(values):
    ordered = sorted(values)
    return {
        "n": len(values),
        "p50": statistics.median(values),
        "p95": ordered[math.ceil(0.95 * len(ordered)) - 1],
        "min": ordered[0],
        "max": ordered[-1],
        "total": sum(values),
    }


def measured(check, path, expected):
    def fresh_digest():
        data, _ = check(path, LIMIT)
        return hashlib.sha256(data).hexdigest()

    tracemalloc.start()
    started = time.perf_counter_ns()
    try:
        assert fresh_digest() == expected
        assert fresh_digest() == expected
        milliseconds = (time.perf_counter_ns() - started) / 1_000_000
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {"two_fresh_read_and_hash_ms": milliseconds, "peak_traced_bytes": peak}


def benchmark(before_source, rounds):
    current_source = (
        Path(__file__).resolve().parents[1]
        / "src/kirabridge/platform_adapters/macos/system_transport.py"
    )
    before, old_sha = reader(before_source)
    after, new_sha = reader(current_source)
    records = []
    with tempfile.TemporaryDirectory(prefix="kirabridge-private-file-bench-") as directory:
        for size in (1024, 256 * 1024, 2 * 1024 * 1024, LIMIT):
            path = Path(directory) / "owned-native-fixture"
            with path.open("wb") as stream:
                remaining = size
                chunk = b"f" * min(size, 1024 * 1024)
                while remaining:
                    part = chunk[:remaining]
                    stream.write(part)
                    remaining -= len(part)
            path.chmod(0o600)
            expected = hashlib.sha256(path.read_bytes()).hexdigest()
            # One unmeasured read per version warms the same OS file cache.
            assert hashlib.sha256(before(path, LIMIT)[0]).hexdigest() == expected
            assert hashlib.sha256(after(path, LIMIT)[0]).hexdigest() == expected
            samples = {"before": [], "after": []}
            for index in range(rounds):
                order = (("before", before), ("after", after))
                if index % 2:
                    order = tuple(reversed(order))
                for label, check in order:
                    samples[label].append(measured(check, path, expected))
            for label in ("before", "after"):
                records.append(
                    {
                        "label": label,
                        "fixture_bytes": size,
                        "two_fresh_read_and_hash_ms": summary(
                            [s["two_fresh_read_and_hash_ms"] for s in samples[label]]
                        ),
                        "peak_traced_bytes": summary(
                            [s["peak_traced_bytes"] for s in samples[label]]
                        ),
                        "samples": samples[label],
                    }
                )
    return {
        "scope": "Owned temporary regular files only; no app, process, bridge or network calls",
        "limit_bytes": LIMIT,
        "fresh_reads_and_sha256_per_sample": 2,
        "rounds_per_size_and_version": rounds,
        "before_function_sha256": old_sha,
        "after_function_sha256": new_sha,
        "cache": "Warm OS file cache; no application/integrity/result cache",
        "method": (
            "Alternating before/after order; P50 median, P95 nearest rank; "
            "tracemalloc active during timing"
        ),
        "limitations": (
            "Synthetic integrity-read microbenchmark, not Cloud or end-to-end latency; "
            "traced memory is Python allocation, not RSS"
        ),
        "records": records,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rounds", type=int, default=20)
    args = parser.parse_args()
    assert 5 <= args.rounds <= 100
    result = benchmark(args.before_source, args.rounds)
    with os.fdopen(
        os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    for record in result["records"]:
        print(json.dumps({key: value for key, value in record.items() if key != "samples"}))
