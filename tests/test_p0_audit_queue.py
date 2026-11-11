"""P0 10.11.: lossless diagnostic overflow, bounded task results, stale/capped queues."""

import asyncio
import json
import time
from pathlib import Path

import pytest
from conftest import request, submit

from kirabridge import diagnostics
from kirabridge.audit_manager import verify
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.diagnostics import AuditObserver, verify_archive
from kirabridge.storage_compaction import compact, restore


def hot_diagnostics(store):
    return store.db.execute("SELECT count(*) FROM audit WHERE kind LIKE 'diagnostic.%'").fetchone()[
        0
    ]


def test_more_than_20000_events_without_loss_and_intact_chains(bridge, config, monkeypatch):
    monkeypatch.setattr(diagnostics.os, "fsync", lambda fd: None)  # speed only
    config.diagnostics.max_records = config.diagnostics.max_events_per_day = 1000
    observer = AuditObserver(config, "local", bridge.runtime, bridge.store)
    total = 21000
    for index in range(total):
        assert observer("connection", {"phase": "connect.started", "connection_id": str(index)})
    archive = verify_archive(config.state_path)
    assert observer.dropped == 0 and observer.status()["recording"] == "budget_exhausted"
    assert hot_diagnostics(bridge.store) == 1000 and archive["valid"]
    assert archive["records"] == observer.archived == total - 1000
    assert verify(bridge.store)["valid"]


def test_archive_rotation_is_bounded_and_anchored_in_audit_chain(bridge, config, monkeypatch):
    monkeypatch.setattr(diagnostics, "ARCHIVE_SEGMENT_BYTES", 8192)
    monkeypatch.setattr(diagnostics, "ARCHIVE_SEGMENTS", 2)
    config.diagnostics.max_records = 10
    observer = AuditObserver(config, "local", bridge.runtime, bridge.store)
    for _ in range(200):
        assert observer("connection", {"phase": "connect.started"})
    rotated = sorted(config.state_path.glob("diagnostic-archive.*.jsonl"))
    assert len(rotated) == 2 and verify_archive(config.state_path)["valid"]
    anchors = bridge.store.db.execute(
        "SELECT metadata FROM audit WHERE kind='audit.diagnostic_archive_rotated'"
    ).fetchall()
    assert anchors and any(json.loads(a[0])["removed_segments"] for a in anchors)
    assert verify(bridge.store)["valid"]


def test_successful_routine_read_polls_bypass_hot_budget(bridge, config):
    observer = AuditObserver(config, "local", bridge.runtime, bridge.store)
    for tool in ("bridge_health", "read_query", "task_get"):
        assert observer("connection", {"phase": "call.started", "tool": tool})
        assert observer("connection", {"phase": "call.returned", "tool": tool})
    assert hot_diagnostics(bridge.store) == 0 and observer.archived == 6
    # Failures and task-bound calls stay hot evidence.
    observer("connection", {"phase": "call.returned", "tool": "task_get", "error_code": "x"})
    observer("connection", {"phase": "call.started", "tool": "task_request"}, task_id="t-1")
    assert hot_diagnostics(bridge.store) == 2


async def test_large_result_is_stored_bounded_and_resolved_transparently(bridge, config):
    root = config.principals["local"].roots[0]
    text = "x" * 60000
    path = f"{root}/large.txt"
    Path(path).write_text(text)
    value = request("file.read", {"path": path}, task_id="large-read")
    submit(bridge, value)
    async with bridge:
        task = await bridge.tasks.wait("local", value.task_id, 5)
        assert task["state"] == "completed" and task["result"]["text"] == text
        assert task["result"]["output_status"] == "available"
        stored = bridge.store.db.execute("SELECT result FROM tasks WHERE id=?", ("large-read",))
        assert len(stored.fetchone()[0]) < 4096
        kinds = bridge.store.db.execute("SELECT DISTINCT kind FROM output_snapshots").fetchall()
        assert {k[0] for k in kinds} == {"task_result"}
        assert verify(bridge.store)["valid"]


def age(bridge, task_id, seconds):
    db = bridge.store.db
    db.execute("UPDATE tasks SET created=created-? WHERE id=?", (seconds, task_id))
    db.execute("UPDATE events SET at=at-? WHERE task_id=?", (seconds, task_id))


