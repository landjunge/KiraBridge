# Imported fixtures are resolved by pytest dependency injection.
# ruff: noqa: F811
"""View-only unknown withdrawal: execution reservations and history stay authoritative."""

import pytest
from conftest import request, submit
from test_mcp import http_bridge  # noqa: F401
from test_queue_management import message, queues  # noqa: F401

from kirabridge.bridge_core.config import VisibleTerminalBinding
from kirabridge.bridge_core.models import BridgeError, State, canonical
from kirabridge.queue_management.models import QueueControl


def unknown(bridge, family):
    if family == "tasks":
        value = request("file.list", {"path": "/synthetic"}, task_id="unknown-task")
        submit(bridge, value)
        bridge.store.claim("isolated-worker", 20)
        bridge.store.transition(value.task_id, State.UNKNOWN, {"execution_unconfirmed": True})
        return value.task_id
    message(bridge)
    if family == "messages":
        bridge.store.db.execute(
            "UPDATE message_jobs SET state='unknown',evidence=? WHERE message_id='one'",
            (canonical({"execution_unconfirmed": True}),),
        )
        return "one"
    binding = VisibleTerminalBinding(
        pane_id="terminal:1:ttys001", expected_pid=123, agent_pid=124, ready_pattern="ready"
    )
    bridge.config.visible_handoffs.bindings["other"] = binding
    bridge.store.db.execute(
        "INSERT INTO visible_handoffs VALUES(?,?,?,?,?,?,'unknown',1,1,?)",
        (
            "unknown-handoff",
            "local",
            "other",
            "hash",
            canonical(binding.model_dump()),
            "one",
            canonical({"terminal_input_attempted": True}),
        ),
    )
    return "unknown-handoff"


def withdraw(queues, family, identifier, *, acknowledged=True):
    entry = queues.get("local", family, identifier)
    return QueueControl(
        queue_id=family,
        action="withdraw",
        item_id=identifier,
        revision=entry["revision"],
        reason="Explicit synthetic withdrawal; execution remains unknown",
        acknowledge_execution_unknown=acknowledged,
    )


def history(bridge):
    return {
        table: [
            tuple(row) for row in bridge.store.db.execute(f"SELECT * FROM {table} ORDER BY rowid")
        ]
        for table in (
            "tasks",
            "events",
            "messages",
            "message_events",
            "message_jobs",
            "visible_handoffs",
            "visible_handoff_events",
            "completion_notices",
        )
    }


@pytest.mark.parametrize("family", ["tasks", "messages", "handoffs"])
async def test_unknown_withdrawal_hides_only_delivery_and_preserves_original_history(
    queues,
    bridge,
    family,  # noqa: F811
):
    identifier = unknown(bridge, family)
    original = history(bridge)
    request = withdraw(queues, family, identifier)
    result = await queues.control("local", request)
    assert result["fully_removed"] and not result["execution_stop_claimed"]
    entry = queues.get("local", family, identifier)
    assert entry["state"] == entry["execution_state"] == "unknown"
    assert not entry["delivery_active"] and entry["hold"] is None
    assert entry["withdrawal"]["actor"] == "local"
    assert queues.entries("local", family)["entries"] == []
    assert queues.entries("local", family, active_only=False)["entries"][0]["id"] == identifier
    assert history(bridge) == original
    assert not bridge.store.db.execute("SELECT 1 FROM queue_holds").fetchone()
    assert bridge.store.db.execute("SELECT count(*) FROM queue_withdrawals").fetchone()[0] == 1
    assert (
        bridge.store.db.execute(
            "SELECT count(*) FROM audit WHERE kind='queue.withdraw'"
        ).fetchone()[0]
        == 1
    )


@pytest.mark.parametrize("acknowledged", [False, None])
async def test_withdraw_requires_explicit_unknown_acknowledgement(queues, bridge, acknowledged):  # noqa: F811
    identifier = unknown(bridge, "tasks")
    value = withdraw(queues, "tasks", identifier)
    value = value.model_copy(update={"acknowledge_execution_unknown": acknowledged})
    with pytest.raises(BridgeError) as error:
        await queues.control("local", value)
    assert error.value.code == "execution_unknown_ack_required"
    assert not bridge.store.db.execute("SELECT 1 FROM queue_withdrawals").fetchone()


