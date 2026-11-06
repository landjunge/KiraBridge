"""Closure requires acceptance plus board readback and never polls terminal work."""

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

from test_coordinator_runtime import runtime


def test_closure_requires_each_evidence_and_survives_restart():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE autonext_items(task_id,grant_id,receipt,state);
        CREATE TABLE autonext_outbox(task_id,grant_id,phase,verified,content);
        INSERT INTO autonext_items VALUES('a','g',NULL,'completed');
    """)
    bridge = SimpleNamespace(store=SimpleNamespace(db=db))
    assert runtime.closure_status(bridge) == {"closed": [], "missing": ["a: Abnahmebeleg fehlt"]}
    receipt = {"task_id": "a", "accepted_at": 1}
    db.execute("UPDATE autonext_items SET receipt=?", (json.dumps(receipt),))
    assert "Board-Readback" in runtime.closure_status(bridge)["missing"][0]
    db.execute("INSERT INTO autonext_outbox VALUES('a','other','completed',1,'{}')")
    assert not runtime.closure_status(bridge)["closed"]
    db.execute("INSERT INTO autonext_outbox VALUES('a','g','completed',0,'{}')")
    assert not runtime.closure_status(bridge)["closed"]
    db.execute("UPDATE autonext_outbox SET verified=1")
    assert "stimmt nicht" in runtime.closure_status(bridge)["missing"][0]
    db.execute(
        "UPDATE autonext_outbox SET content=?",
        (json.dumps({"receipt_sha256": runtime.digest(receipt)}),),
    )
    assert runtime.closure_status(bridge) == {"closed": ["a"], "missing": []}
    assert runtime.closure_status(SimpleNamespace(store=bridge.store)) == runtime.closure_status(
        bridge
    )


def test_terminal_and_missing_evidence_do_not_wait_for_worker_status():
    for state in ("complete", "stopped", "idle", "disabled"):
        assert not runtime.should_wait_for_status({"state": state})
    assert runtime.should_wait_for_status({"state": "waiting"})


def test_final_report_has_stable_deduplication_id_and_payload():
    with patch.object(runtime, "run_status_report") as send:
        for _ in range(2):
            runtime.report(
                {"report_cli": "report", "instance": "fixture"},
                ["a"],
                "Abschluss belegt",
                "done",
                report_id="closure-a",
                next_step="Auftrag abgeschlossen",
            )
        assert send.call_args_list[0] == send.call_args_list[1]
        assert send.call_args.kwargs["report_id"] == "closure-a"
