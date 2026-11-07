"""Owner scope, queue withdrawal, CAS and restart: never falsely stop uncertain work."""

import json

import pytest
from conftest import request, submit
from test_mcp import http_bridge  # noqa: F401 -- real isolated HTTP fixture

from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.message_manager import MessageSend
from kirabridge.queue_management.models import QueueControl


@pytest.fixture
def queues(bridge, config):
    policy = config.principals["local"]
    policy.capabilities += ["message.send", "message.read", "message.ack"]
    policy.message_peers = ["other"]
    policy.approval_mode = "automatic"
    policy.permission_level = "full"
    config.principals["other"].message_peers = ["local"]
    config.principals["other"].capabilities += ["message.read", "message.ack"]
    return bridge.queues


def message(bridge, identifier="one"):
    result = bridge.messages.send(
        "local",
        MessageSend(
            recipient="other",
            conversation_id="conversation",
            message_id=identifier,
            idempotency_key=identifier,
            body="Original Unicode ä🧠 content",
            kind="work",
            dispatch=False,
        ),
    )

    bridge.store.db.execute(
        "INSERT INTO message_jobs(message_id,state) VALUES(?, 'queued')", (identifier,)
    )
    return result


def command(queues, queue, identifier=None, action="cancel"):
    value = (
        queues.get("local", queue, identifier) if identifier else queues.snapshot("local", queue)
    )
    return QueueControl(
        queue_id=queue,
        item_id=identifier,
        action=action,
        revision=value["revision"],
        reason="explicit isolated test",
    )


async def test_cancel_restore_without_delivery_or_duplicate(queues, bridge):
    message(bridge)
    value = queues.get("local", "messages/other", "one")
    assert value["detail"]["delivered"] is None
    assert value["detail"]["body"] == "Original Unicode ä🧠 content"
    result = await queues.control("local", command(queues, "messages/other", "one"))
    assert result["fully_removed"] and not result["execution_stop_claimed"]
    assert bridge.message_receiver._claim("one") is None
    assert bridge.messages.receive("other")["messages"] == []
    assert queues.entries("local", "messages/other")["entries"] == []
    assert queues.get("local", "messages/other", "one")["state"] == "queued"
    restored = await queues.control("local", command(queues, "messages/other", "one", "restore"))
    assert restored["results"][0]["delivery_active"]
    assert len(bridge.messages.receive("other")["messages"]) == 1
    assert bridge.store.db.execute("select count(*) from messages").fetchone()[0] == 1
    with pytest.raises(BridgeError):
        await queues.control("local", command(queues, "messages/other", "one", "restore"))


async def test_exact_clear_race_does_not_remove_new_or_foreign(queues, bridge):
    message(bridge)
    clear = command(queues, "messages/other", action="clear")
    message(bridge, "two")
    with pytest.raises(BridgeError, match="changed"):
        await queues.control("local", clear)
    assert len(queues.entries("local", "messages/other")["entries"]) == 2
    result = await queues.control("local", command(queues, "messages/other", action="clear"))
    assert result["fully_removed"]
    with pytest.raises(BridgeError):
        queues.get("local", "messages/wrong", "one")
    bridge.config.principals["outsider"] = bridge.config.principals["local"].model_copy(deep=True)
    assert queues.entries("outsider", "messages")["entries"] == []
    with pytest.raises(BridgeError):
        queues.get("outsider", "messages", "one")


async def test_task_lanes_cancel_and_running_unknown_preserved(queues, bridge, config):
    task = request("file.list", {"path": config.principals["local"].roots[0]})
    submit(bridge, task)
    assert queues.entries("local", "tasks/read")["entries"] == []
    # file.list is normal lane; ownership and exact state still apply.
    entry = queues.get("local", "tasks/normal", task.task_id)
    assert entry["detail"]["args"]["path"] == config.principals["local"].roots[0]
    await queues.control("local", command(queues, "tasks", task.task_id))
    assert bridge.store.get(task.task_id)["state"] == "cancelled"
    with pytest.raises(BridgeError):
        await queues.control("local", command(queues, "tasks", task.task_id, "restore"))
    second = request("file.list", {"path": config.principals["local"].roots[0]}, task_id="running")
    submit(bridge, second)
    bridge.store.claim("worker", 20)
    result = await queues.control("local", command(queues, "tasks", "running"))
    assert not result["fully_removed"] and not result["execution_stop_claimed"]
    assert bridge.store.get("running")["state"] == "accepted"