@pytest.mark.parametrize("state", ["queued", "accepted", "running", "completed"])
async def test_withdraw_refuses_non_unknown_work_without_stopping_or_cancelling(
    queues, bridge, state
):  # noqa: F811
    identifier = unknown(bridge, "tasks")
    bridge.store.db.execute("UPDATE tasks SET state=? WHERE id=?", (state, identifier))
    before = history(bridge)
    with pytest.raises(BridgeError) as error:
        await queues.control("local", withdraw(queues, "tasks", identifier))
    assert error.value.code == "state_conflict"
    assert history(bridge) == before
    assert not bridge.store.db.execute("SELECT 1 FROM queue_withdrawals").fetchone()


async def test_withdraw_keeps_handoff_execution_reservation_and_other_pending_messages(
    queues, bridge
):  # noqa: F811
    identifier = unknown(bridge, "handoffs")
    message(bridge, "other-pending")
    original = history(bridge)
    result = await queues.control("local", withdraw(queues, "handoffs", identifier))
    assert result["execution_reservation_released"] is False
    assert result["results"][0]["execution_reservation_released"] is False
    assert not result["results"][0]["execution_stop_claimed"]
    binding = bridge.config.visible_handoffs.bindings["other"]
    with pytest.raises(BridgeError) as error:
        await bridge.visible_handoffs.reconcile_target_reservations("local", "other", binding)
    assert error.value.code == "visible_target_busy"
    assert history(bridge) == original
    assert {row["id"] for row in queues.entries("local", "messages")["entries"]} == {
        "one",
        "other-pending",
    }
    assert not bridge.store.db.execute("SELECT 1 FROM queue_holds").fetchone()


async def test_withdraw_revision_permissions_and_idempotence_are_preserved(queues, bridge, config):  # noqa: F811
    identifier = unknown(bridge, "tasks")
    value = withdraw(queues, "tasks", identifier)
    config.principals["outsider"] = config.principals["local"].model_copy(deep=True)
    with pytest.raises(BridgeError):
        await queues.control("outsider", value)
    config.principals["local"].capabilities.remove("task.cancel")
    with pytest.raises(BridgeError) as denied:
        await queues.control("local", value)
    assert denied.value.code == "forbidden"
    config.principals["local"].capabilities.append("task.cancel")
    await queues.control("local", value)
    first = tuple(bridge.store.db.execute("SELECT * FROM queue_withdrawals").fetchone())
    with pytest.raises(BridgeError) as stale:
        await queues.control("local", value)
    assert stale.value.code == "queue_changed"
    await queues.control("local", withdraw(queues, "tasks", identifier))
    assert tuple(bridge.store.db.execute("SELECT * FROM queue_withdrawals").fetchone()) == first
    assert (
        bridge.store.db.execute(
            "SELECT count(*) FROM audit WHERE kind='queue.withdraw'"
        ).fetchone()[0]
        == 1
    )


async def test_withdraw_ack_does_not_replace_required_local_approval(queues, bridge, config):  # noqa: F811
    identifier = unknown(bridge, "tasks")
    value = withdraw(queues, "tasks", identifier)
    config.principals["local"].permission_level = "ask"
    config.principals["local"].approval_mode = "manual"
    with pytest.raises(BridgeError) as error:
        await queues.control("local", value)
    assert error.value.code == "approval_required"
    assert not bridge.store.db.execute("SELECT 1 FROM queue_withdrawals").fetchone()


async def test_withdraw_rejects_other_queue_family_even_when_unknown(queues, bridge):  # noqa: F811
    identifier = unknown(bridge, "tasks")
    bridge.store.db.execute(
        "INSERT INTO session_input_buffers(task_id,state,created,expires) VALUES(?,'unknown',1,2)",
        (identifier,),
    )
    with pytest.raises(BridgeError) as error:
        await queues.control("local", withdraw(queues, "session-input", identifier))
    assert error.value.code == "state_conflict"
    assert not bridge.store.db.execute("SELECT 1 FROM queue_withdrawals").fetchone()


