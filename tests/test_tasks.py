import asyncio
import json
import sys

import pytest
from conftest import archive_task, request, submit
from test_mcp import http_bridge  # noqa: F401

from kirabridge.audit_manager import verify
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import BridgeError, State


async def test_persist_before_dispatch_and_evidence(bridge, config):
    value = request(arguments={"path": config.principals["local"].roots[0]})
    async with bridge:
        initial = submit(bridge, value)
        assert initial["state"] == "accepted"
        assert initial["receipt"] and initial["started"] is None
        final = await bridge.tasks.wait("local", value.task_id)
        assert final["state"] == "completed"
        assert final["created"] <= final["accepted"] <= final["started"] <= final["finished"]
        assert final["receipt"]
        states = [event["state"] for event in bridge.events("local", value.task_id)["events"]]
        assert states == ["created", "accepted", "running", "completed"]
        assert verify(bridge.store)["valid"]


async def test_idempotency_executes_once(bridge, config):
    target = config.principals["local"].roots[0] + "/once.txt"
    value = request(
        "terminal.execute",
        {
            "argv": [
                sys.executable,
                "-c",
                "from pathlib import Path; p=Path('once.txt'); "
                "p.write_text(p.read_text()+'x' if p.exists() else 'x')",
            ],
            "cwd": config.principals["local"].roots[0],
        },
    )
    async with bridge:
        initial = submit(bridge, value)
        assert bridge.submit("local", value, "already-consumed")["id"] == initial["id"]
        assert (await bridge.tasks.wait("local", value.task_id))["state"] == "completed"
        assert bridge.submit("local", value, "")["state"] == "completed"
        from pathlib import Path

        assert Path(target).read_text() == "x"


async def test_conflicting_idempotency_and_task_ids(bridge, config):
    await bridge.tasks.start()
    submit(bridge, request(arguments={"path": config.principals["local"].roots[0]}))
    with pytest.raises(BridgeError, match="Idempotency"):
        submit(bridge, request(arguments={"path": "/elsewhere"}))
    with pytest.raises(BridgeError, match="identifier"):
        submit(
            bridge,
            request(
                arguments={"path": config.principals["local"].roots[0]},
                task_id="task-1",
                key="different",
            ),
        )
    await bridge.tasks.stop()


async def test_restart_archives_legacy_queue_and_never_reexecutes_unknown(bridge, config):
    for i in range(3):
        bridge.prepare(
            "local",
            request(arguments={"path": config.principals["local"].roots[0]}, task_id=f"t-{i}"),
        )
        # Fixture for an actual pre-upgrade database; new admission cannot create this state.
        bridge.store.db.execute("UPDATE tasks SET state='queued' WHERE id=?", (f"t-{i}",))
    first = bridge.store.claim("dead-worker", 30)
    second = bridge.store.claim("dead-worker", 30)
    bridge.store.transition(second["id"], State.RUNNING, {"pid": 999}, owner="dead-worker")
    bridge.store.close()
    reopened = Bridge(config)
    try:
        await reopened.tasks.start()
        assert reopened.store.get(first["id"])["state"] == "unknown"
        assert reopened.store.get(second["id"])["state"] == "unknown"
        assert reopened.store.get(second["id"])["evidence"]["last_observation"]["pid"] == 999
        assert reopened.store.get("t-2")["state"] == "cancelled"
        assert reopened.store.get("t-2")["evidence"]["reason"] == "execution_queue_removed"
        assert reopened.store.claim("new-worker", 30) is None
    finally:
        await reopened.tasks.stop()
        reopened.store.close()


async def test_exclusive_dispatcher_lock(bridge, config):
    second = Bridge(config)
    try:
        await bridge.tasks.start()
        with pytest.raises(BridgeError, match="already owns"):
            await second.tasks.start()
    finally:
        await bridge.tasks.stop()
        second.store.close()


async def test_illegal_and_unproven_state_transitions(bridge, config):
    await bridge.tasks.start()
    submit(bridge, request(arguments={"path": config.principals["local"].roots[0]}))
    with pytest.raises(BridgeError, match="Invalid"):
        bridge.store.transition("task-1", State.QUEUED, {"pretend": True})
    with pytest.raises(BridgeError, match="evidence"):
        bridge.store.transition("task-1", State.RUNNING, {}, owner=bridge.tasks.owner)
    with pytest.raises(BridgeError, match="owns"):
        bridge.store.transition("task-1", State.RUNNING, {"pid": 5}, owner="wrong")
    await bridge.tasks.stop()


async def test_delegation_is_owned_and_traceable(bridge, config):
    await bridge.tasks.start()
    parent = request(arguments={"path": config.principals["local"].roots[0]})
    submit(bridge, parent)
    child = request(
        arguments={"path": config.principals["local"].roots[0]},
        task_id="child",
        parent=parent.task_id,
    )
    assert submit(bridge, child)["parent_id"] == parent.task_id
    with pytest.raises(BridgeError, match="not found"):
        submit(
            bridge,
            child.model_copy(update={"task_id": "foreign", "idempotency_key": "foreign"}),
            "other",
        )
    await bridge.tasks.stop()


