"""Synthetic task-event reads in a private temporary database, never the live service.

Use the same script and Python environment with baseline/candidate PYTHONPATH.
No dispatcher, native helper, clipboard, network or user terminal is started.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import tempfile
import time
from pathlib import Path

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.bridge_core.models import State, TaskRequest

EVENT_SQL = (
    "SELECT seq,at,state,evidence FROM events WHERE task_id=? AND seq>? ORDER BY seq LIMIT 1000"
)
MORE_SQL = "SELECT 1 FROM events WHERE task_id=? AND seq>? LIMIT 1"


def summary(values):
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "p50_ms": statistics.median(ordered),
        "p95_ms": ordered[math.ceil(0.95 * len(ordered)) - 1],
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
    }


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def benchmark(label, rounds, noise_events):
    import kirabridge.bridge_core.bridge as bridge_module
    import kirabridge.task_manager.store as store_module

    files = (bridge_module.__file__, store_module.__file__)
    before = {str(path): fingerprint(path) for path in files}
    with tempfile.TemporaryDirectory(prefix="kirabridge-event-benchmark-") as root:
        root = Path(root).resolve()
        config = Config(
            data_dir=str(root / "state"),
            principals={
                "bench": PrincipalConfig(
                    approval_mode="automatic",
                    capabilities=["task.read", "terminal.execute"],
                    roots=[str(root)],
                    executables=["/bin/echo"],
                )
            },
        )
        config.visible_handoffs.enabled = False
        bridge = Bridge(config)
        try:
            task_id, worker = "synthetic-owned-output", "synthetic-fixture"
            request = TaskRequest(
                task_id=task_id,
                idempotency_key=task_id,
                operation="terminal.execute",
                arguments={"argv": ["/bin/echo", "never executed"], "cwd": str(root)},
            )
            bridge.prepare("bench", request)
            bridge.store.claim_exact(worker, 30, task_id)
            bridge.store.transition(task_id, State.RUNNING, {"synthetic": True}, owner=worker)
            bridge.store.transition(
                task_id,
                State.COMPLETED,
                {"synthetic": True},
                result={"stdout": "x" * (4 * 1024 * 1024), "stderr": "", "exit_code": 0},
                owner=worker,
            )
            db = bridge.store.db
            # Equalize fixture timestamps/evidence across separate process runs;
            # returned event payloads must be byte-equivalent, not just same-sized.
            with bridge.store.transaction():
                for index, row in enumerate(
                    list(
                        db.execute(
                            "SELECT seq FROM events WHERE task_id=? ORDER BY seq", (task_id,)
                        )
                    )
                ):
                    db.execute(
                        "UPDATE events SET at=?,evidence=? WHERE seq=?",
                        (index, json.dumps({"fixture_event": index}), row["seq"]),
                    )
            # A finished task followed by a representative unrelated event history.
            # Raw synthetic inserts avoid measuring dispatch/audit work during setup.
            seed_started = time.perf_counter_ns()
            with bridge.store.transaction():
                db.execute(
                    "INSERT INTO tasks(id,principal,idem,request_hash,operation,args,state,"
                    "created,updated) VALUES('noise','bench','noise','fixture','file.read',"
                    "'{}','completed',1,1)"
                )
                db.executemany(
                    "INSERT INTO events(task_id,at,state,evidence) VALUES('noise',?,'running',?)",
                    ((index, '{"synthetic":"' + "x" * 100 + '"}') for index in range(noise_events)),
                )
            seed_ms = (time.perf_counter_ns() - seed_started) / 1e6
            rows = list(db.execute(EVENT_SQL, (task_id, 0)))
            expected = {
                "events": [{**dict(row), "evidence": json.loads(row["evidence"])} for row in rows]
            }
            last = rows[-1]["seq"]
            output_reads = []
            original_read = bridge.outputs.read

            def counted_read(principal, reference):
                output_reads.append(reference["id"])
                return original_read(principal, reference)

            bridge.outputs.read = counted_read
            records = []
            for name, action, expected_value in (
                (
                    "standalone_events_4mib_output",
                    lambda: bridge.events("bench", task_id),
                    expected,
                ),
                (
                    "event_page_sql",
                    lambda: [tuple(row) for row in db.execute(EVENT_SQL, (task_id, 0))],
                    [tuple(row) for row in rows],
                ),
                (
                    "no_later_event_sql",
                    lambda: list(db.execute(MORE_SQL, (task_id, last))),
                    [],
                ),
            ):
                elapsed, cpu, reads = [], [], []
                for _ in range(rounds):
                    output_reads.clear()
                    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
                    result = action()
                    cpu.append((time.process_time_ns() - cpu_started) / 1e6)
                    elapsed.append((time.perf_counter_ns() - started) / 1e6)
                    reads.append(len(output_reads))
                    if result != expected_value:
                        raise RuntimeError("Event semantics changed: " + name)
                records.append(
                    {
                        "path": name,
                        "wall": summary(elapsed),
                        "cpu": summary(cpu),
                        "wall_samples_ms": elapsed,
                        "cpu_samples_ms": cpu,
                        "output_reads_per_call": sorted(set(reads)),
                    }
                )
            index_present = (
                db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='index' AND name='events_task_seq'"
                ).fetchone()
                is not None
            )
            query_plans = {
                "events": [
                    tuple(row)
                    for row in db.execute("EXPLAIN QUERY PLAN " + EVENT_SQL, (task_id, 0))
                ],
                "more": [
                    tuple(row)
                    for row in db.execute("EXPLAIN QUERY PLAN " + MORE_SQL, (task_id, last))
                ],
            }
            # Bound the one-time startup cost for an existing database separately.
            db.execute("DROP INDEX IF EXISTS events_task_seq")
            build_started = time.perf_counter_ns()
            with bridge.store.transaction():
                db.execute("CREATE INDEX events_task_seq ON events(task_id,seq)")
            index_build_ms = (time.perf_counter_ns() - build_started) / 1e6
            if before != {str(path): fingerprint(path) for path in files}:
                raise RuntimeError("Measured source files changed during the run")
            return {
                "label": label,
                "scope": (
                    "synthetic temporary SQLite/OutputHistory; "
                    "direct reads, no cloud/MCP serialization"
                ),
                "warmup": "none excluded; same-process SQLite/OS caches remain",
                "percentiles": "P50 median; P95 nearest rank",
                "source_sha256": before,
                "tasks": db.execute("SELECT count(*) FROM tasks").fetchone()[0],
                "events": db.execute("SELECT count(*) FROM events").fetchone()[0],
                "output_bytes": 4 * 1024 * 1024,
                "target_events": len(rows),
                "event_payload_sha256": hashlib.sha256(
                    json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "events_index_present_during_reads": index_present,
                "setup_noise_insert_ms": seed_ms,
                "separate_existing_history_index_build_ms": index_build_ms,
                "query_plans": query_plans,
                "records": records,
            }
        finally:
            bridge.store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rounds", type=int, choices=range(10, 101), default=30)
    parser.add_argument("--noise-events", type=int, choices=(40000, 100000), default=100000)
    args = parser.parse_args()
    result = benchmark(args.label, args.rounds, args.noise_events)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
