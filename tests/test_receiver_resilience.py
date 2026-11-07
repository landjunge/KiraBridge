"""Regression coverage for receiver isolation, preflight failures and final replies.

Only test adapters are replaced; no live terminal, credentials or service is used.
"""
# Imported fixture is supplied by pytest.
# ruff: noqa: F811

import asyncio

import pytest
from test_visible_dispatch_wait import enqueue, fake_receiver
from test_visible_handoff import visible  # noqa: F401

from kirabridge.bridge_core.config import ReceiverConfig
from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.message_manager import MessageSend
from kirabridge.message_manager.receiver import MessageReceiver


def _running_handoff(bridge, key, state):
    sent = enqueue(bridge, key=key)
    binding = bridge.config.visible_handoffs.bindings["grok"]
    handoff_id = "channel-" + key
    bridge.store.db.execute(
        "UPDATE message_jobs SET state='running',run_id=?,evidence=? WHERE message_id=?",
        (handoff_id, canonical({"handoff_id": handoff_id, "state": state}), sent["id"]),
    )
    bridge.store.db.execute(
        "INSERT INTO visible_handoffs VALUES(?,?, 'grok','hash',?,?, ?,1,1,?)",
        (
            handoff_id,
            "chatgpt",
            canonical(binding.model_dump()),
            sent["id"],
            state,
            canonical({"automatic_retry": False}),
        ),
    )
    return sent


@pytest.mark.parametrize("state", ["return_sent", "sent", "confirmed", "completed"])
@pytest.mark.parametrize("acknowledged", [False, True])
async def test_restart_requires_ack_and_stored_reply_for_completion(visible, state, acknowledged):
    bridge, transport = visible
    sent = _running_handoff(bridge, "answered", state)
    if acknowledged:
        incoming = bridge.messages.receive("grok")["messages"][0]
        bridge.messages.ack("grok", incoming["id"], incoming["receipt"])
    bridge.messages.send(
        "grok",
        MessageSend(
            recipient="chatgpt",
            conversation_id=sent["conversation_id"],
            idempotency_key="reply-" + sent["id"],
            body="stored",
            kind="result",
            reply_to=sent["id"],
            request_reply=False,
            dispatch=False,
        ),
    )
    receiver = MessageReceiver(bridge)
    await receiver.start()
    try:
        job = bridge.messages.get("chatgpt", sent["id"])["processing"]
        if acknowledged:
            assert job["state"] == "completed"
            assert job["evidence"]["reason"] == "reply_already_recorded"
            assert job["evidence"]["automatic_retry"] is False
            assert job["reply_id"]
        else:
            assert job["state"] == "running"
            assert job["reply_id"] is None
        assert not transport["calls"]
    finally:
        await receiver.stop()


@pytest.mark.parametrize("state,kept", [("sent", True), ("completed", True), ("inserting", False)])
async def test_restart_keeps_only_a_delivered_handoff(visible, state, kept):
    bridge, transport = visible
    sent = _running_handoff(bridge, state, state)
    receiver = MessageReceiver(bridge)
    await receiver.start()
    try:
        job = bridge.messages.get("chatgpt", sent["id"])["processing"]
        if kept:
            assert job["state"] == "running"
        else:
            assert job["state"] == "unknown" and job["error"] == "interrupted"
            assert job["evidence"]["reason"] == "receiver_restart"
        assert not transport["calls"]
    finally:
        await receiver.stop()


def _receive_handoff(bridge, sent):
    return bridge.messages.receive("grok", conversation_id=sent["conversation_id"])["messages"][0]


def _store_reply(bridge, sent, kind="result"):
    return bridge.messages.send(
        "grok",
        MessageSend(
            recipient="chatgpt",
            conversation_id=sent["conversation_id"],
            idempotency_key=kind + "-" + sent["id"],
            body="stored reply",
            kind=kind,
            reply_to=sent["id"],
            request_reply=False,
            dispatch=False,
        ),
    )


