"""Immediate admission uses isolated message stores and fake terminal transports."""
# Imported fixture is supplied by pytest.
# ruff: noqa: F811

import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from test_visible_handoff import visible  # noqa: F401

from kirabridge.bridge_core.config import ReceiverConfig
from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.message_manager import MessageSend


@pytest.fixture
async def delivery(visible, monkeypatch):
    bridge, transport = visible
    direct = bridge.message_receiver.direct
    direct.accepting = True
    connected = []
    for recipient in ("grok", "codex"):
        bridge.config.messaging.receivers[recipient] = ReceiverConfig(cwd="/tmp", timeout=3)

    class Pool:
        def __init__(self, **kwargs):
            self.recipient = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def connect(self, recipient):
            self.recipient = recipient
            connected.append(recipient)

        async def call(self, peer_name, tool, arguments):
            assert peer_name == "daemon"
            if tool == "message_receive":
                result = bridge.messages.receive(self.recipient, **arguments)
            elif tool == "message_get":
                result = bridge.messages.get(self.recipient, **arguments)
            elif tool == "message_ack":
                result = bridge.messages.ack(self.recipient, **arguments)
            else:
                raise AssertionError(tool)
            return SimpleNamespace(structuredContent=result, isError=False)

    monkeypatch.setattr("kirabridge.message_manager.direct.MCPClientPool", Pool)
    monkeypatch.setattr(
        "kirabridge.message_manager.direct.peer", lambda config, recipient: recipient
    )
    yield bridge, transport, direct, connected, Pool
    await direct.stop()


def new_message(bridge, key="direct", recipient="grok"):
    return bridge.messages.send(
        "chatgpt",
        MessageSend(
            recipient=recipient,
            conversation_id=key,
            idempotency_key=key,
            body="One newly authorized test request",
            kind="work",
            dispatch=True,
        ),
    )


def job(bridge, sent):
    return bridge.messages.get("chatgpt", sent["id"])["processing"]


async def settled(direct):
    async with asyncio.timeout(3):
        while direct.active:
            await asyncio.sleep(0)


@pytest.mark.parametrize("limit", ["conversation", "hourly"])
async def test_new_run_limit_rejection_stays_blocked_and_cannot_be_delivered_later(delivery, limit):
    bridge, transport, direct, _, _ = delivery
    prior = new_message(bridge, "limit-history")
    bridge.store.db.execute(
        "UPDATE message_jobs SET state='completed',claimed=? WHERE message_id=?",
        (time.time(), prior["id"]),
    )
    request = MessageSend(
        recipient="grok",
        conversation_id=prior["conversation_id"],
        idempotency_key="new-over-limit",
        body="This request is never admitted",
        kind="work",
        dispatch=True,
    )
    if limit == "conversation":
        bridge.config.messaging.max_runs_per_conversation = 1
    else:
        bridge.config.messaging.max_runs_per_hour = 1
    sent = bridge.messages.send("chatgpt", request)
    direct.submit("chatgpt", sent["id"])
    await direct.wait_delivery(sent["id"])
    current = job(bridge, sent)
    assert current["state"] == "blocked"
    assert current["evidence"]["reason"] == limit + "_run_limit"
    assert current["claimed"] is None and current["started"] is None
    assert not transport["calls"]
    assert bridge.store.db.execute(
        "SELECT 1 FROM queue_holds WHERE queue_id='messages' AND item_id=?", (sent["id"],)
    ).fetchone()
    inbox = bridge.messages.receive("grok", after=sent["seq"] - 1)["messages"]
    assert inbox == []
    assert bridge.messages.send("chatgpt", request)["id"] == sent["id"]
    assert not direct.submit("chatgpt", sent["id"])


async def test_ready_target_gets_exactly_one_paste_return_and_authenticated_answer(delivery):
    bridge, transport, direct, connected, _ = delivery
    sent = new_message(bridge)
    assert direct.submit("chatgpt", sent["id"])
    await direct.wait_delivery(sent["id"])
    await settled(direct)
    assert job(bridge, sent)["state"] == "completed"
    assert transport["calls"] == ["insert", "return"]
    assert connected == ["grok"]
    assert not direct.submit("chatgpt", sent["id"])
    assert transport["calls"] == ["insert", "return"]


