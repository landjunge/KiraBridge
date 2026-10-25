import json
from types import SimpleNamespace

import pytest
from conftest import archive_task, request

from kirabridge.audit_manager import verify
from kirabridge.bridge_core.models import BridgeError, State
from kirabridge.operator_application import operator_application


def observed(bridge, text, pane="terminal:100:ttys001"):
    return bridge.outputs.observe_terminal(
        "local",
        {
            "pane_id": pane,
            "expected_pid": 123,
            "text": text,
            "scope": "test transport snapshot",
        },
    )


def manual_running(
    bridge, config, identifier="raw-task", operation="terminal.execute", principal="local"
):
    config.principals[principal].approval_mode = "automatic"
    config.principals[principal].capabilities += ["session.inspect"]
    args = {"argv": ["/bin/echo", "test"], "cwd": config.principals[principal].roots[0]}
    if operation == "session.read":
        args = {"pane_id": "terminal:100:ttys001", "expected_pid": 123}
    task = request(operation, args, task_id=identifier)
    archive_task(bridge, task, principal)
    bridge.store.claim("test-owner", 30, control="read" if operation == "session.read" else False)
    bridge.store.transition(identifier, State.RUNNING, {"test_transport": True}, owner="test-owner")
    return task


def complete(bridge, identifier, result):
    bridge.store.transition(
        identifier, State.COMPLETED, {"returned": True}, result=result, owner="test-owner"
    )


def test_completed_output_remains_readable_without_raw_task_audit_or_notice_copies(bridge, config):
    task = manual_running(bridge, config)
    marker = "RAW_STREAM_ONLY_IN_BOUNDED_STORE"
    complete(bridge, task.task_id, {"stdout": marker, "stderr": "", "exit_code": 0})
    result = bridge.task("local", task.task_id)["result"]
    assert result["stdout"] == marker and result["output_available"]
    stored = bridge.store.db.execute(
        "SELECT result FROM tasks WHERE id=?", (task.task_id,)
    ).fetchone()[0]
    assert marker not in stored and json.loads(stored)["output_codec"] == 1
    for table, column in (("audit", "metadata"), ("completion_notices", "payload")):
        assert all(
            marker not in row[0] for row in bridge.store.db.execute(f"SELECT {column} FROM {table}")
        )
    payload = bridge.store.db.execute("SELECT payload FROM output_snapshots").fetchone()[0]
    assert marker.encode() in payload and verify(bridge.store)["valid"]


def test_direct_and_queued_session_reads_share_one_snapshot_and_keep_protocol_output(
    bridge, config
):
    marker = "VISIBLE_CAPTURE_WITHOUT_PERMANENT_RAW_COPY"
    first = observed(bridge, marker)
    second = observed(bridge, marker)
    assert first["output_ref"] == second["output_ref"]
    task = manual_running(bridge, config, operation="session.read")
    complete(bridge, task.task_id, first)
    assert bridge.task("local", task.task_id)["result"]["text"] == marker
    assert bridge.store.db.execute("SELECT count(*) FROM output_snapshots").fetchone()[0] == 1
    assert marker not in bridge.store.db.execute("SELECT result FROM tasks").fetchone()[0]
    changes = bridge.store.db.total_changes
    page = operator_application(bridge).control.queries.protocol()
    assert any(
        e["kind"] == "terminal.output" and e["details"].get("text") == marker
        for e in page["entries"]
    )
    assert bridge.store.db.total_changes == changes


def test_ownership_and_hash_mismatch_do_not_expose_capture_contents(bridge):
    result = observed(bridge, "PRIVATE_TERMINAL_CONTENT")
    ref = result["output_ref"]
    assert bridge.outputs.read("other", ref)[0] is None
    assert bridge.outputs.read("local", {**ref, "sha256": "0" * 64}) == (None, "integrity_mismatch")
    bridge.store.db.execute(
        "UPDATE output_snapshots SET payload=? WHERE id=?", (b'{"text":"tampered"}', ref["id"])
    )
    assert bridge.outputs.read("local", ref) == (None, "integrity_mismatch")
    assert verify(bridge.store)["valid"]  # The immutable audit was not changed.


