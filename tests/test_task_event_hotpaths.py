"""Event-only reads retain fresh ownership checks without loading task output."""

import json
import sqlite3

import pytest
from conftest import request

from kirabridge.bridge_core.models import BridgeError, State
from kirabridge.task_manager.store import SCHEMA_VERSION, Store


def completed_task(bridge, config):
    config.principals["local"].approval_mode = "automatic"
    value = request(
        "terminal.execute",
        {"argv": ["/bin/echo", "fixture"], "cwd": config.principals["local"].roots[0]},
        task_id="owned-events-fixture",
    )
    config.principals["local"].executables.append("/bin/echo")
    bridge.prepare("local", value)
    bridge.store.claim_exact("fixture", 30, value.task_id)
    bridge.store.transition(value.task_id, State.RUNNING, {"fixture": True}, owner="fixture")
    bridge.store.transition(
        value.task_id,
        State.COMPLETED,
        {"fixture": True},
        result={"stdout": "large synthetic output " * 8192, "stderr": "", "exit_code": 0},
        owner="fixture",
    )
    return value.task_id


def test_standalone_events_never_resolve_output_or_failed_task_diagnostics(
    bridge, config, monkeypatch
):
    task_id = completed_task(bridge, config)
    expected = {
        "events": [
            {**dict(row), "evidence": json.loads(row["evidence"])}
            for row in bridge.store.db.execute(
                "SELECT seq,at,state,evidence FROM events WHERE task_id=? ORDER BY seq", (task_id,)
            )
        ]
    }

    def no_output(*_args, **_kwargs):
        raise AssertionError("An event-only read must not load output or diagnostics")

    monkeypatch.setattr(bridge, "task", no_output)
    monkeypatch.setattr(bridge.outputs, "read", no_output)
    monkeypatch.setattr("kirabridge.diagnostics.task_report", no_output)
    for state in (State.COMPLETED, State.FAILED, State.UNKNOWN):
        bridge.store.db.execute("UPDATE tasks SET state=? WHERE id=?", (state, task_id))
        assert bridge.events("local", task_id) == expected
    after = expected["events"][2]["seq"]
    assert bridge.events("local", task_id, after) == {"events": expected["events"][3:]}


def test_event_rights_remain_fresh_and_foreign_ids_are_indistinguishable_from_missing(
    bridge, config
):
    task_id = completed_task(bridge, config)
    assert bridge.events("local", task_id)["events"]
    for identifier in (task_id, "no-such-task"):
        with pytest.raises(BridgeError) as error:
            bridge.events("other", identifier)
        assert error.value.code == "not_found"
        assert str(error.value) == "Task not found"
    config.principals["local"].capabilities.remove("task.read")
    with pytest.raises(BridgeError) as error:
        bridge.events("local", task_id)
    assert error.value.code == "forbidden"
    config.principals["local"].capabilities.append("task.read")
    assert bridge.events("local", task_id)["events"]


def test_index_upgrade_preserves_existing_rows_version_and_pagination(tmp_path):
    path = tmp_path / "state" / "bridge.sqlite3"
    store = Store(path)
    with store.transaction():
        store.db.execute("DROP INDEX events_task_seq")
        for task_id in ("old-owned", "old-unrelated"):
            store.db.execute(
                "INSERT INTO tasks(id,principal,idem,request_hash,operation,args,state,"
                "created,updated) VALUES(?,?,?,'fixture','file.read','{}','completed',1,1)",
                (task_id, "local", task_id),
            )
        store.db.executemany(
            "INSERT INTO events(task_id,at,state,evidence) VALUES(?,?,'running',?)",
            (
                ("old-owned" if i % 2 else "old-unrelated", i, json.dumps({"event": i}))
                for i in range(2400)
            ),
        )
    tables = {
        name: [tuple(row) for row in store.db.execute(f"SELECT * FROM {name} ORDER BY rowid")]
        for name in ("tasks", "events")
    }
    store.close()
    # Opening existing state upgrades the index without rewriting historical rows.
    # A second startup is idempotent and supports older code reading this same DB.
    for _ in range(2):
        reopened = Store(path)
        try:
            assert reopened.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
            for name, expected in tables.items():
                assert [
                    tuple(row)
                    for row in reopened.db.execute(f"SELECT * FROM {name} ORDER BY rowid")
                ] == expected
            for sql, parameters in (
                (
                    "SELECT seq,at,state,evidence FROM events WHERE task_id=? AND seq>? "
                    "ORDER BY seq LIMIT 1000",
                    ("old-owned", 0),
                ),
                ("SELECT 1 FROM events WHERE task_id=? AND seq>? LIMIT 1", ("old-owned", 2000)),
            ):
                plan = reopened.db.execute("EXPLAIN QUERY PLAN " + sql, parameters).fetchall()
                assert any("events_task_seq" in row["detail"] for row in plan)
            page = reopened.db.execute(
                "SELECT seq FROM events WHERE task_id='old-owned' AND seq>0 ORDER BY seq LIMIT 1000"
            ).fetchall()
            tail = reopened.db.execute(
                "SELECT seq FROM events WHERE task_id='old-owned' AND seq>? "
                "ORDER BY seq LIMIT 1000",
                (page[-1]["seq"],),
            ).fetchall()
            assert len(page) == 1000 and len(tail) == 200
            assert [row["seq"] for row in page + tail] == list(range(2, 2401, 2))
        finally:
            reopened.close()


def test_index_creation_failure_rolls_back_and_keeps_existing_state(tmp_path, monkeypatch):
    path = tmp_path / "state" / "bridge.sqlite3"
    store = Store(path)
    store.db.execute("DROP INDEX events_task_seq")
    before = list(store.db.iterdump())
    store.close()
    original_connect = sqlite3.connect
    opened = []

    def reject_index(*args, **kwargs):
        db = original_connect(*args, **kwargs)
        opened.append(db)
        db.set_authorizer(
            lambda action, *_args: (
                sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_INDEX else sqlite3.SQLITE_OK
            )
        )
        return db

    monkeypatch.setattr("kirabridge.task_manager.store.sqlite3.connect", reject_index)
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        Store(path)
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")
    with original_connect(path) as verify:
        assert list(verify.iterdump()) == before