async def _wait_for_completion(bridge, sent):
    async with asyncio.timeout(3):
        while bridge.messages.get("chatgpt", sent["id"])["processing"]["state"] != "completed":
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("receipt_last", [False, True])
async def test_restart_finishes_late_reply_or_ack_without_input(visible, receipt_last):
    bridge, transport = visible
    sent = _running_handoff(bridge, "late", "sent")
    incoming = _receive_handoff(bridge, sent)
    if receipt_last:
        reply = _store_reply(bridge, sent)
    else:
        bridge.messages.ack("grok", sent["id"], incoming["receipt"])
    receiver = MessageReceiver(bridge)
    await receiver.start()
    try:
        assert bridge.messages.get("chatgpt", sent["id"])["processing"]["state"] == "running"
        # Let the replacement worker observe the still-incomplete evidence first.
        await asyncio.sleep(0)
        if receipt_last:
            bridge.messages.ack("grok", sent["id"], incoming["receipt"])
        else:
            reply = _store_reply(bridge, sent)
        await _wait_for_completion(bridge, sent)
        job = bridge.messages.get("chatgpt", sent["id"])["processing"]
        assert job["reply_id"] == reply["id"]
        assert job["evidence"]["handoff_id"] == "channel-late"
        assert job["evidence"]["reconciled_without_input"] is True
        assert job["evidence"]["automatic_retry"] is False
        handoff = bridge.visible_handoffs.status("chatgpt", "channel-late")
        assert handoff["state"] == "completed"
        assert handoff["evidence"]["reply_id"] == reply["id"]
        # A second observation and a second receiver start cannot duplicate completion.
        await receiver.stop()
        await receiver.start()
        await asyncio.sleep(0)
        assert bridge.store.db.execute("SELECT count(*) FROM completion_notices").fetchone()[0] == 1
        assert not transport["calls"]
    finally:
        await receiver.stop()


async def test_recovered_handoff_waits_for_final_reply(visible):
    bridge, transport = visible
    sent = _running_handoff(bridge, "nonfinal", "confirmed")
    incoming = _receive_handoff(bridge, sent)
    bridge.messages.ack("grok", sent["id"], incoming["receipt"])
    receiver = MessageReceiver(bridge)
    await receiver.start()
    try:
        _store_reply(bridge, sent, "note")
        await asyncio.sleep(0.02)
        assert bridge.messages.get("chatgpt", sent["id"])["processing"]["state"] == "running"
        reply = _store_reply(bridge, sent)
        await _wait_for_completion(bridge, sent)
        assert bridge.messages.get("chatgpt", sent["id"])["processing"]["reply_id"] == reply["id"]
        assert not transport["calls"]
    finally:
        await receiver.stop()


@pytest.mark.parametrize(
    "change",
    [
        "new_running",
        "unknown",
        "blocked",
        "unknown_on_start",
        "blocked_on_start",
        "handoff_unknown",
    ],
)
async def test_restart_recovery_preserves_other_execution_states(visible, change):
    bridge, transport = visible
    receiver = MessageReceiver(bridge)
    if change == "new_running":
        bridge.config.messaging.receivers["grok"] = ReceiverConfig(cwd="/tmp", timeout=3)
        await receiver.start()
        await asyncio.sleep(0)
    sent = _running_handoff(bridge, "preserved", "sent")
    incoming = _receive_handoff(bridge, sent)
    if change in {"unknown_on_start", "blocked_on_start"}:
        bridge.store.db.execute(
            "UPDATE message_jobs SET state=? WHERE message_id=?",
            (change.removesuffix("_on_start"), sent["id"]),
        )
    if change != "new_running":
        await receiver.start()
    try:
        if change in {"unknown", "blocked"}:
            bridge.store.db.execute(
                "UPDATE message_jobs SET state=? WHERE message_id=?", (change, sent["id"])
            )
        if change == "handoff_unknown":
            bridge.visible_handoffs.transition(
                "channel-preserved", "unknown", {"reason": "uncertain", "automatic_retry": False}
            )
        bridge.messages.ack("grok", sent["id"], incoming["receipt"])
        _store_reply(bridge, sent)
        await asyncio.sleep(0.02)
        expected = change.removesuffix("_on_start")
        expected = expected if expected in {"unknown", "blocked"} else "running"
        assert bridge.messages.get("chatgpt", sent["id"])["processing"]["state"] == expected
        handoff = bridge.visible_handoffs.status("chatgpt", "channel-preserved")
        assert handoff["state"] == ("unknown" if change == "handoff_unknown" else "sent")
        assert bridge.store.db.execute("SELECT count(*) FROM completion_notices").fetchone()[0] == 0
        assert not transport["calls"]
    finally:
        await receiver.stop()


