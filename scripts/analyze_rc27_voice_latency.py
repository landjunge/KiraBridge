#!/usr/bin/env python3
"""Content-free, read-only export of the RC27 Voice repro and exact event phases."""

import argparse
import json
import math
import sqlite3
import statistics
from pathlib import Path

from analyze_keyboard_latency import EVENT_TYPES, analyze

EVENT_TYPES.add("native_keyboard_commit_attempt")


def quantiles(values):
    ordered = sorted(values)
    return {
        "n": len(values),
        "total_ms": sum(values),
        "p50_ms": statistics.median(values),
        "p95_nearest_rank_ms": ordered[math.ceil(0.95 * len(values)) - 1],
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
    }


def export(db):
    data = analyze(
        db,
        "rc27_realkeys_20261103_0042_",
        ["rc27_long_poem_20261103_0040", "rc27_poem_20261103_0037"],
    )
    data["quantile_method"] = "median; p95 nearest rank ceil(.95*n); n=8 p95 is maximum"
    data["statistics"] = {
        key: quantiles(
            [
                t["durations_ms"][key]
                for t in data["tasks"]
                if t["durations_ms"].get(key) is not None
            ]
        )
        for key in data["statistics"]
    }
    internal = data["statistics"]["created_to_finished"]["total_ms"]
    window = data["first_created_to_last_finished_ms"]
    data["external_user_report"] = {
        "keys_total_ms": 42504,
        "scope": "User-reported ChatGPT Voice total; no independent voice/model boundary clock",
        "minus_persisted_window_ms": 42504 - window,
        "minus_sum_internal_tasks_ms": 42504 - internal,
        "internal_share_of_reported_total_percent": 100 * internal / 42504,
        "block_text_characters_reported": 568,
        "block_text_total_ms_reported": 3426,
    }
    data["persisted_window_outside_task_ms"] = window - internal
    data["outside_share_of_persisted_window_percent"] = 100 * (window - internal) / window
    connection = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    try:
        for task in data["additional_tasks"]:
            row = connection.execute("SELECT args FROM tasks WHERE id=?", (task["id"],)).fetchone()
            text = json.loads(row[0])["text"]
            task["input_counts_only"] = {
                "codepoints": len(text),
                "without_edge_linebreaks": len(text.strip("\r\n")),
                "utf8_bytes": len(text.encode()),
                "utf16_units": len(text.encode("utf-16-le")) // 2,
            }
            commits = [
                e["at"]
                for e in task["events"]
                if e.get("evidence_type") == "native_keyboard_commit_attempt"
            ]
            task["commit_attempt_to_finished_ms"] = (
                (task["finished"] - commits[-1]) * 1000 if commits else None
            )
    finally:
        connection.close()
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    if options.db.resolve() == options.output.resolve():
        parser.error("Output must not overwrite database")
    result = export(options.db)
    options.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "tasks": result["task_count"],
                "internal": result["statistics"]["created_to_finished"],
                "persisted_window_ms": result["first_created_to_last_finished_ms"],
                "outside_task_share_percent": result["outside_share_of_persisted_window_percent"],
                "additional": [
                    {
                        "id": t["id"],
                        "counts": t["input_counts_only"],
                        "task_ms": t["durations_ms"]["created_to_finished"],
                        "commit_ms": t["commit_attempt_to_finished_ms"],
                    }
                    for t in result["additional_tasks"]
                ],
            }
        )
    )