async def test_direct_capacity_does_not_consume_approval_or_persist_queue(bridge, config):
    config.concurrency = 1
    await bridge.tasks.start()
    first = request(arguments={"path": config.principals["local"].roots[0]})
    submit(bridge, first)
    second = first.model_copy(update={"task_id": "second", "idempotency_key": "second"})
    token = bridge.security.grant("local", second)
    with pytest.raises(BridgeError, match="capacity"):
        bridge.submit("local", second, token)
    assert not bridge.store.db.execute("SELECT 1 FROM tasks WHERE id='second'").fetchone()
    await bridge.tasks.wait("local", first.task_id)
    assert bridge.submit("local", second, token)["state"] == "accepted"
    await bridge.tasks.wait("local", second.task_id)
    await bridge.tasks.stop()


async def test_shutdown_yields_unknown_not_completed(bridge, config):
    value = request(
        "terminal.execute",
        {
            "argv": [sys.executable, "-c", "import time; time.sleep(60)"],
            "cwd": config.principals["local"].roots[0],
        },
    )
    await bridge.tasks.start()
    submit(bridge, value)
    async with asyncio.timeout(5):
        while bridge.store.get(value.task_id)["state"] != "running":
            await asyncio.sleep(0.01)
    await bridge.tasks.stop()
    assert bridge.store.get(value.task_id)["state"] == "unknown"
    assert not bridge.terminal.sessions


def test_reconciliation_requires_unknown_and_evidence(bridge, config):
    bridge.prepare("local", request(arguments={"path": config.principals["local"].roots[0]}))
    with pytest.raises(BridgeError):
        bridge.tasks.reconcile("task-1", State.COMPLETED, "external-run:1")
    bridge.store.db.execute("UPDATE tasks SET state='accepted' WHERE id='task-1'")
    bridge.store.recover()
    with pytest.raises(BridgeError):
        bridge.tasks.reconcile("task-1", State.COMPLETED, "")
    result = bridge.tasks.reconcile("task-1", State.COMPLETED, "external-run:1")
    assert result["evidence"]["source"] == "local_operator_attestation"


async def test_audit_detects_tampering_and_does_not_log_payload(bridge, config):
    await bridge.tasks.start()
    secret = "sensitive-test-string"
    submit(
        bridge,
        request("file.write", {"path": config.principals["local"].roots[0] + "/x", "text": secret}),
    )
    records = [dict(row) for row in bridge.store.db.execute("SELECT * FROM audit")]
    assert secret not in json.dumps(records)
    assert verify(bridge.store)["valid"]
    bridge.store.db.execute("UPDATE audit SET kind='tampered' WHERE seq=1")
    assert not verify(bridge.store)["valid"]
    await bridge.tasks.stop()


async def test_local_console_approval_reaches_live_dispatcher_without_queue(http_bridge, config):  # noqa: F811
    from kirabridge.task_manager.local import approve

    running, _ = http_bridge
    value = request(arguments={"path": config.principals["local"].roots[0]})
    assert running.prepare("local", value)["state"] == "created"
    owner = Bridge(config)  # Separate local control process; never acquires dispatcher ownership.
    try:
        hashed = owner.store.db.execute(
            "SELECT request_hash FROM tasks WHERE id=?", (value.task_id,)
        ).fetchone()[0]
        with pytest.raises(BridgeError, match="reviewed"):
            await approve(owner.tasks, value.task_id, expected_hash="0" * 64)
        result = await approve(owner.tasks, value.task_id, expected_hash=hashed)
        assert result["state"] in {"accepted", "running", "completed"}
        final = await running.tasks.wait("local", value.task_id, 5)
        assert final["state"] == "completed"
        assert not running.store.db.execute("SELECT 1 FROM tasks WHERE state='queued'").fetchone()
    finally:
        owner.store.close()


async def test_shutdown_before_coroutine_entry_settles_admission_as_unknown(bridge, config):
    await bridge.tasks.start()
    value = request(arguments={"path": config.principals["local"].roots[0]})
    assert submit(bridge, value)["state"] == "accepted"
    await bridge.tasks.stop()
    assert bridge.store.get(value.task_id)["state"] == "unknown"


async def test_legacy_queued_label_with_execution_receipt_remains_unknown(bridge, config):
    value = request(arguments={"path": config.principals["local"].roots[0]})
    archive_task(bridge, value)
    bridge.store.db.execute(
        "UPDATE tasks SET receipt='old-receipt',started=1 WHERE id=?", (value.task_id,)
    )
    await bridge.tasks.start()
    try:
        result = bridge.store.get(value.task_id)
        assert result["state"] == "unknown" and result["receipt"] == "old-receipt"
        assert result["evidence"]["automatic_replay"] is False
        assert not bridge.tasks.admission.active
    finally:
        await bridge.tasks.stop()