@pytest.mark.parametrize("capability", ["task.read", "message.read"])
async def test_recovered_handoff_with_revoked_sender_rights_does_not_block_receiver(
    visible, capability
):
    bridge, transport = visible
    sent = _running_handoff(bridge, "revoked", "sent")
    incoming = _receive_handoff(bridge, sent)
    bridge.messages.ack("grok", sent["id"], incoming["receipt"])
    _store_reply(bridge, sent)
    bridge.config.principals["chatgpt"].capabilities.remove(capability)
    other = enqueue(bridge, sender="grok_app", key="still-authorized")
    received = _receive_handoff(bridge, other)
    bridge.messages.ack("grok", other["id"], received["receipt"])
    receiver = MessageReceiver(bridge)
    await receiver.start()
    try:
        async with asyncio.timeout(1):
            while (
                bridge.messages.get("grok_app", other["id"])["processing"]["state"] != "completed"
            ):
                await asyncio.sleep(0.01)
        original = bridge.store.db.execute(
            "SELECT state,reply_id FROM message_jobs WHERE message_id=?", (sent["id"],)
        ).fetchone()
        assert original["state"] == "running" and original["reply_id"] is None
        assert (
            bridge.store.db.execute(
                "SELECT state FROM visible_handoffs WHERE id='channel-revoked'"
            ).fetchone()[0]
            == "sent"
        )
        assert not transport["calls"]
        # Restoring permission permits observation of the same stored evidence, never a resend.
        bridge.config.principals["chatgpt"].capabilities.append(capability)
        bridge.messages.wake.set()
        await _wait_for_completion(bridge, sent)
        assert bridge.visible_handoffs.status("chatgpt", "channel-revoked")["state"] == "completed"
        assert not transport["calls"]
    finally:
        await receiver.stop()


async def test_restart_never_executes_historical_visible_backlog(
    visible,
    monkeypatch,  # noqa: F811
):
    bridge, _ = visible
    receiver = bridge.message_receiver
    fake_receiver(monkeypatch, bridge, [])
    processed = []
    fake_receiver(monkeypatch, bridge, processed)
    first = enqueue(bridge, key="ordered-first")
    second = enqueue(bridge, key="ordered-second")
    await receiver.start()
    try:
        await asyncio.sleep(0.02)
        assert processed == []
        before = [
            bridge.messages.get("chatgpt", row["id"])["processing"] for row in (first, second)
        ]
        assert all(row["state"] == "queued" and row["claimed"] is None for row in before)
        await receiver.stop()
        await receiver.start()
        await asyncio.sleep(0.02)
        assert [
            bridge.messages.get("chatgpt", row["id"])["processing"] for row in (first, second)
        ] == before
    finally:
        await receiver.stop()
    assert processed == []


@pytest.mark.parametrize("recover", [False, True])
async def test_connection_retries_back_off_and_survive_restart(visible, monkeypatch, recover):  # noqa: F811
    from kirabridge.bridge_core.bridge import Bridge

    bridge, transport = visible
    processed = []
    fake_receiver(monkeypatch, bridge, processed)
    sent = enqueue(bridge, key="retry")
    from kirabridge.message_manager.receiver import MCPClientPool

    attempts = []
    clock = [1000.0]

    async def connect(self, connection):
        attempts.append(clock[0])
        if len(attempts) == 1 or not recover:
            raise BridgeError("peer_connection", "Secret details must never enter evidence")

    monkeypatch.setattr(MCPClientPool, "connect", connect)
    monkeypatch.setattr("kirabridge.message_manager.receiver.time.time", lambda: clock[0])
    assert not await bridge.message_receiver._dispatch_next()
    first = bridge.messages.get("chatgpt", sent["id"])["processing"]
    clock[0] += 1
    assert not await bridge.message_receiver._dispatch_next()
    assert attempts == [1000.0]
    reopened = Bridge(bridge.config)
    try:
        assert reopened.messages.get("chatgpt", sent["id"])["processing"] == first
    finally:
        reopened.store.close()
    clock[0] += 1
    assert await bridge.message_receiver._dispatch_next() is recover
    if recover:
        assert processed == [sent["id"]] and len(attempts) == 2
        assert not await bridge.message_receiver._dispatch_next()
    else:
        clock[0] += 1
        assert not await bridge.message_receiver._dispatch_next()
        failed = bridge.messages.get("chatgpt", sent["id"])["processing"]
        assert failed["state"] == "failed" and failed["error"] == "peer_connection"
        assert failed["claimed"] is None and not processed and not transport["calls"]
        assert "Secret" not in str(failed)
        assert bridge.store.db.execute("SELECT count(*) FROM completion_notices").fetchone()[0] == 1
        assert not await bridge.message_receiver._dispatch_next()
        assert len(attempts) == 2