@pytest.mark.parametrize(
    "code",
    [
        "visible_target_busy",
        "visible_target_working",
        "visible_target_unknown",
        "session_busy",
        "session_selection_changed",
        "desktop_locked",
        "forbidden",
    ],
)
async def test_blocked_target_fails_once_without_claim_or_private_error_text(
    delivery, monkeypatch, code
):
    bridge, transport, direct, connected, _ = delivery

    async def refuse(*args):
        error = BridgeError(code, "PRIVATE EXCEPTION CONTENT MUST NOT APPEAR")
        error.observation = {
            "state": "reserved",
            "handoff_id": "old-handoff",
            "text": "PRIVATE SCREEN",
        }
        raise error

    monkeypatch.setattr(bridge.visible_handoffs, "dispatch_ready", refuse)
    sent = new_message(bridge)
    direct.submit("chatgpt", sent["id"])
    await direct.wait_delivery(sent["id"])
    current = job(bridge, sent)
    assert current["state"] == "failed" and current["error"] == code
    assert current["claimed"] is None and current["started"] is None
    assert current["evidence"]["phase"] == "direct_admission"
    assert current["evidence"]["terminal_input_attempted"] is False
    assert current["evidence"]["automatic_retry"] is False
    assert current["evidence"]["observation"]["handoff_id"] == "old-handoff"
    assert "PRIVATE" not in json.dumps(current)
    assert not transport["calls"] and not connected
    assert not direct.submit("chatgpt", sent["id"])


async def test_selection_race_after_internal_receipt_is_failed_without_requeue(
    delivery, monkeypatch
):
    bridge, transport, direct, _, _ = delivery

    async def refuse(*args, **kwargs):
        raise BridgeError("session_selection_changed", "changed before any handoff or input")

    monkeypatch.setattr(bridge.agents, "execute", refuse)
    sent = new_message(bridge)
    direct.submit("chatgpt", sent["id"])
    await direct.wait_delivery(sent["id"])
    current = job(bridge, sent)
    assert current["claimed"] is not None and current["started"] is None
    assert bridge.messages.get("chatgpt", sent["id"])["delivered"] is not None
    assert current["state"] == "failed" and current["error"] == "session_selection_changed"
    assert current["evidence"]["terminal_input_attempted"] is False
    assert not transport["calls"]
    assert not bridge.store.db.execute(
        "SELECT 1 FROM message_events WHERE message_id=? AND kind='message.unsent_requeued'",
        (sent["id"],),
    ).fetchone()


async def test_return_uncertainty_is_never_repeated(delivery):
    bridge, transport, direct, _, _ = delivery
    transport["fail"] = True
    sent = new_message(bridge)
    direct.submit("chatgpt", sent["id"])
    await direct.wait_delivery(sent["id"])
    assert job(bridge, sent)["state"] == "unknown"
    assert job(bridge, sent)["evidence"]["automatic_retry"] is False
    assert transport["calls"] == ["insert", "return"]
    transport["fail"] = False
    assert not direct.submit("chatgpt", sent["id"])
    repeated = new_message(bridge)
    assert repeated["id"] == sent["id"] and repeated["processing"]["state"] == "unknown"
    assert transport["calls"] == ["insert", "return"]


async def test_cancelled_caller_does_not_cancel_delivery(delivery, monkeypatch):
    bridge, transport, direct, _, pool = delivery
    entered, release = asyncio.Event(), asyncio.Event()
    connect = pool.connect

    async def gated_connect(self, recipient):
        entered.set()
        await release.wait()
        await connect(self, recipient)

    monkeypatch.setattr(pool, "connect", gated_connect)
    sent = new_message(bridge)
    direct.submit("chatgpt", sent["id"])
    await entered.wait()
    caller = asyncio.create_task(direct.wait_delivery(sent["id"]))
    await asyncio.sleep(0)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert sent["id"] in direct.active
    release.set()
    await settled(direct)
    assert job(bridge, sent)["state"] == "completed"
    assert transport["calls"] == ["insert", "return"]