async def test_unknown_handoff_retirement_requires_idle_and_keeps_unknown(queues, bridge, config):
    from kirabridge.bridge_core.config import VisibleTerminalBinding

    message(bridge)
    binding = VisibleTerminalBinding(
        pane_id="terminal:1:ttys001", expected_pid=123, agent_pid=124, ready_pattern="ready"
    )
    config.visible_handoffs.bindings["other"] = binding
    bridge.store.db.execute(
        "INSERT INTO visible_handoffs VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            "uncertain",
            "local",
            "other",
            "hash",
            canonical(binding.model_dump()),
            "one",
            "unknown",
            1,
            1,
            canonical({"terminal_input_attempted": True}),
        ),
    )

    async def busy(*args, **kwargs):
        raise BridgeError("visible_target_busy", "Busy real target must remain untouched")

    bridge.visible_handoffs.check_target = busy
    with pytest.raises(BridgeError):
        await queues.control("local", command(queues, "handoffs", "uncertain", "retire"))
    assert queues.get("local", "handoffs", "uncertain")["delivery_active"]

    async def idle(*args, **kwargs):
        assert kwargs["ready"] is True
        return {"fresh_idle": True}

    bridge.visible_handoffs.check_target = idle
    result = await queues.control("local", command(queues, "handoffs", "uncertain", "retire"))
    assert result["fully_removed"] and not result["execution_stop_claimed"]
    assert queues.get("local", "handoffs", "uncertain")["state"] == "unknown"
    bridge.visible_handoffs.transition("uncertain", "confirmed", {"late_receipt": True})
    assert queues.get("local", "handoffs", "uncertain")["state"] == "unknown"
    await bridge.visible_handoffs.reconcile_target_reservations("local", "other", binding)
    assert bridge.messages.get("local", "one")["body"].startswith("Original")


async def test_manual_grants_require_exact_approval_and_control_lane(queues, bridge, config):
    message(bridge)
    config.principals["local"].approval_mode = "manual"
    config.principals["local"].permission_level = "ask"
    args = command(queues, "messages", "one")
    with pytest.raises(BridgeError, match="approved"):
        await queues.control("local", args)
    task = request("queue.control", args.model_dump())
    pending = bridge.prepare("local", task)
    assert pending["state"] == "created"
    # The old queued message is not delivered by this isolated test.
    approved = bridge.security.grant("local", task)
    submitted = bridge.submit("local", task, approved)
    assert submitted["state"] == "queued"
    with pytest.raises(BridgeError) as repeated:
        bridge.tasks.approve(task.task_id)
    assert repeated.value.code == "state_conflict"
    assert bridge.store.claim("control-worker", 20, "stop")["id"] == task.task_id


def test_catalog_skips_completed_task_results(queues, bridge):
    calls = {"n": 0}
    original = bridge.store.get

    def counting(task_id, principal=None):
        calls["n"] += 1
        return original(task_id, principal)

    bridge.store.get = counting
    for index in range(40):
        bridge.store.db.execute(
            "INSERT INTO tasks (id,principal,idem,request_hash,operation,args,state,"
            "created,updated,result) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                f"old-{index}",
                "local",
                f"idem-{index}",
                "hash",
                "file.list",
                "{}",
                "completed",
                1,
                1,
                "x" * 2000,
            ),
        )
    result = queues.catalog("local")
    assert any(queue["queue_id"] == "tasks/read" for queue in result["queues"])
    assert calls["n"] < 40


