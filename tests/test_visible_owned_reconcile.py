"""A sender authorized to execute a visible handoff, but without public task.read,
must not turn its own submitted Return into a false forbidden/UNKNOWN.

Observed live (M4 isolated run): exact visible Return and provider transcript, then
UNKNOWN/forbidden because post-effect reconciliation used the public status read.
Public status/reconcile authorization and recipient-only ACK stay unchanged.
"""

# Imported fixtures are used through pytest's dependency injection.
# ruff: noqa: F811
import asyncio

import pytest
from test_receiver_resilience import _receive_handoff, _store_reply
from test_visible_dispatch_wait import enqueue
from test_visible_handoff import callback, visible  # noqa: F401

from kirabridge.bridge_core.models import AgentInput, BridgeError, UncertainExecution, canonical
from kirabridge.message_manager.receiver import MessageReceiver


def without_task_read(bridge, principal="chatgpt"):
    caps = bridge.config.principals[principal].capabilities
    caps[:] = [capability for capability in caps if capability != "task.read"]


@pytest.mark.parametrize("wait_for_reply", [True, False])
async def test_post_return_bookkeeping_needs_no_public_task_read(visible, wait_for_reply):
    bridge, transport = visible
    without_task_read(bridge)
    transport.update(ack=wait_for_reply, reply=wait_for_reply)
    identifier = f"owned-reconcile-{wait_for_reply}"
    result = await bridge.visible_handoffs.execute(
        {"id": identifier, "principal": "chatgpt"},
        AgentInput(agent="grok", prompt="Short M4 body", cwd="/tmp", wait_for_reply=wait_for_reply),
        callback,
        callback,
    )
    assert transport["calls"] == ["insert", "return"]  # exactly one paste and one Return
    if wait_for_reply:
        # The real recipient ACK and directed reply complete the turn.
        assert result["scope"] == "agent_turn" and result["text"] == "independent review"
        assert result["evidence"]["agent_confirmed"] is True
        state = bridge.store.db.execute(
            "SELECT state FROM visible_handoffs WHERE id=?", (identifier,)
        ).fetchone()["state"]
        assert state == "completed"
    else:
        assert result["scope"] == "visible_input_delivery"
        assert result["agent_confirmed"] is False and result["return_sent"] is True

    # Public reads keep their authorization: still forbidden for this sender.
    for read in (bridge.visible_handoffs.status, bridge.visible_handoffs.reconcile):
        with pytest.raises(BridgeError) as error:
            read("chatgpt", identifier)
        assert error.value.code == "forbidden"


async def test_owned_reexecution_never_replays_and_needs_no_task_read(visible):
    bridge, transport = visible
    without_task_read(bridge)
    task = {"id": "owned-reentry", "principal": "chatgpt"}
    args = AgentInput(agent="grok", prompt="Only once", cwd="/tmp")
    first = await bridge.visible_handoffs.execute(task, args, callback, callback)
    assert first["scope"] == "agent_turn"
    try:
        await bridge.visible_handoffs.execute(task, args, callback, callback)
    except BridgeError as error:
        assert error.code != "forbidden"  # classification, not a public-read failure
    assert transport["calls"] == ["insert", "return"]  # no second input


async def test_uncertain_reply_still_classified_without_public_read(visible, monkeypatch):
    """No ACK/reply within the bound: still UNKNOWN (correct), not forbidden."""
    bridge, transport = visible
    without_task_read(bridge)
    transport.update(ack=False, reply=False)
    with pytest.raises(UncertainExecution) as error:
        await bridge.visible_handoffs.execute(
            {"id": "owned-no-reply", "principal": "chatgpt"},
            AgentInput(agent="grok", prompt="No answer", cwd="/tmp", timeout=1),
            callback,
            callback,
        )
    assert error.value.code == "visible_reply_unknown"
    assert transport["calls"] == ["insert", "return"]


def test_ack_stays_recipient_only(visible):
    from kirabridge.message_manager import MessageSend

    bridge, _ = visible
    sent = bridge.messages.send(
        "chatgpt",
        MessageSend(
            recipient="grok",
            conversation_id="ack-scope",
            idempotency_key="ack-scope",
            body="note",
            kind="note",
            dispatch=False,
        ),
    )
    received = bridge.messages.receive("grok")["messages"]
    receipt = next(m for m in received if m["id"] == sent["id"])["receipt"]
    with pytest.raises(BridgeError) as error:
        bridge.messages.ack("chatgpt", sent["id"], receipt)
    assert error.value.code == "not_found"
    assert bridge.messages.ack("grok", sent["id"], receipt)["acknowledged"] is not None