async def test_withdrawal_schema_is_additive_and_old_claim_logic_cannot_replay_unknown(
    queues, bridge
):  # noqa: F811
    from kirabridge.queue_management.schema import install_schema
    from kirabridge.task_manager.store import Store

    identifier = unknown(bridge, "tasks")
    schema_version = bridge.store.db.execute("PRAGMA user_version").fetchone()[0]
    await queues.control("local", withdraw(queues, "tasks", identifier))
    original = history(bridge)
    # Simulate the old execution selector: the new view-only table is irrelevant.
    assert bridge.store.db.execute("SELECT id FROM tasks WHERE state='queued'").fetchall() == []
    assert bridge.store.claim("old-runtime", 20) is None
    reopened = Store(bridge.config.state_path / "bridge.sqlite3")
    try:
        with reopened.transaction():
            install_schema(reopened)  # Repeated owner startup is idempotent.
        assert reopened.db.execute("PRAGMA user_version").fetchone()[0] == schema_version
        assert reopened.db.execute("SELECT count(*) FROM queue_withdrawals").fetchone()[0] == 1
        assert reopened.get(identifier)["state"] == "unknown"
        assert reopened.claim("old-runtime", 20) is None
        assert not reopened.db.execute("SELECT 1 FROM queue_holds").fetchone()
    finally:
        reopened.close()
    assert history(bridge) == original


async def test_withdraw_is_discovered_and_executed_once_through_existing_mcp_tasks(
    http_bridge,
    queues,  # noqa: F811
):
    from kirabridge.mcp_gateway.client import MCPClientPool, Peer

    bridge, endpoint = http_bridge
    identifier = unknown(bridge, "tasks")
    original = dict(
        bridge.store.db.execute("SELECT * FROM tasks WHERE id=?", (identifier,)).fetchone()
    )
    value = withdraw(queues, "tasks", identifier)
    async with MCPClientPool() as client:
        await client.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        tools = await client.list_tools("local")
        schema = next(tool.inputSchema for tool in tools if tool.name == "queue_control")
        control = schema["$defs"]["QueueControl"]["properties"]
        assert "withdraw" in control["action"]["enum"]
        assert control["acknowledge_execution_unknown"]["type"] == "boolean"
        args = {
            "request": value.model_dump(),
            "task_id": "withdraw-control",
            "idempotency_key": "withdraw-control",
        }
        assert not (await client.call("local", "queue_control", args)).isError
        result = await bridge.tasks.wait("local", "withdraw-control", 10)
        assert result["state"] == "completed", result
        assert result["result"]["fully_removed"]
        assert not result["result"]["execution_stop_claimed"]
        assert not result["result"]["execution_reservation_released"]
        assert not (await client.call("local", "queue_control", args)).isError
    assert (
        dict(bridge.store.db.execute("SELECT * FROM tasks WHERE id=?", (identifier,)).fetchone())
        == original
    )
    assert (
        bridge.store.db.execute(
            "SELECT count(*) FROM audit WHERE kind='queue.withdraw'"
        ).fetchone()[0]
        == 1
    )


async def test_withdraw_appends_a_valid_hash_audit_without_plaintext_reason(queues, bridge):
    import json

    from kirabridge.audit_manager import verify
    from kirabridge.bridge_core.models import digest

    identifier = unknown(bridge, "tasks")
    value = withdraw(queues, "tasks", identifier)
    await queues.control("local", value)
    audit = bridge.store.db.execute(
        "SELECT metadata FROM audit WHERE kind='queue.withdraw'"
    ).fetchone()
    metadata = json.loads(audit[0])
    assert metadata["reason_sha256"] == digest(value.reason)
    assert value.reason not in audit[0]
    assert metadata["execution_state_unchanged"] is True
    assert metadata["execution_reservation_released"] is False
    assert verify(bridge.store)["valid"]