def test_count_and_byte_bounds_evict_raw_payloads_without_deleting_audit(bridge):
    bridge.config.output_history.max_entries = 2
    refs = [observed(bridge, str(i), f"terminal:{100 + i}:ttys001")["output_ref"] for i in range(3)]
    assert bridge.outputs.status()["entries"] == 2
    assert bridge.outputs.read("local", refs[0])[0] is None
    audit = [tuple(row) for row in bridge.store.db.execute("SELECT * FROM audit")]
    bridge.config.output_history.max_bytes = 4096
    bridge.config.output_history.max_item_bytes = 4096
    for i in range(3):
        observed(bridge, str(i) * 3000, f"terminal:{200 + i}:ttys001")
    status = bridge.outputs.status()
    assert status["entries"] <= 2 and status["payload_bytes"] <= 4096
    assert [
        tuple(row) for row in bridge.store.db.execute("SELECT * FROM audit LIMIT ?", (len(audit),))
    ] == audit
    assert verify(bridge.store)["valid"]


def test_multibyte_truncation_is_explicit_and_hashes_the_retained_payload(bridge):
    bridge.config.output_history.max_item_bytes = 1024
    result = observed(bridge, "Anfang\n" + "🧡" * 1000 + "\nENDE")
    ref = result["output_ref"]
    payload, status = bridge.outputs.read("local", ref)
    assert status == "available" and payload["text"].endswith("ENDE")
    assert ref["truncated"] and ref["bytes"] <= 1024 < ref["original_bytes"]


def test_truncated_direct_and_queued_results_keep_the_same_capture_reference(bridge, config):
    bridge.config.output_history.max_item_bytes = 1024
    direct = observed(bridge, "prefix " + "🧡" * 1000 + " ENDE")
    task = manual_running(bridge, config, operation="session.read")
    complete(bridge, task.task_id, direct)
    queued = bridge.task("local", task.task_id)["result"]
    assert queued == direct and queued["output_truncated"]
    assert queued["output_ref"]["original_bytes"] > 1024
    assert bridge.outputs.status()["entries"] == 1