async def test_next_same_pane_send_releases_original_transport_only_reservation(visible):
    bridge, transport = visible
    without_task_read(bridge)
    transport.update(ack=False, reply=False)
    args = AgentInput(agent="grok", prompt="First body", cwd="/tmp", wait_for_reply=False)
    handoffs = bridge.visible_handoffs
    first = await handoffs.execute(
        {"id": "owned-first", "principal": "chatgpt"}, args, callback, callback
    )
    first_status = handoffs._owned_status("owned-first", "chatgpt", "grok", first["message_id"])
    assert first_status["state"] == "sent"
    assert any(
        e["state"] == "planned" and e["evidence"].get("task_read_at_admission") is False
        for e in first_status["events"]
    )
    second = await handoffs.execute(
        {"id": "owned-second", "principal": "chatgpt"},
        args.model_copy(update={"prompt": "Second body"}),
        callback,
        callback,
    )
    assert first["scope"] == second["scope"] == "visible_input_delivery"
    assert first["message_id"] != second["message_id"]
    first_status = handoffs._owned_status("owned-first", "chatgpt", "grok", first["message_id"])
    assert first_status["evidence"]["input_reservation_released"] is True
    assert transport["calls"] == ["insert", "return", "insert", "return"]
    with pytest.raises(BridgeError) as denied:
        handoffs.status("chatgpt", "owned-first")
    assert denied.value.code == "forbidden"


async def test_independent_sender_cannot_reenter_another_senders_handoff(visible):
    bridge, transport = visible
    args = AgentInput(agent="grok", prompt="Original body", cwd="/tmp")
    handoffs = bridge.visible_handoffs
    await handoffs.execute(
        {"id": "owned-cross-sender", "principal": "chatgpt"}, args, callback, callback
    )
    for read in (handoffs.status, handoffs.reconcile):
        with pytest.raises(BridgeError) as denied:
            read("grok_app", "owned-cross-sender")
        assert denied.value.code == "not_found"
    with pytest.raises(BridgeError) as denied:
        await handoffs.execute(
            {"id": "owned-cross-sender", "principal": "grok_app"}, args, callback, callback
        )
    assert denied.value.code == "handoff_conflict"
    assert transport["calls"] == ["insert", "return"]


@pytest.mark.parametrize("exact_run", [True, False])
async def test_restart_reconciles_only_exact_run_without_original_task_read(visible, exact_run):
    bridge, transport = visible
    without_task_read(bridge)
    transport.update(ack=False, reply=False)
    sent = enqueue(bridge, key="owned-recovered")
    message_id = sent["id"]
    _, run_id = bridge.message_receiver._claim(message_id, direct=True)
    returned = asyncio.Event()

    async def persist(evidence):
        bridge.store.db.execute(
            "UPDATE message_jobs SET evidence=? WHERE message_id=?",
            (canonical(evidence), message_id),
        )
        if evidence.get("state") == "sent":
            returned.set()

    task = asyncio.create_task(
        bridge.visible_handoffs.execute(
            {"id": run_id, "principal": "chatgpt", "visible_message_id": message_id},
            AgentInput(agent="grok", prompt=sent["body"], cwd="/tmp"),
            persist,
            persist,
        )
    )
    try:
        await asyncio.wait_for(returned.wait(), timeout=2)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert transport["calls"] == ["insert", "return"]
    original = _receive_handoff(bridge, sent)
    bridge.messages.ack("grok", message_id, original["receipt"])
    reply = _store_reply(bridge, sent)
    if not exact_run:
        bridge.store.db.execute(
            "UPDATE message_jobs SET run_id=? WHERE message_id=?",
            ("independent-run", message_id),
        )
    receiver = MessageReceiver(bridge)
    await receiver.start()
    try:
        processing = bridge.messages.get("chatgpt", message_id)["processing"]
        status = bridge.visible_handoffs._owned_status(run_id, "chatgpt", "grok", message_id)
        if exact_run:
            assert processing["state"] == status["state"] == "completed"
            assert processing["reply_id"] == reply["id"]
            assert processing["evidence"]["reconciled_without_input"] is True
        else:
            assert processing["state"] == "unknown" and processing["reply_id"] is None
            assert status["state"] == "sent"  # the other run did not reconcile this handoff
        assert transport["calls"] == ["insert", "return"]
        with pytest.raises(BridgeError) as denied:
            bridge.visible_handoffs.status("chatgpt", run_id)
        assert denied.value.code == "forbidden"
    finally:
        await receiver.stop()
