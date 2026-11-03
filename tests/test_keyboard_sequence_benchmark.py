"""Acceptance accounting catches hidden batching, duplicate posts and unknown replay."""

import hashlib
import importlib.util
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "sequence_benchmark", Path(__file__).parents[1] / "scripts/keyboard_sequence_benchmark.py"
)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class Receiver:
    def __init__(self, *, unknown=False):
        self.text, self.pairs, self.sequence = "", 0, 0
        self.calls, self.receipts, self.unknown = [], {}, unknown
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE tasks(id,state,created,accepted,started,finished)")
        self.bridge = SimpleNamespace(
            store=SimpleNamespace(db=db), events=lambda *_: {"events": []}
        )

    def snapshot(self):
        return {
            "text_sha256": hashlib.sha256(self.text.encode()).hexdigest(),
            "utf8_bytes": len(self.text),
            "utf16_units": len(self.text),
            "selection_utf16": {"location": len(self.text), "length": 0},
            "return_count": 0,
            "down_count": self.pairs,
            "up_count": self.pairs,
            "event_counts": {"key_down": self.pairs, "key_up": self.pairs},
            "event_records_dropped": 0,
            "clipboard_generation": 1,
            "event_sequence": self.sequence,
        }

    async def command(self, operation):
        if operation == "reset":
            self.text, self.pairs = "", 0
        return self.snapshot()

    async def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        if "task_id" not in arguments:
            return {"ok": True}
        identifier = arguments["task_id"]
        if identifier in self.receipts:
            return self.receipts[identifier]
        request = arguments["request"]
        steps = request["steps"] if tool == "keyboard_sequence" else [request]
        for step in steps:
            key = step["key"]
            character = " " if key.get("named") == "space" else key["character"]
            self.text += character.upper() if "shift" in step.get("modifiers", []) else character
            self.pairs += 1
            self.sequence += 2
        state = "unknown" if self.unknown else "completed"
        result = {
            "state": state,
            "result": {"completed_steps": len(steps), "post_calls_returned": 2 * len(steps)},
        }
        self.receipts[identifier] = result
        self.bridge.store.db.execute(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?)", (identifier, state, 1, 1, 1, 1)
        )
        return result


def test_p95_is_explicit_nearest_rank_and_receiver_rejects_duplicate_pairs():
    assert benchmark.summary(list(range(1, 21)))["p95_ms"] == 19
    assert benchmark.summary([1, 2, 3, 4, 5])["p95_ms"] == 5
    receiver = Receiver()
    receiver.text, receiver.pairs = "Stern am", 8
    assert benchmark.receiver_matches(receiver.snapshot())
    receiver.pairs = 16
    assert not benchmark.receiver_matches(receiver.snapshot())
    receiver.bridge.store.db.close()


async def test_same_workload_accounts_for_real_pairs_and_completed_idempotency():
    receiver = Receiver()
    records, ids, responses = [], [], set()
    try:
        result = await benchmark.run_key_rounds(
            call=receiver.call,
            fixture_command=receiver.command,
            bridge=receiver.bridge,
            app="owned.fixture",
            nonce="a" * 32,
            rounds=5,
            mode="both",
            record=lambda kind, value: records.append((kind, value)),
            task_ids=ids,
            responses=responses,
        )
        assert len(result["rounds"]) == 10 and len(ids) == len(responses) == 45
        assert len(receiver.calls) == 46  # 45 physical writes + completed receipt probe.
        assert result["summary"]["single"]["tool_calls"] == 40
        assert result["summary"]["sequence"]["tool_calls"] == 5
        assert result["summary"]["single"]["native_key_pairs"] == 40
        assert result["summary"]["sequence"]["native_key_pairs"] == 40
        assert result["rounds"][0]["mode"] == "single"
        assert result["rounds"][2]["mode"] == "sequence"
        assert receiver.text == "Stern am" and receiver.sequence == 160
        assert any(kind == "completed_sequence_idempotency" for kind, _ in records)
    finally:
        receiver.bridge.store.db.close()


async def test_unknown_stops_without_next_key_or_new_task_id():
    receiver = Receiver(unknown=True)
    ids, responses = [], set()
    try:
        with pytest.raises(RuntimeError, match="unknown"):
            await benchmark.run_key_rounds(
                call=receiver.call,
                fixture_command=receiver.command,
                bridge=receiver.bridge,
                app="owned.fixture",
                nonce="b" * 32,
                rounds=5,
                mode="single",
                record=lambda *_: None,
                task_ids=ids,
                responses=responses,
            )
        assert len(receiver.calls) == len(ids) == len(responses) == 1
        assert receiver.text == "S"
    finally:
        receiver.bridge.store.db.close()


async def test_read_only_domain_rounds_include_ten_samples_and_no_task_or_content():
    receiver = Receiver()
    try:
        result = await benchmark.run_read_rounds(call=receiver.call, record=lambda *_: None)
        assert len(result["samples"]) == 40
        assert all(row["count"] == 10 for row in result["summary"].values())
        assert len(receiver.receipts) == 0 and receiver.text == ""
    finally:
        receiver.bridge.store.db.close()


def test_only_permission_observation_time_is_excluded_from_semantic_comparison():
    first = {"permissions": [{"state": "granted", "observed_at": 1}], "revision": "same"}
    second = {"permissions": [{"state": "granted", "observed_at": 2}], "revision": "same"}
    assert benchmark.stable_permission_observations(
        first
    ) == benchmark.stable_permission_observations(second)
    second["permissions"][0]["state"] = "denied"
    assert benchmark.stable_permission_observations(
        first
    ) != benchmark.stable_permission_observations(second)
