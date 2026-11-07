"""Stored-only retirement diagnostics; no native terminal or production database access."""

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.visible_handoff import VisibleHandoffs
from kirabridge.visible_message_evidence import visible_message_evidence


@pytest.mark.parametrize("mode", ["retired", "view_withdrawn", "legacy_without_holds"])
def test_handoff_diagnostics_distinguish_retirement_from_unknown_view_withdrawal(mode):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE messages(id TEXT PRIMARY KEY,sender TEXT,recipient TEXT);
        CREATE TABLE visible_handoffs(id TEXT PRIMARY KEY,principal TEXT,target TEXT,
            message_id TEXT,state TEXT,updated REAL,evidence TEXT,binding TEXT);
        CREATE TABLE visible_handoff_events(seq INTEGER PRIMARY KEY,id TEXT,
            state TEXT,at REAL,evidence TEXT);
        CREATE TABLE queue_withdrawals(queue_id TEXT,item_id TEXT);
        INSERT INTO messages VALUES('msg','chatgpt','codex');
        INSERT INTO visible_handoffs VALUES('run','chatgpt','codex','msg','unknown',1,
            '{"reason":"visible_insert_unknown","prompt":"PRIVATE"}','{}');
        INSERT INTO visible_handoff_events VALUES(1,'run','unknown',1,'{}');
    """)
    if mode != "legacy_without_holds":
        db.execute("CREATE TABLE queue_holds(queue_id TEXT,item_id TEXT)")
    if mode == "retired":
        db.execute("INSERT INTO queue_holds VALUES('handoffs','run')")
    elif mode == "view_withdrawn":
        db.execute("INSERT INTO queue_withdrawals VALUES('handoffs','run')")
    before = list(db.iterdump())
    manager = SimpleNamespace(
        store=SimpleNamespace(db=db), security=SimpleNamespace(principal=Mock())
    )
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
    db.set_authorizer(
        lambda action, *unused: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY
    )
    try:
        status = VisibleHandoffs.status(manager, "chatgpt", "run")
        evidence = visible_message_evidence(db, "chatgpt", "msg", "run")
        for result in (status, evidence):
            assert result["state"] == "unknown"
            assert result["delivery_retired"] is (mode == "retired")
            assert result["execution_reservation_active"] is (mode != "retired")
            assert result["next_step"] == (
                "retired_history_do_not_resend"
                if mode == "retired"
                else "inspect_original_handoff_without_repeating_input"
            )
        assert status["evidence"]["prompt"] == "PRIVATE"
        assert len(status["events"]) == 1
        assert "PRIVATE" not in json.dumps(evidence)
        assert evidence["automatic_retry_permitted"] is False
        with pytest.raises(BridgeError) as exc:
            VisibleHandoffs.status(manager, "outsider", "run")
        assert exc.value.code == "not_found"
        assert visible_message_evidence(db, "outsider", "msg", "run") is None
        manager.security.principal.assert_any_call("chatgpt", "task.read")
    finally:
        db.set_authorizer(None)
    assert list(db.iterdump()) == before
    # A terminal execution state is never reported as an active reservation,
    # including on a legacy schema that has no delivery-hold table.
    db.execute("UPDATE visible_handoffs SET state='completed'")
    assert not VisibleHandoffs.status(manager, "chatgpt", "run")["execution_reservation_active"]
    assert not visible_message_evidence(db, "chatgpt", "msg", "run")["execution_reservation_active"]
    db.close()
