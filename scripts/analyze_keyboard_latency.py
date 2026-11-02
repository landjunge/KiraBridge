#!/usr/bin/env python3
"""Export bounded, content-free task timings from a read-only bridge database."""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from datetime import datetime, timezone
from pathlib import Path

EVENT_TYPES = {
    "automatic_keyboard_resolution",
    "automatic_keyboard_target_bound",
    "native_keyboard_attempt",
}


def summarize(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "min_ms": None, "p50_ms": None, "max_ms": None, "sum_ms": 0}
    return {
        "n": len(values),
        "min_ms": min(values),
        "p50_ms": statistics.median(values),
        "max_ms": max(values),
        "sum_ms": sum(values),
    }


def milliseconds(start: float | None, end: float | None) -> float | None:
    return None if start is None or end is None else (end - start) * 1000


def export_task(connection: sqlite3.Connection, task: sqlite3.Row) -> dict:
    result = {
        key: task[key]
        for key in (
            "id",
            "principal",
            "operation",
            "state",
            "created",
            "accepted",
            "started",
            "finished",
        )
    }
    result["has_error"] = task["error"] is not None
    events = []
    for event in connection.execute(
        "SELECT seq, at, state, evidence FROM events WHERE task_id=? ORDER BY seq", (task["id"],)
    ):
        evidence = json.loads(event["evidence"])
        record = {key: event[key] for key in ("seq", "at", "state")}
        if evidence.get("evidence_type") in EVENT_TYPES:
            record["evidence_type"] = evidence["evidence_type"]
        events.append(record)
    result["events"] = events
    native_result = json.loads(task["result"] or "{}")
    result["receipt"] = {
        key: native_result[key]
        for key in ("automatic_retry", "app_processing_confirmed", "post_calls_returned")
        if key in native_result
    }
    result["completion_notices"] = [
        {key: row[key] for key in ("created", "delivered", "acknowledged")}
        for row in connection.execute(
            "SELECT created, delivered, acknowledged FROM completion_notices "
            "WHERE source='task' AND source_id=? ORDER BY seq",
            (task["id"],),
        )
    ]
    times = {
        event.get("evidence_type"): event["at"] for event in events if "evidence_type" in event
    }
    stages = {
        "created_to_accepted": (task["created"], task["accepted"]),
        "accepted_to_started": (task["accepted"], task["started"]),
        "started_to_target_bound": (task["started"], times.get("automatic_keyboard_target_bound")),
        "target_bound_to_native_attempt": (
            times.get("automatic_keyboard_target_bound"),
            times.get("native_keyboard_attempt"),
        ),
        "native_attempt_to_finished": (times.get("native_keyboard_attempt"), task["finished"]),
        "started_to_finished": (task["started"], task["finished"]),
        "created_to_finished": (task["created"], task["finished"]),
    }
    result["durations_ms"] = {key: milliseconds(*value) for key, value in stages.items()}
    return result


def analyze(db: Path, prefix: str, include_tasks: list[str] | None = None) -> dict:
    if not prefix:
        raise ValueError("A nonempty literal task prefix is required")
    # Path.as_uri escapes URI metacharacters. No writes, migrations, checkpoint or schema changes.
    connection = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        # A literal prefix, including underscores and percent signs; no LIKE wildcards.
        rows = connection.execute(
            "SELECT id, principal, operation, state, created, accepted, started, finished, "
            "error, result FROM tasks WHERE substr(id,1,?)=? ORDER BY created, id LIMIT 1001",
            (len(prefix), prefix),
        ).fetchall()
        if len(rows) > 1000:
            raise ValueError("Prefix matches more than 1000 tasks; choose a narrower prefix")
        tasks = [export_task(connection, row) for row in rows]
        metrics: dict[str, list[float]] = {}
        for index, task in enumerate(tasks):
            if index:
                previous = tasks[index - 1]
                task["durations_ms"]["between_admissions"] = milliseconds(
                    previous["created"], task["created"]
                )
                task["durations_ms"]["previous_finished_to_created"] = milliseconds(
                    previous["finished"], task["created"]
                )
            for name, value in task["durations_ms"].items():
                if value is not None:
                    metrics.setdefault(name, []).append(value)
        requested_tasks = list(dict.fromkeys(include_tasks or []))
        additional = []
        for task_id in requested_tasks:
            row = connection.execute(
                "SELECT id, principal, operation, state, created, accepted, started, finished, "
                "error, result FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()
            additional.append(
                export_task(connection, row) if row else {"id": task_id, "exists": False}
            )
        diagnostic = connection.execute(
            "SELECT count(*) AS records, max(at) AS last_at FROM audit "
            "WHERE kind='diagnostic.connection'"
        ).fetchone()
        wall_ms = milliseconds(tasks[0]["created"], tasks[-1]["finished"]) if tasks else None
        return {
            "schema_version": 1,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": "bridge.sqlite3 read-only snapshot transaction",
            "timestamp_unit": "Unix epoch seconds UTC; historical wall clock, not monotonic",
            "prefix": prefix,
            "task_count": len(tasks),
            "states": {
                state: sum(t["state"] == state for t in tasks)
                for state in sorted({t["state"] for t in tasks})
            },
            "first_created_to_last_finished_ms": wall_ms,
            "statistics": {name: summarize(values) for name, values in metrics.items()},
            "tasks": tasks,
            "additional_tasks": additional,
            "historical_connection_diagnostics": dict(diagnostic),
            "limits": [
                "Task persistence follows MCP ingress and precedes returned tool response.",
                "Between-task gaps include transport return, orchestration and next ingress.",
                "Native posting receipts do not prove application consumption.",
                "No inference about absent pre-admission requests from missing tasks.",
                "Undelivered completion notices do not imply missing synchronous tool responses.",
                "The platform tool-call-limit error is user-reported, not measured by this export.",
            ],
        }
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--include-task", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.output.resolve() == args.db.resolve():
        parser.error("Output must not overwrite the source database")
    result = json.dumps(analyze(args.db, args.prefix, args.include_task), indent=2) + "\n"
    if args.output:
        args.output.write_text(result, encoding="utf-8")
    else:
        print(result, end="")


if __name__ == "__main__":
    main()