def started(bridge, task_id):
    return bridge.store.db.execute(
        "SELECT count(*) FROM events WHERE task_id=? AND state IN ('accepted','running')",
        (task_id,),
    ).fetchone()[0]


async def test_undelivered_task_done_directly_is_never_executed_late(bridge, config):
    root = config.principals["local"].roots[0]
    target = f"{root}/result.txt"
    value = request("file.write", {"path": target, "text": "from queue A"}, task_id="a")
    submit(bridge, value)
    # Delivery did not happen; the same work was then done in the visible terminal.
    Path(target).write_text("done directly")
    age(bridge, "a", config.queue_stale_seconds + 60)
    async with bridge:
        task = await bridge.tasks.wait("local", "a", 3)
        assert task["state"] == "blocked"
        assert task["evidence"]["reason"] == "stale_queue_expired"
        assert task["evidence"]["automatic_retry"] is False and started(bridge, "a") == 0
    assert Path(target).read_text() == "done directly"


async def test_waiting_cap_rejects_new_task_and_never_cancels_existing(bridge, config):
    config.max_queued = 3
    for index in range(3):
        submit(
            bridge,
            request(
                "file.list", {"path": config.principals["local"].roots[0]}, task_id=f"q{index}"
            ),
        )
    with pytest.raises(BridgeError) as refused:
        submit(
            bridge,
            request("file.list", {"path": config.principals["local"].roots[0]}, task_id="q-new"),
        )
    assert refused.value.code == "queue_full"
    for index in range(3):
        assert bridge.store.get(f"q{index}")["state"] == "queued"
    assert (
        bridge.store.db.execute("SELECT count(*) FROM tasks WHERE state='cancelled'").fetchone()[0]
        == 0
    )
    assert (
        bridge.store.db.execute(
            "SELECT count(*) FROM audit WHERE kind='task.superseded_by_queue_cap'"
        ).fetchone()[0]
        == 0
    )
    assert bridge.store.db.execute("SELECT count(*) FROM tasks WHERE id='q-new'").fetchone()[0] == 0
    async with bridge:
        for index in range(3):
            assert (await bridge.tasks.wait("local", f"q{index}", 5))["state"] == "completed"
        assert all(started(bridge, f"q{index}") for index in range(3))
    again = Bridge(config)  # restart: completed work is retained, not revived
    try:
        async with again:
            await asyncio.sleep(0.5)
            for index in range(3):
                assert again.store.get(f"q{index}")["state"] == "completed"
            assert verify(again.store)["valid"]
    finally:
        again.store.close()


def test_compaction_is_backed_up_reversible_and_keeps_unknown(bridge, tmp_path):
    db = bridge.store.db
    big = {"text": "y" * 50000, "content_sha256": "abc", "scope": "file"}
    now = time.time()
    for task_id, state in (("done", "completed"), ("open", "unknown")):
        db.execute(
            "INSERT INTO tasks(id,principal,idem,request_hash,operation,args,state,created,"
            "updated,result) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (task_id, "local", task_id, "h", "file.read", "{}", state, now, now, canonical(big)),
        )
    with bridge.store.transaction():
        bridge.store.audit("test.seed", "local", None, {})
    original = {r[0]: r[1] for r in db.execute("SELECT id,result FROM tasks")}
    path = bridge.config.state_path / "bridge.sqlite3"
    bridge.store.close()
    report = compact(path, tmp_path / "backup", apply=True)
    assert report["tasks"] == 1 and report["audit_after"]["valid"]
    assert (
        len(report["backup_sha256"]) == 64 and report["db_bytes_after"] < report["db_bytes_before"]
    )
    reopened = Bridge(bridge.config)
    try:
        rows = {r[0]: r[1] for r in reopened.store.db.execute("SELECT id,result FROM tasks")}
        assert rows["open"] == original["open"]  # UNKNOWN stays byte-identical
        assert json.loads(rows["done"])["output_archived"]["fields"] == ["text"]
    finally:
        reopened.store.close()
    assert restore(path, report["manifest"])["audit"]["valid"]
    reopened = Bridge(bridge.config)
    try:
        rows = {r[0]: r[1] for r in reopened.store.db.execute("SELECT id,result FROM tasks")}
        assert rows == original
    finally:
        reopened.store.close()