def test_full_conversation_only_allows_one_final_reply_per_accepted_request(visible):  # noqa: F811
    bridge, _ = visible
    bridge.config.messaging.max_conversation_messages = 2
    bridge.config.messaging.receivers["codex"] = ReceiverConfig(
        cwd=bridge.config.principals["codex"].roots[0], timeout=3
    )
    requests = []
    for n in range(2):
        requests.append(
            bridge.messages.send(
                "chatgpt",
                MessageSend(
                    recipient="codex",
                    conversation_id="bounded-replies",
                    idempotency_key=f"request-{n}",
                    kind="question",
                    dispatch=False,
                    body="Question",
                ),
            )
        )
    for n, request in enumerate(requests):
        reply = MessageSend(
            recipient="chatgpt",
            conversation_id="bounded-replies",
            idempotency_key=f"reply-{n}",
            kind="answer",
            dispatch=False,
            reply_to=request["id"],
            body="Answer",
        )
        result = bridge.messages.send("codex", reply)
        assert bridge.messages.send("codex", reply)["id"] == result["id"]
        with pytest.raises(BridgeError, match="message limit"):
            bridge.messages.send(
                "codex", reply.model_copy(update={"idempotency_key": f"extra-{n}"})
            )
        with pytest.raises(BridgeError, match="message limit"):
            bridge.messages.send(
                "codex",
                reply.model_copy(
                    update={
                        "idempotency_key": f"note-{n}",
                        "kind": "note",
                    }
                ),
            )
    assert bridge.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 4
    with pytest.raises(BridgeError, match="message limit"):
        bridge.messages.send(
            "chatgpt",
            MessageSend(
                recipient="codex",
                conversation_id="bounded-replies",
                idempotency_key="new-work",
                kind="question",
                dispatch=False,
                body="More work",
            ),
        )


async def test_final_reply_at_limit_releases_the_visible_reservation(visible):  # noqa: F811
    from test_visible_preinput import LocalRecipientPool

    bridge, transport = visible
    bridge.config.messaging.max_conversation_messages = 2
    note = bridge.messages.send(
        "chatgpt",
        MessageSend(
            recipient="grok",
            conversation_id="full-visible",
            idempotency_key="initial-note",
            body="Earlier context",
            kind="note",
            dispatch=False,
        ),
    )
    delivered = bridge.messages.receive("grok")["messages"][0]
    bridge.messages.ack("grok", note["id"], delivered["receipt"])
    sent = enqueue(bridge, key="full-visible")
    message, run_id = bridge.message_receiver._claim(sent["id"])
    await bridge.message_receiver._process(LocalRecipientPool(bridge, "grok"), message, run_id)
    completed = bridge.messages.get("chatgpt", sent["id"])["processing"]
    assert completed["state"] == "completed" and completed["reply_id"]
    assert bridge.visible_handoffs.status("chatgpt", run_id)["state"] == "completed"
    await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
    assert transport["calls"] == ["insert", "return"]


