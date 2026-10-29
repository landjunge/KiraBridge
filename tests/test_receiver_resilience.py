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


async def test_restart_completes_a_delivered_handoff_when_the_reply_is_stored(visible):
    bridge, transport = visible
    sent = _running_handoff(bridge, "answered", "completed")
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
        assert job["state"] == "completed"
        assert job["evidence"]["reason"] == "reply_already_recorded"
        assert job["evidence"]["automatic_retry"] is False
        assert job["reply_id"]
        assert not transport["calls"]
    finally:
        await receiver.stop()


@pytest.mark.parametrize(
    "state,kept", [("sent", True), ("completed", True), ("inserting", False)]
)
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


async def test_same_recipient_stays_ordered_and_shutdown_drains_only_running_work(
    visible,
    monkeypatch,  # noqa: F811
):
    bridge, _ = visible
    receiver = bridge.message_receiver
    fake_receiver(monkeypatch, bridge, [])
    entered, release = asyncio.Event(), asyncio.Event()
    processed = []

    async def process(pool, message, run_id):
        processed.append(message["id"])
        entered.set()
        await release.wait()
        with bridge.store.transaction():
            receiver._finish(message["id"], "completed", {})

    monkeypatch.setattr(receiver, "_process", process)
    first = enqueue(bridge, key="ordered-first")
    second = enqueue(bridge, key="ordered-second")
    await receiver.start()
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert processed == [first["id"]]
        assert bridge.messages.get("chatgpt", second["id"])["processing"]["state"] == "queued"
        stopping = asyncio.create_task(receiver.stop())
        await asyncio.sleep(0)
        assert not stopping.done()
        release.set()
        await asyncio.wait_for(stopping, 1)
        assert processed == [first["id"]]
        # A new start drains the unchanged second message once, not the first again.
        entered.clear()
        await receiver.start()
        await asyncio.wait_for(entered.wait(), 1)
    finally:
        release.set()
        await receiver.stop()
    assert processed == [first["id"], second["id"]]


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

    async def process(pool, message, run_id):
        if message["recipient"] == "codex":
            entered.set()
            await release.wait()
        else:
            grok_started.set()
        with bridge.store.transaction():
            receiver._finish(message["id"], "completed", {"audit_stub": True})

    monkeypatch.setattr(bridge.visible_handoffs, "dispatch_ready", ready)
    monkeypatch.setattr(receiver, "_process", process)
    enqueue(bridge, target="codex", key="audit-running-codex")
    bridge.config.messaging.receivers["grok"] = ReceiverConfig(
        cwd=bridge.config.principals["grok"].roots[0], timeout=3
    )
    if same_pane:
        bridge.config.visible_handoffs.bindings["grok"] = bridge.config.visible_handoffs.bindings[
            "codex"
        ].model_copy()
    await receiver.start()
    try:
        await asyncio.wait_for(entered.wait(), 1)
        grok = enqueue(bridge, sender="codex", target="grok", key="audit-ready-grok")
        try:
            await asyncio.wait_for(grok_started.wait(), 0.1)
        except TimeoutError:
            pass
        before_release = bridge.messages.get("codex", grok["id"])["processing"]
        dispatched_while_codex_running = grok_started.is_set()
        release.set()
        await asyncio.wait_for(grok_started.wait(), 1)
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