async def test_watchdog_bounds_preflight_without_any_waiting_caller(delivery, monkeypatch):
    bridge, transport, direct, _, _ = delivery
    direct.delivery_timeout = 0.02

    async def never_ready(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(bridge.visible_handoffs, "dispatch_ready", never_ready)
    sent = new_message(bridge)
    direct.submit("chatgpt", sent["id"])
    await settled(direct)
    current = job(bridge, sent)
    assert current["state"] == "failed" and current["error"] == "delivery_timeout"
    assert current["evidence"]["terminal_input_attempted"] is False
    assert current["evidence"]["automatic_retry"] is False
    assert current["claimed"] is None and not transport["calls"]


async def test_watchdog_keeps_a_claimed_ambiguous_attempt_unknown(delivery, monkeypatch):
    bridge, transport, direct, _, _ = delivery
    direct.delivery_timeout = 0.02

    async def unresolved(pool, message, run_id, *, delivery_event, delivery_binding=None):
        await asyncio.Event().wait()

    monkeypatch.setattr(bridge.message_receiver, "_process", unresolved)
    sent = new_message(bridge)
    direct.submit("chatgpt", sent["id"])
    await settled(direct)
    current = job(bridge, sent)
    assert current["state"] == "unknown" and current["error"] == "delivery_timeout"
    assert current["evidence"]["terminal_input_attempted"] == "unconfirmed"
    assert not direct.submit("chatgpt", sent["id"]) and not transport["calls"]


async def test_delivery_deadline_does_not_cancel_a_sent_reply_waiter(delivery, monkeypatch):
    bridge, _, direct, _, _ = delivery
    direct.delivery_timeout = 0.02
    release = asyncio.Event()

    async def pending_reply(pool, message, run_id, *, delivery_event, delivery_binding=None):
        delivery_event.set()
        await release.wait()
        bridge.message_receiver._finish(message["id"], "completed", {"reply_observed": True})

    monkeypatch.setattr(bridge.message_receiver, "_process", pending_reply)
    sent = new_message(bridge)
    direct.submit("chatgpt", sent["id"])
    await direct.wait_delivery(sent["id"])
    await asyncio.sleep(0.04)
    assert sent["id"] in direct.active and job(bridge, sent)["state"] == "running"
    release.set()
    await settled(direct)
    assert job(bridge, sent)["state"] == "completed"


@pytest.mark.parametrize("same_pane", [False, True])
async def test_competing_admission_is_rejected_instead_of_waiting(delivery, monkeypatch, same_pane):
    bridge, transport, direct, connected, _ = delivery
    release = asyncio.Event()

    async def pending_reply(pool, message, run_id, *, delivery_event, delivery_binding=None):
        delivery_event.set()
        await release.wait()
        bridge.message_receiver._finish(message["id"], "completed", {})

    monkeypatch.setattr(bridge.message_receiver, "_process", pending_reply)
    if same_pane:
        bridge.config.visible_handoffs.bindings["codex"] = bridge.config.visible_handoffs.bindings[
            "grok"
        ].model_copy()

        async def observe_only(*args):
            pass

        monkeypatch.setattr(bridge.visible_handoffs, "dispatch_ready", observe_only)
    first = new_message(bridge, "first")
    direct.submit("chatgpt", first["id"])
    await direct.wait_delivery(first["id"])
    second = new_message(bridge, "second", "codex" if same_pane else "grok")
    direct.submit("chatgpt", second["id"])
    await direct.wait_delivery(second["id"])
    current = job(bridge, second)
    assert current["state"] == "failed"
    assert current["error"] == ("visible_target_busy" if same_pane else "execution_busy")
    assert current["claimed"] is None
    assert connected == ["grok"] and not transport["calls"]
    assert job(bridge, first)["state"] == "running"
    release.set()
    await settled(direct)


async def test_an_existing_running_job_blocks_only_new_admission(delivery):
    bridge, transport, direct, connected, _ = delivery
    previous = new_message(bridge, "previous")
    bridge.store.db.execute(
        "UPDATE message_jobs SET state='running',run_id='prior-run',claimed=1 WHERE message_id=?",
        (previous["id"],),
    )
    original = job(bridge, previous)
    sent = new_message(bridge, "new")
    direct.submit("chatgpt", sent["id"])
    await direct.wait_delivery(sent["id"])
    assert job(bridge, sent)["error"] == "execution_busy"
    assert job(bridge, previous) == original
    assert not transport["calls"] and not connected


async def test_new_message_does_not_select_or_dispatch_historical_queued_work(
    delivery, monkeypatch
):
    bridge, transport, direct, _, _ = delivery
    previous = new_message(bridge, "historical")
    original = job(bridge, previous)
    processed = []

    async def finish_new(pool, message, run_id, *, delivery_event, delivery_binding=None):
        processed.append(message["id"])
        bridge.message_receiver._finish(message["id"], "completed", {})
        delivery_event.set()

    monkeypatch.setattr(bridge.message_receiver, "_process", finish_new)
    sent = new_message(bridge, "new")
    direct.submit("chatgpt", sent["id"])
    await settled(direct)
    assert processed == [sent["id"]]
    assert job(bridge, previous) == original
    assert not transport["calls"]


@pytest.mark.parametrize("change", ["unknown", "claimed", "receipt", "foreign", "evidence", "hold"])
async def test_submit_cannot_reactivate_an_old_or_conflicting_record(delivery, change):
    bridge, transport, direct, connected, _ = delivery
    sent = new_message(bridge)
    if change == "unknown":
        bridge.store.db.execute(
            "UPDATE message_jobs SET state='unknown' WHERE message_id=?", (sent["id"],)
        )
    elif change == "claimed":
        bridge.store.db.execute(
            "UPDATE message_jobs SET claimed=1 WHERE message_id=?", (sent["id"],)
        )
    elif change == "receipt":
        bridge.messages.receive("grok", conversation_id=sent["conversation_id"])
    elif change == "evidence":
        bridge.store.db.execute(
            "UPDATE message_jobs SET evidence=? WHERE message_id=?",
            (canonical({"terminal_input_attempted": False, "reason": "historical"}), sent["id"]),
        )
    elif change == "hold":
        bridge.store.db.execute(
            "INSERT INTO queue_holds(queue_id,item_id,actor,created,reason) "
            "VALUES('messages',?,?,1,'test hold')",
            (sent["id"], "chatgpt"),
        )
    original = job(bridge, sent)
    assert not direct.submit("grok" if change == "foreign" else "chatgpt", sent["id"])
    assert not direct.active and job(bridge, sent) == original
    assert not transport["calls"] and not connected


async def test_stop_before_task_entry_preserves_other_tasks_and_never_replays(delivery):
    bridge, transport, direct, _, _ = delivery
    unrelated_event = asyncio.Event()
    unrelated = asyncio.create_task(unrelated_event.wait())
    try:
        sent = new_message(bridge)
        direct.submit("chatgpt", sent["id"])
        await direct.stop()
        assert job(bridge, sent)["state"] == "failed"
        assert job(bridge, sent)["evidence"]["terminal_input_attempted"] is False
        assert not unrelated.done() and not transport["calls"]
        direct.accepting = True
        assert not direct.submit("chatgpt", sent["id"])
    finally:
        unrelated_event.set()
        await unrelated


async def test_stop_preserves_delivered_running_handoff_for_existing_reply_recovery(
    delivery, monkeypatch
):
    bridge, transport, direct, _, _ = delivery

    async def sent_waiter(pool, message, run_id, *, delivery_event, delivery_binding=None):
        binding = bridge.config.visible_handoffs.bindings[message["recipient"]]
        evidence = {"handoff_id": run_id, "state": "sent"}
        bridge.store.db.execute(
            "INSERT INTO visible_handoffs VALUES(?,?,?,?,?,?,'sent',1,1,?)",
            (
                run_id,
                message["sender"],
                message["recipient"],
                "hash",
                canonical(binding.model_dump()),
                message["id"],
                canonical(evidence),
            ),
        )
        bridge.store.db.execute(
            "UPDATE message_jobs SET started=1,evidence=? WHERE message_id=?",
            (canonical(evidence), message["id"]),
        )
        delivery_event.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(bridge.message_receiver, "_process", sent_waiter)
    sent = new_message(bridge)
    direct.submit("chatgpt", sent["id"])
    await direct.wait_delivery(sent["id"])
    original = job(bridge, sent)
    await direct.stop()
    assert job(bridge, sent) == original and original["state"] == "running"
    assert not transport["calls"] and not direct.submit("chatgpt", sent["id"])


@pytest.mark.parametrize("phase", ["before_entry", "during_preflight", "after_claim"])
async def test_concurrent_claim_cannot_be_overwritten_by_old_direct_driver(
    delivery, monkeypatch, phase
):
    bridge, transport, direct, connected, _ = delivery
    sent = new_message(bridge)

    def foreign_claim():
        bridge.store.db.execute(
            "UPDATE message_jobs SET state='running',run_id='foreign-run',claimed=2,evidence=? "
            "WHERE message_id=?",
            (canonical({"owner": "another admitted execution"}), sent["id"]),
        )

    if phase == "during_preflight":

        async def observe_then_change(*args):
            foreign_claim()

        monkeypatch.setattr(bridge.visible_handoffs, "dispatch_ready", observe_then_change)
    elif phase == "after_claim":

        async def change_owner(pool, message, run_id, **kwargs):
            foreign_claim()
            raise BridgeError("visible_target_busy", "A different owner now holds this record")

        monkeypatch.setattr(bridge.message_receiver, "_process", change_owner)
    direct.submit("chatgpt", sent["id"])
    if phase == "before_entry":
        foreign_claim()
    await settled(direct)
    current = job(bridge, sent)
    assert current["state"] == "running" and current["run_id"] == "foreign-run"
    assert current["evidence"] == {"owner": "another admitted execution"}
    assert current["error"] is None and not transport["calls"]
    if phase != "after_claim":
        assert not connected


async def test_confirmed_binding_is_pinned_across_peer_connection(delivery, monkeypatch):
    bridge, transport, direct, _, pool = delivery
    original = bridge.config.visible_handoffs.bindings["grok"].model_copy(deep=True)
    connect = pool.connect

    async def change_config(self, recipient):
        await connect(self, recipient)
        bridge.config.visible_handoffs.bindings[recipient].pane_id = "terminal:999:ttys009"

    async def inspect_binding(pool, message, run_id, *, delivery_event, delivery_binding):
        assert delivery_binding == original
        assert delivery_binding != bridge.config.visible_handoffs.bindings["grok"]
        assert ("pane", original.pane_id) in direct.targets
        bridge.message_receiver._finish(message["id"], "completed", {})
        delivery_event.set()

    monkeypatch.setattr(pool, "connect", change_config)
    monkeypatch.setattr(bridge.message_receiver, "_process", inspect_binding)
    sent = new_message(bridge)
    direct.submit("chatgpt", sent["id"])
    await settled(direct)
    assert job(bridge, sent)["state"] == "completed" and not transport["calls"]


def public_request(key):
    return MessageSend(
        recipient="grok",
        conversation_id=key,
        idempotency_key=key,
        body="One public receiver-send request",
        kind="work",
        dispatch=True,
    )


async def test_public_send_observes_one_ready_delivery(delivery):
    bridge, transport, direct, _, _ = delivery
    receiver = bridge.message_receiver
    await receiver.start()
    try:
        result = await receiver.send("chatgpt", public_request("public-ready"))
        assert "error" not in result
        assert result["processing"]["state"] in {"running", "completed"}
        assert transport["calls"] == ["insert", "return"]
        await settled(direct)
        assert job(bridge, result)["state"] == "completed"
    finally:
        await receiver.stop()


async def test_public_busy_result_is_immediate_and_same_id_never_retries_when_ready(delivery):
    bridge, transport, direct, connected, _ = delivery
    receiver = bridge.message_receiver
    transport["text"] = "Thinking…\n╭\n│ ❯ │\n╰"
    await receiver.start()
    try:
        request = public_request("public-busy")
        result = await receiver.send("chatgpt", request)
        assert result["error"]["code"] == "visible_target_working"
        assert result["processing"]["state"] == "failed"
        assert result["processing"]["claimed"] is None
        transport["text"] = "╭\n│ ❯ │\n╰"
        repeated = await receiver.send("chatgpt", request)
        assert repeated["id"] == result["id"]
        assert repeated["error"]["code"] == "visible_target_working"
        assert not transport["calls"] and not connected
        assert not direct.submit("chatgpt", result["id"])
    finally:
        await receiver.stop()


async def test_public_send_without_active_receiver_returns_durable_unavailable(delivery):
    bridge, transport, direct, connected, _ = delivery
    direct.accepting = False
    result = await bridge.message_receiver.send("chatgpt", public_request("not-running"))
    assert result["error"]["code"] == "receiver_unavailable"
    current = job(bridge, result)
    assert current["state"] == "failed" and current["claimed"] is None
    assert current["evidence"]["terminal_input_attempted"] is False
    assert current["evidence"]["automatic_retry"] is False
    assert not direct.active and not connected and not transport["calls"]
