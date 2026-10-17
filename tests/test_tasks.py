import asyncio
import json
import sys

import pytest
from conftest import request, submit

from kirabridge.audit_manager import verify
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import BridgeError, State


async def test_persist_before_dispatch_and_evidence(bridge, config):
    value = request(arguments={"path": config.principals["local"].roots[0]})
    initial = submit(bridge, value)
    assert initial["state"] == "queued"
    assert initial["receipt"] is None and initial["started"] is None
    async with bridge:
        final = await bridge.tasks.wait("local", value.task_id)
        assert final["state"] == "completed"
        assert final["created"] <= final["accepted"] <= final["started"] <= final["finished"]
        assert final["receipt"]
        states = [event["state"] for event in bridge.events("local", value.task_id)["events"]]
        assert states == ["created", "queued", "accepted", "running", "completed"]
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
    initial = submit(bridge, value)
    assert bridge.submit("local", value, "already-consumed")["id"] == initial["id"]
    async with bridge:
        assert (await bridge.tasks.wait("local", value.task_id))["state"] == "completed"
        assert bridge.submit("local", value, "")["state"] == "completed"
        from pathlib import Path

        assert Path(target).read_text() == "x"


def test_conflicting_idempotency_and_task_ids(bridge, config):
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


def test_restart_preserves_queue_and_never_reexecutes_unknown(bridge, config):
    for i in range(3):
        submit(
            bridge,
            request(arguments={"path": config.principals["local"].roots[0]}, task_id=f"t-{i}"),
        )
    first = bridge.store.claim("dead-worker", 30)
    second = bridge.store.claim("dead-worker", 30)
    bridge.store.transition(second["id"], State.RUNNING, {"pid": 999}, owner="dead-worker")
    bridge.store.close()
    reopened = Bridge(config)
    try:
        assert reopened.store.recover() == 2
        assert reopened.store.get(first["id"])["state"] == "unknown"
        assert reopened.store.get(second["id"])["state"] == "unknown"
        assert reopened.store.get(second["id"])["evidence"]["last_observation"]["pid"] == 999
        next_task = reopened.store.claim("new-worker", 30)
        assert next_task["id"] == "t-2"
        assert reopened.store.claim("new-worker", 30) is None
    finally:
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


def test_illegal_and_unproven_state_transitions(bridge, config):
    submit(bridge, request(arguments={"path": config.principals["local"].roots[0]}))
    with pytest.raises(BridgeError, match="Invalid"):
        bridge.store.transition("task-1", State.COMPLETED, {"pretend": True})
    bridge.store.claim("worker", 30)
    with pytest.raises(BridgeError, match="evidence"):
        bridge.store.transition("task-1", State.RUNNING, {}, owner="worker")
    with pytest.raises(BridgeError, match="owns"):
        bridge.store.transition("task-1", State.RUNNING, {"pid": 5}, owner="wrong")


def test_delegation_is_owned_and_traceable(bridge, config):
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


def test_queue_capacity_does_not_consume_approval(bridge, config):
    config.max_queued = 1
    first = request(arguments={"path": config.principals["local"].roots[0]})
    submit(bridge, first)
    second = first.model_copy(update={"task_id": "second", "idempotency_key": "second"})
    token = bridge.security.grant("local", second)
    with pytest.raises(BridgeError, match="capacity"):
        bridge.submit("local", second, token)
    bridge.tasks.cancel_queued("local", first.task_id)
    assert bridge.submit("local", second, token)["state"] == "queued"


async def test_shutdown_yields_unknown_not_completed(bridge, config):
    value = request(
        "terminal.execute",
        {
            "argv": [sys.executable, "-c", "import time; time.sleep(60)"],
            "cwd": config.principals["local"].roots[0],
        },
    )
    submit(bridge, value)
    await bridge.tasks.start()
    async with asyncio.timeout(5):
        while bridge.store.get(value.task_id)["state"] != "running":
            await asyncio.sleep(0.01)
    await bridge.tasks.stop()
    assert bridge.store.get(value.task_id)["state"] == "unknown"
    assert not bridge.terminal.sessions


def test_reconciliation_requires_unknown_and_evidence(bridge, config):
    submit(bridge, request(arguments={"path": config.principals["local"].roots[0]}))
    with pytest.raises(BridgeError):
        bridge.tasks.reconcile("task-1", State.COMPLETED, "external-run:1")
    bridge.store.claim("worker", 1)
    bridge.store.recover()
    with pytest.raises(BridgeError):
        bridge.tasks.reconcile("task-1", State.COMPLETED, "")
    result = bridge.tasks.reconcile("task-1", State.COMPLETED, "external-run:1")
    assert result["evidence"]["source"] == "local_operator_attestation"


def test_audit_detects_tampering_and_does_not_log_payload(bridge, config):
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