def test_queue_catalog_read_has_no_delivery_side_effects(queues, bridge):
    message(bridge)
    result = queues.catalog("local")
    assert any(q["queue_id"] == "messages/other" for q in result["queues"])
    assert bridge.messages.get("local", "one")["delivered"] is None
    assert bridge.messages.events("local", "one")["events"][0]["kind"] == "message.queued"
    assert (
        json.loads(bridge.store.db.execute("SELECT evidence FROM message_jobs").fetchone()[0]) == {}
    )


async def test_clear_task_queue_through_exact_control_task_excludes_itself(queues, bridge, config):
    submit(
        bridge,
        request("file.list", {"path": config.principals["local"].roots[0]}, task_id="pending"),
    )
    args = command(queues, "tasks", action="clear")
    value = request("queue.control", args.model_dump(), task_id="clear-control")
    bridge.prepare("local", value)
    claimed = bridge.store.claim(bridge.tasks.owner, 30, "stop")
    await bridge.tasks._execute(claimed)
    assert bridge.store.get("clear-control")["state"] == "completed"
    assert bridge.store.get("pending")["state"] == "cancelled"


async def test_withdrawal_frees_capacity_without_deleting_history(queues, bridge, config):
    config.messaging.max_pending_per_recipient = 1
    message(bridge)
    with pytest.raises(BridgeError):
        message(bridge, "two")
    await queues.control("local", command(queues, "messages", "one"))
    message(bridge, "two")
    assert bridge.store.db.execute("select count(*) from messages").fetchone()[0] == 2
    assert bridge.messages.activation_work_count() == 1
    assert [r["id"] for r in queues.entries("local", "messages")["entries"]] == ["two"]
    assert queues.entries("local", "messages")["entries"][0]["position"] == 1


async def test_withdrawal_survives_store_restart(queues, bridge, config):
    from kirabridge.bridge_core.bridge import Bridge

    message(bridge)
    await queues.control("local", command(queues, "messages", "one"))
    count = bridge.store.db.execute("SELECT count(*) FROM audit").fetchone()[0]
    bridge.store.close()
    reopened = Bridge(config)
    try:
        assert reopened.queues.get("local", "messages", "one")["hold"]
        assert reopened.messages.receive("other")["messages"] == []
        assert reopened.message_receiver._claim("one") is None
        assert reopened.store.db.execute("SELECT count(*) FROM audit").fetchone()[0] >= count
    finally:
        reopened.store.close()