@pytest.mark.parametrize("same_pane", [False, True])
async def test_running_codex_only_holds_the_same_terminal(
    visible,
    monkeypatch,
    same_pane,  # noqa: F811
):
    bridge, _ = visible
    receiver = bridge.message_receiver
    fake_receiver(monkeypatch, bridge, [])
    entered = asyncio.Event()
    release = asyncio.Event()
    grok_started = asyncio.Event()

    async def ready(*args):
        return None

    async def process(pool, message, run_id, *, delivery_event=None, delivery_binding=None):
        if message["recipient"] == "codex":
            entered.set()
            await release.wait()
        else:
            grok_started.set()
        with bridge.store.transaction():
            receiver._finish(message["id"], "completed", {"audit_stub": True})

    monkeypatch.setattr(bridge.visible_handoffs, "dispatch_ready", ready)
    monkeypatch.setattr(receiver, "_process", process)
    bridge.config.messaging.receivers["codex"] = ReceiverConfig(cwd="/tmp", timeout=3)
    bridge.config.messaging.receivers["grok"] = ReceiverConfig(
        cwd=bridge.config.principals["grok"].roots[0], timeout=3
    )
    if same_pane:
        bridge.config.visible_handoffs.bindings["grok"] = bridge.config.visible_handoffs.bindings[
            "codex"
        ].model_copy()
    await receiver.start()
    try:
        enqueue(bridge, target="codex", key="audit-running-codex")
        await asyncio.wait_for(entered.wait(), 1)
        grok = enqueue(bridge, sender="codex", target="grok", key="audit-ready-grok")
        try:
            await asyncio.wait_for(grok_started.wait(), 0.1)
        except TimeoutError:
            pass
        before_release = bridge.messages.get("codex", grok["id"])["processing"]
        dispatched_while_codex_running = grok_started.is_set()
        release.set()
        if not same_pane:
            await asyncio.wait_for(grok_started.wait(), 1)
        else:
            assert before_release["state"] == "failed"
            assert before_release["error"] == "visible_target_busy"
    finally:
        release.set()
        await receiver.stop()
    assert dispatched_while_codex_running is not same_pane, (
        "Ready Grok remained " + before_release["state"] + " until the unrelated Codex turn ended"
    )


@pytest.mark.parametrize("code", ["peer_connection", "credentials_missing"])
async def test_preclaim_errors_have_durable_explanation(visible, monkeypatch, code):  # noqa: F811
    bridge, _ = visible
    fake_receiver(monkeypatch, bridge, [])
    sent = enqueue(bridge, key="audit-preclaim-" + code)

    if code == "peer_connection":
        from kirabridge.message_manager.receiver import MCPClientPool

        async def broken_connect(self, connection):
            raise BridgeError(code, "Synthetic connection failure")

        monkeypatch.setattr(MCPClientPool, "connect", broken_connect)
    else:

        def broken_peer(*args):
            raise BridgeError(code, "Synthetic credential lookup failure")

        monkeypatch.setattr("kirabridge.message_manager.receiver.peer", broken_peer)
    for _ in range(3):
        assert not await bridge.message_receiver._dispatch_next()
    job = bridge.messages.get("chatgpt", sent["id"])["processing"]
    assert job["claimed"] is None
    assert job["state"] == ("queued" if code == "peer_connection" else "failed")
    events = [
        row[0]
        for row in bridge.store.db.execute(
            "SELECT kind FROM message_events WHERE message_id=?", (sent["id"],)
        )
    ]
    assert job["evidence"].get("reason") == code or job["error"] == code, (
        f"Three {code} failures left evidence={job['evidence']}, "
        f"error={job['error']}, events={events}"
    )


def test_accepted_request_leaves_capacity_for_its_answer(visible):  # noqa: F811
    bridge, _ = visible
    conversation = "audit-full-conversation"
    for position in range(bridge.config.messaging.max_conversation_messages - 1):
        bridge.messages.send(
            "chatgpt",
            MessageSend(
                recipient="codex",
                conversation_id=conversation,
                idempotency_key=f"audit-note-{position}",
                body="Synthetic note",
                kind="note",
                request_reply=False,
                dispatch=False,
            ),
        )
    sent = enqueue(bridge, target="codex", key=conversation)
    assert sent["request_reply"]
    incoming = bridge.messages.receive("codex", after=sent["seq"] - 1)["messages"][0]
    bridge.messages.ack("codex", sent["id"], incoming["receipt"])
    try:
        bridge.messages.send(
            "codex",
            MessageSend(
                recipient="chatgpt",
                conversation_id=conversation,
                idempotency_key="audit-final-answer",
                reply_to=sent["id"],
                body="The requested result",
                kind="result",
                request_reply=False,
                dispatch=False,
            ),
        )
    except BridgeError as exc:
        pytest.fail(
            f"Accepted request at position {sent['position']} cannot be answered: {exc.code}"
        )