def test_retention_does_not_slide_or_rewrite_old_audit(bridge, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("kirabridge.output_history.time", SimpleNamespace(time=lambda: clock[0]))
    bridge.config.output_history.retention_seconds = 60
    with bridge.store.transaction():
        bridge.store.audit("terminal.output", "local", None, {"text": "LEGACY_RAW_HISTORY"})
    old = tuple(bridge.store.db.execute("SELECT * FROM audit ORDER BY seq LIMIT 1").fetchone())
    result = observed(bridge, "new capture")
    clock[0] += 30
    assert observed(bridge, "new capture")["output_ref"] == result["output_ref"]
    clock[0] += 31
    assert bridge.outputs.read("local", result["output_ref"]) == (None, "expired")
    bridge.outputs.prune()
    assert bridge.outputs.status()["entries"] == 0
    assert (
        tuple(bridge.store.db.execute("SELECT * FROM audit ORDER BY seq LIMIT 1").fetchone()) == old
    )
    assert verify(bridge.store)["valid"]


def test_capture_task_completion_and_notice_rollback_together(bridge, config, monkeypatch):
    task = manual_running(bridge, config)
    before = [tuple(row) for row in bridge.store.db.execute("SELECT * FROM audit")]

    def failed_notice(*args, **kwargs):
        raise RuntimeError("simulated notice write failure")

    monkeypatch.setattr("kirabridge.completion_manager.record_notice", failed_notice)
    with pytest.raises(RuntimeError, match="notice write failure"):
        complete(bridge, task.task_id, {"stdout": "must rollback", "stderr": ""})
    assert bridge.store.get(task.task_id)["state"] == "running"
    assert bridge.outputs.status()["entries"] == 0
    assert bridge.store.db.execute("SELECT count(*) FROM completion_notices").fetchone()[0] == 0
    assert [tuple(row) for row in bridge.store.db.execute("SELECT * FROM audit")] == before


def test_evicted_completed_task_is_not_reexecuted_and_legacy_results_stay_available(bridge, config):
    task = manual_running(bridge, config)
    complete(bridge, task.task_id, {"stdout": "one execution", "stderr": ""})
    bridge.store.db.execute("DELETE FROM output_snapshots")
    replay = bridge.prepare("local", task)
    assert replay["state"] == "completed" and replay["result"]["stdout"] == ""
    assert not replay["result"]["output_available"]
    assert bridge.store.claim("must-not-run-again", 30) is None
    bridge.store.db.execute(
        "UPDATE tasks SET result=? WHERE id=?",
        (json.dumps({"stdout": "LEGACY_RESULT"}), task.task_id),
    )
    assert bridge.task("local", task.task_id)["result"] == {"stdout": "LEGACY_RESULT"}


def test_explicit_legacy_rollback_preserves_task_states_receipts_events_and_audit(bridge, config):
    task = manual_running(bridge, config)
    complete(bridge, task.task_id, {"stdout": "compatible output", "stderr": ""})
    before = bridge.task("local", task.task_id)
    events = [tuple(row) for row in bridge.store.db.execute("SELECT * FROM events")]
    with pytest.raises(BridgeError) as error:
        bridge.outputs.prepare_legacy_results()
    assert error.value.code == "rollback_maintenance_required"
    bridge.store.db.execute(
        "INSERT INTO activation_runs VALUES('rollback','draining',1,1,'{}',NULL)"
    )
    assert bridge.outputs.prepare_legacy_results()["tasks"] == 1
    after = bridge.task("local", task.task_id)
    for key in ("state", "receipt", "finished", "updated", "evidence"):
        assert after[key] == before[key]
    assert (
        after["result"]["stdout"] == "compatible output" and "output_codec" not in after["result"]
    )
    assert [tuple(row) for row in bridge.store.db.execute("SELECT * FROM events")] == events
    assert verify(bridge.store)["valid"]


def test_legacy_rollback_refuses_unbounded_duplicate_export_without_modifying_tasks(bridge, config):
    bridge.config.output_history.max_bytes = 4096
    bridge.config.output_history.max_item_bytes = 4096
    capture = observed(bridge, "x" * 3000)
    for index in range(2):
        task = manual_running(bridge, config, identifier=f"read-{index}", operation="session.read")
        complete(bridge, task.task_id, capture)
    assert bridge.outputs.status()["entries"] == 1
    before = [
        tuple(row) for row in bridge.store.db.execute("SELECT id,result FROM tasks ORDER BY id")
    ]
    bridge.store.db.execute(
        "INSERT INTO activation_runs VALUES('rollback','draining',1,1,'{}',NULL)"
    )
    with pytest.raises(BridgeError) as error:
        bridge.outputs.prepare_legacy_results()
    assert error.value.code == "rollback_capacity"
    assert [
        tuple(row) for row in bridge.store.db.execute("SELECT id,result FROM tasks ORDER BY id")
    ] == before


async def test_grok_expired_output_finishes_with_clear_answer_without_replay(bridge, config):
    from kirabridge.bridge_core.config import GrokConnectorConfig
    from kirabridge.grok_connector.conversation import result_for_conversation

    config.grok_connector = GrokConnectorConfig(enabled=True, public_origin="https://voice.example")
    config.principals["grok_app"] = config.principals["local"].model_copy(deep=True)
    task = manual_running(bridge, config, principal="grok_app")
    complete(bridge, task.task_id, {"stdout": "real old output", "stderr": ""})
    bridge.store.db.execute("DELETE FROM output_snapshots")
    result = await result_for_conversation(
        bridge, "grok_app", bridge.task("grok_app", task.task_id)
    )
    assert result["conversation_return"]["final"]
    assert not result["conversation_return"]["continue_required"]
    assert "nicht mehr verfügbar" in result["conversation_return"]["text"]
    assert bridge.store.claim("do-not-repeat", 30) is None