async def test_actual_http_mcp_queue_cancel_restore_clear_and_owned_stop(
    http_bridge,  # noqa: F811 -- imported live fixture
    config,
):
    import asyncio
    import sys

    from kirabridge.mcp_gateway.client import MCPClientPool, Peer

    bridge, endpoint = http_bridge
    config.principals["local"].capabilities += ["message.send", "message.read", "message.ack"]
    config.principals["other"].capabilities += ["message.read"]
    config.principals["local"].message_peers = ["other"]
    config.principals["other"].message_peers = ["local"]
    config.principals["local"].permission_level = "full"
    config.principals["local"].approval_mode = "automatic"
    message(bridge)
    async with MCPClientPool() as pool:
        await pool.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        names = {tool.name for tool in await pool.list_tools("local")}
        assert {
            "queue_catalog",
            "queue_entries",
            "queue_entry",
            "queue_control",
            "queue_stop",
        } <= names
        for index, action in enumerate(["cancel", "restore", "clear"]):
            tool = "queue_catalog" if action == "clear" else "queue_entry"
            arguments = (
                {} if action == "clear" else {"queue_id": "messages/other", "item_id": "one"}
            )
            raw = await pool.call("local", tool, arguments)
            assert raw.structuredContent is not None, raw
            view = raw.structuredContent
            observed = (
                next(q for q in view["queues"] if q["queue_id"] == "messages/other")
                if action == "clear"
                else view
            )
            result = await pool.call(
                "local",
                "queue_control",
                {
                    "request": {
                        "queue_id": "messages/other",
                        "item_id": None if action == "clear" else "one",
                        "action": action,
                        "revision": observed["revision"],
                        "reason": "isolated MCP acceptance",
                    },
                    "task_id": f"queue-{index}",
                    "idempotency_key": f"queue-{index}",
                },
            )
            assert not result.isError
            done = await bridge.tasks.wait("local", f"queue-{index}", 10)
            assert done["state"] == "completed", done
        assert bridge.messages.get("local", "one")["delivered"] is None
        # This is an isolated owned subprocess, never a user's terminal or coding agent.
        task = request(
            "terminal.execute",
            {
                "argv": [sys.executable, "-c", "import time; time.sleep(30)"],
                "cwd": config.principals["local"].roots[0],
            },
            task_id="owned-sleeper",
        )
        await pool.call("local", "task_request", {"request": task.model_dump()})
        async with asyncio.timeout(10):
            while "owned-sleeper" not in bridge.terminal.sessions:
                await asyncio.sleep(0.01)
        stopped = await pool.call(
            "local",
            "queue_stop",
            {
                "task_id": "owned-sleeper",
                "stop_task_id": "owned-stop",
                "idempotency_key": "owned-stop",
            },
        )
        assert not stopped.isError
        proof = await bridge.tasks.wait("local", "owned-stop", 10)
        assert proof["state"] == "completed", proof
        assert proof["result"]["exit_code"] is not None
        session = bridge.terminal.sessions.get("owned-sleeper")
        assert session is None or session.process.returncode is not None


async def test_recipient_cannot_reverse_sender_withdrawal(queues, bridge, config):
    message(bridge)
    await queues.control("local", command(queues, "messages", "one"))
    config.principals["other"].permission_level = "full"
    record = queues.get("other", "messages", "one")
    args = QueueControl(
        queue_id="messages",
        item_id="one",
        action="restore",
        revision=record["revision"],
        reason="must not override sender",
    )
    with pytest.raises(BridgeError, match="withdrawing"):
        await queues.control("other", args)
    assert bridge.messages.receive("other")["messages"] == []


def test_lossless_unicode_content_paging_and_no_silent_truncation(queues, bridge):
    import hashlib

    message(bridge)
    parts, offset, version = [], 0, None
    while True:
        page = queues.read_entry("local", "messages", "one", offset, 19, version)
        parts.append(page["detail_json_chunk"])
        version, offset = page["revision"], page["next_content_offset"]
        if not page["has_more_content"]:
            break
    raw = "".join(parts)
    assert hashlib.sha256(raw.encode()).hexdigest() == page["content_sha256"]
    assert json.loads(raw)["body"] == "Original Unicode ä🧠 content"
    assert bridge.messages.get("local", "one")["delivered"] is None
    assert "detail" not in queues.entries("local", "messages")["entries"][0]


def test_unknown_historical_operation_remains_inspectable(queues, bridge, config):
    submit(bridge, request("file.list", {"path": config.principals["local"].roots[0]}))
    bridge.store.db.execute("UPDATE tasks SET operation='legacy.custom' WHERE id='task-1'")
    assert queues.entries("local", "tasks/unknown")["entries"][0]["id"] == "task-1"
    assert any(q["queue_id"] == "tasks/unknown" for q in queues.catalog("local")["queues"])


async def test_message_job_transition_invalidates_clear_and_content_revision(queues, bridge):
    message(bridge)
    control = command(queues, "messages", "one")
    initial = queues.read_entry("local", "messages", "one", 0, 19)
    bridge.store.db.execute("UPDATE message_jobs SET state='unknown',error='lost-receipt'")
    with pytest.raises(BridgeError, match="changed"):
        await queues.control("local", control)
    with pytest.raises(BridgeError, match="changed"):
        queues.read_entry("local", "messages", "one", 19, 19, initial["revision"])
    assert queues.get("local", "messages", "one")["state"] == "unknown"
