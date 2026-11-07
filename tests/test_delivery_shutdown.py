"""Actual handoff/driver paths with entirely fake terminal IO and private stores."""
# Imported fixtures are used by pytest.
# ruff: noqa: F811

import asyncio

import pytest
from test_direct_delivery import delivery  # noqa: F401
from test_visible_handoff import visible  # noqa: F401

from kirabridge.bridge_core.models import AgentInput, TaskRequest
from kirabridge.message_manager import MessageSend


async def test_start_cannot_replace_worker_after_direct_cleanup_before_stop_returns(
    delivery, monkeypatch
):
    bridge, _, direct, _, _ = delivery
    receiver = bridge.message_receiver
    completed, release = asyncio.Event(), asyncio.Event()
    stop_direct = direct.stop

    async def delayed_stop():
        await stop_direct()
        completed.set()
        await release.wait()

    monkeypatch.setattr(direct, "stop", delayed_stop)
    await receiver.start()
    worker = receiver.worker
    stopping = asyncio.create_task(receiver.stop())
    try:
        await asyncio.wait_for(completed.wait(), 1)
        await asyncio.sleep(0)
        assert worker.done() and direct._stop_task.done()
        await receiver.start()
        assert receiver.worker is worker and direct.accepting is False
        release.set()
        await asyncio.wait_for(stopping, 1)
        assert receiver.worker is None
        await receiver.start()
        assert receiver.worker is not worker and direct.accepting is True
    finally:
        release.set()
        await stopping
        await receiver.stop()


@pytest.mark.parametrize("ack_before_shutdown", [False, True])
async def test_actual_sent_handoff_survives_waiter_shutdown_and_late_reply(
    delivery, ack_before_shutdown
):
    bridge, transport, _, _, _ = delivery
    receiver = bridge.message_receiver
    transport["ack"] = ack_before_shutdown
    transport["reply"] = False
    await receiver.start()
    try:
        sent = await receiver.send(
            "chatgpt",
            MessageSend(
                recipient="grok",
                conversation_id="shutdown-real-handoff",
                idempotency_key="shutdown-real-handoff",
                body="A synthetic isolated request",
                kind="work",
                dispatch=True,
            ),
        )
        current = bridge.messages.get("chatgpt", sent["id"])
        assert current["processing"]["state"] == "running"
        run_id = current["processing"]["run_id"]
        assert bridge.visible_handoffs.status("chatgpt", run_id)["state"] in {"sent", "confirmed"}
        assert transport["calls"] == ["insert", "return"]
        await receiver.stop()
        assert bridge.messages.get("chatgpt", sent["id"])["processing"]["state"] == "running"
        assert bridge.visible_handoffs.status("chatgpt", run_id)["state"] in {"sent", "confirmed"}
        await receiver.start()
        if not ack_before_shutdown:
            bridge.messages.ack("grok", sent["id"], current["receipt"])
        reply = bridge.messages.send(
            "grok",
            MessageSend(
                recipient="chatgpt",
                conversation_id=sent["conversation_id"],
                idempotency_key="shutdown-late-result",
                reply_to=sent["id"],
                body="Late authenticated result",
                kind="result",
                request_reply=False,
                dispatch=False,
            ),
        )
        async with asyncio.timeout(3):
            while bridge.messages.get("chatgpt", sent["id"])["processing"]["state"] != "completed":
                await asyncio.sleep(0.01)
        job = bridge.messages.get("chatgpt", sent["id"])["processing"]
        assert job["reply_id"] == reply["id"]
        assert job["evidence"]["reconciled_without_input"] is True
        assert bridge.visible_handoffs.status("chatgpt", run_id)["state"] == "completed"
        assert bridge.store.db.execute("SELECT count(*) FROM completion_notices").fetchone()[0] == 1
        assert transport["calls"] == ["insert", "return"]
    finally:
        await receiver.stop()


@pytest.mark.parametrize("first", ["message", "task"])
async def test_message_and_native_task_share_existing_handoff_input_guard(delivery, first):
    bridge, transport, _, _, _ = delivery
    transport["reply"] = False
    receiver = bridge.message_receiver

    async def execute(task, running, progress):
        return await bridge.visible_handoffs.execute(
            task, AgentInput.model_validate(task["args"]), running, progress
        )

    bridge.tasks.executor = execute
    bridge.tasks.preflight = None
    await bridge.tasks.start()
    await receiver.start()
    message = MessageSend(
        recipient="grok",
        conversation_id="mixed-message-task",
        idempotency_key="mixed-message-task",
        body="One fake terminal turn",
        kind="work",
        dispatch=True,
    )
    request = TaskRequest(
        task_id="mixed-native",
        idempotency_key="mixed-native",
        operation="agent.execute",
        arguments={
            "agent": "grok",
            "prompt": "Another fake terminal turn",
            "cwd": "/tmp",
            "timeout": 3,
        },
    )
    try:
        if first == "message":
            await receiver.send("chatgpt", message)
            token = bridge.security.grant("chatgpt", request)
            bridge.submit("chatgpt", request, token)
            rejected = await bridge.tasks.wait_delivery(request.task_id)
            assert rejected["state"] == "failed"
            assert rejected["error"]["code"] == "visible_target_busy"
        else:
            token = bridge.security.grant("chatgpt", request)
            bridge.submit("chatgpt", request, token)
            admitted = await bridge.tasks.wait_delivery(request.task_id)
            assert admitted["state"] == "running"
            rejected = await receiver.send("chatgpt", message)
            assert rejected["processing"]["state"] == "failed"
            assert rejected["error"]["code"] == "visible_target_busy"
        assert transport["calls"] == ["insert", "return"]
        assert bridge.store.db.execute("SELECT count(*) FROM visible_handoffs").fetchone()[0] == 1
    finally:
        await receiver.stop()
        await bridge.tasks.stop()
