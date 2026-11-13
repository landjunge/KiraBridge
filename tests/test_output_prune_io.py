"""Synthetic snapshot housekeeping; no installed databases or native processes."""

from types import SimpleNamespace

from test_output_history import manual_running, observed

from kirabridge.bridge_core.models import State


def test_prune_plans_use_indexes_without_payload_table_scans(bridge):
    statements = []
    bridge.store.db.set_trace_callback(statements.append)
    try:
        bridge.outputs.prune()
    finally:
        bridge.store.db.set_trace_callback(None)
    deletes = [sql for sql in statements if sql.startswith("DELETE FROM output_snapshots")]
    assert len(deletes) == 2
    for sql in deletes:
        plan = " ".join(row[3] for row in bridge.store.db.execute("EXPLAIN QUERY PLAN " + sql))
        assert "SEARCH output_snapshots USING INDEX output_snapshot_" in plan
        assert "SCAN output_snapshots" not in plan
    aggregate = next(sql for sql in statements if "GROUP BY kind" in sql)
    plan = " ".join(row[3] for row in bridge.store.db.execute("EXPLAIN QUERY PLAN " + aggregate))
    assert "COVERING INDEX output_snapshot_budget" in plan
    assert "TEMP B-TREE" not in plan
    plan = " ".join(
        row[3]
        for row in bridge.store.db.execute(
            "EXPLAIN QUERY PLAN SELECT id,bytes FROM output_snapshots "
            "WHERE kind=? ORDER BY created,rowid LIMIT 1",
            ("session_capture",),
        )
    )
    assert "output_snapshot_oldest" in plan and "TEMP B-TREE" not in plan


def test_prune_retains_union_boundaries_and_unknown_tasks(bridge, config, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("kirabridge.output_history.time", SimpleNamespace(time=lambda: clock[0]))
    config.output_history.retention_seconds = 60
    refs = [observed(bridge, str(i), f"terminal:{i}")["output_ref"] for i in range(4)]
    db = bridge.store.db
    db.execute("UPDATE output_snapshots SET expires=1000 WHERE id=?", (refs[0]["id"],))
    db.execute("UPDATE output_snapshots SET created=940 WHERE id=?", (refs[1]["id"],))
    db.execute("UPDATE output_snapshots SET created=940,expires=1000 WHERE id=?", (refs[2]["id"],))
    task = manual_running(bridge, config)
    bridge.store.transition(
        task.task_id, State.UNKNOWN, {"automatic_retry": False}, owner="test-owner"
    )
    task_before = tuple(db.execute("SELECT * FROM tasks WHERE id=?", (task.task_id,)).fetchone())
    audit_before = [tuple(row) for row in db.execute("SELECT * FROM audit")]
    bridge.outputs.prune()
    assert [row[0] for row in db.execute("SELECT id FROM output_snapshots")] == [refs[3]["id"]]
    assert (
        tuple(db.execute("SELECT * FROM tasks WHERE id=?", (task.task_id,)).fetchone())
        == task_before
    )
    assert [tuple(row) for row in db.execute("SELECT * FROM audit")] == audit_before


def test_worker_maintenance_coalesces_without_delaying_capture_budgets_or_read_expiry(
    bridge, config, monkeypatch
):
    wall, monotonic = [1000.0], [10.0]
    monkeypatch.setattr(
        "kirabridge.output_history.time",
        SimpleNamespace(time=lambda: wall[0], monotonic=lambda: monotonic[0]),
    )
    config.output_history.retention_seconds = 60
    config.output_history.max_entries = 1
    first = observed(bridge, "first")["output_ref"]
    original, calls = bridge.outputs.prune, []

    def prune():
        calls.append(True)
        original()

    monkeypatch.setattr(bridge.outputs, "prune", prune)
    bridge.outputs.maintain()
    bridge.outputs.maintain()
    assert len(calls) == 1
    second = observed(bridge, "second", "terminal:second")["output_ref"]
    assert bridge.outputs.read("local", first)[0] is None  # Immediate insertion budget.
    assert len(calls) == 3  # Capture never uses the maintenance throttle.
    wall[0] += 60
    monotonic[0] += 0.5
    bridge.outputs.maintain()
    assert len(calls) == 3
    assert bridge.outputs.read("local", second) == (None, "expired")
    assert (
        bridge.outputs.captured_text(
            "local", "session_capture", "terminal:second:123", second["sha256"]
        )
        is None
    )
    config.output_history.max_entries = 2
    bridge.outputs.maintain()  # Changed policy bypasses the throttle.
    assert len(calls) == 4
    assert bridge.outputs.status()["entries"] == 0
    monotonic[0] += 1
    bridge.outputs.maintain()
    assert len(calls) == 5


def test_indexed_oldest_keeps_insertion_order_for_equal_timestamps(bridge, config, monkeypatch):
    monkeypatch.setattr("kirabridge.output_history.time", SimpleNamespace(time=lambda: 1000.0))
    config.output_history.max_entries = 2
    refs = [observed(bridge, str(i), f"terminal:{i}")["output_ref"] for i in range(3)]
    assert bridge.outputs.read("local", refs[0])[0] is None
    assert all(bridge.outputs.read("local", ref)[1] == "available" for ref in refs[1:])
