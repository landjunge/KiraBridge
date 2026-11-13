# Imported pytest fixture is intentionally used as test parameters.
# ruff: noqa: F811
import json

import pytest
from test_mcp import http_bridge  # noqa: F401
from test_visible_handoff import callback, visible  # noqa: F401

from kirabridge.bridge_core.config import ReceiverConfig
from kirabridge.bridge_core.models import AgentInput, BridgeError, canonical
from kirabridge.message_manager import MessageSend

# Full boxed footer required by the Grok paste-proof geometry; local to the
# dispatch test below so the shared simplified-box fixture stays untouched.
GROK_BOX_TOP = "╭──────╮"
GROK_BOX_BOTTOM = "╰────── Grok 1.0 ─╯"
GROK_EMPTY_FULL = GROK_BOX_TOP + "\n│ ❯      │\n" + GROK_BOX_BOTTOM


def fullbox_grok_insert(bridge, transport):
    async def insert(principal, args, *, before_transport=None):
        assert not args.submit
        if before_transport is not None:
            await before_transport()
        transport["calls"].append("insert")
        transport["inserted_body"] = args.text
        transport["text"] = GROK_BOX_TOP + "\n│ ❯ " + args.text + " │\n" + GROK_BOX_BOTTOM
        return {"paste_event_sent": True, "return_sent": False, "agent_confirmed": False}

    bridge.sessions.insert = insert


def enqueue(bridge, sender="chatgpt", target="grok", key="wait"):
    bridge.config.messaging.receivers[target] = ReceiverConfig(
        cwd=bridge.config.principals[target].roots[0], timeout=3
    )
    return bridge.messages.send(
        sender,
        MessageSend(
            recipient=target,
            conversation_id=key,
            idempotency_key=key,
            body="Only one visible handoff",
            kind="work",
            dispatch=True,
        ),
    )


def fake_receiver(monkeypatch, bridge, processed):
    class Pool:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def connect(self, connection):
            pass

    monkeypatch.setattr("kirabridge.message_manager.receiver.MCPClientPool", Pool)
    monkeypatch.setattr("kirabridge.message_manager.receiver.peer", lambda *args: None)
    monkeypatch.setattr("kirabridge.message_manager.direct.MCPClientPool", Pool)
    monkeypatch.setattr("kirabridge.message_manager.direct.peer", lambda *args: None)

    async def process(pool, message, run_id, **kwargs):
        processed.append(message["id"])

    monkeypatch.setattr(bridge.message_receiver, "_process", process)


def acknowledged_reservation(bridge, *, target="codex", state="unknown"):
    key = "old-" + target
    bridge.config.messaging.receivers[target] = ReceiverConfig(
        cwd=bridge.config.principals[target].roots[0], timeout=3
    )
    sent = bridge.messages.send(
        "chatgpt",
        MessageSend(
            recipient=target,
            conversation_id=key,
            idempotency_key=key,
            body="Previous accepted turn",
            kind="work",
            dispatch=False,
        ),
    )
    delivered = bridge.messages.receive(target, conversation_id=key)["messages"][0]
    bridge.messages.ack(target, sent["id"], delivered["receipt"])
    binding = bridge.config.visible_handoffs.bindings[target]
    bridge.store.db.execute(
        "INSERT INTO visible_handoffs VALUES('old-run','chatgpt',?,'hash',?,? ,?,1,1,?)",
        (
            target,
            canonical(binding.model_dump()),
            sent["id"],
            state,
            canonical({"reason": "reply_unconfirmed", "agent_confirmed": True}),
        ),
    )
    return "old-run"


def codex_protocol(bridge, state):
    binding = bridge.config.visible_handoffs.bindings["codex"]
    binding.codex_thread_id = "thread-test"
    binding.codex_rollout_path = "/tmp/thread-test.jsonl"

    async def read(path, thread_id):
        assert path == binding.codex_rollout_path
        assert thread_id == binding.codex_thread_id
        return {"state": state}

    bridge.visible_handoffs.codex_state.read = read


async def test_idle_codex_releases_acknowledged_reply_pending_reservation_once(visible):
    bridge, transport = visible
    transport["text"] = "› "
    codex_protocol(bridge, "idle")
    old_id = acknowledged_reservation(bridge)

    await bridge.visible_handoffs.dispatch_ready("chatgpt", "codex")

    old = bridge.visible_handoffs.status("chatgpt", old_id)
    assert old["state"] == "unknown"
    assert old["evidence"]["reason"] == "target_idle_reply_unconfirmed"
    assert old["evidence"]["automatic_retry"] is False
    assert transport["calls"] == []


async def test_idle_codex_allows_next_handoff_without_replaying_previous_message(visible):
    bridge, transport = visible
    transport["target"] = "codex"
    transport["text"] = "› "
    codex_protocol(bridge, "idle")
    old_id = acknowledged_reservation(bridge)

    result = await bridge.visible_handoffs.execute(
        {"id": "new-codex-run", "principal": "chatgpt"},
        AgentInput(agent="codex", prompt="One new authorized task", cwd="/tmp"),
        callback,
        callback,
    )

    assert result["text"] == "independent review"
    assert transport["calls"] == ["insert", "return"]
    assert bridge.visible_handoffs.status("chatgpt", old_id)["state"] == "unknown"
    assert bridge.visible_handoffs.status("chatgpt", "new-codex-run")["state"] == "completed"


async def test_working_codex_does_not_release_acknowledged_reservation(visible):
    bridge, transport = visible
    transport["text"] = "› "
    codex_protocol(bridge, "working")
    old_id = acknowledged_reservation(bridge)

    with pytest.raises(BridgeError) as exc:
        await bridge.visible_handoffs.dispatch_ready("chatgpt", "codex")

    assert exc.value.code == "visible_target_working"
    assert bridge.visible_handoffs.status("chatgpt", old_id)["state"] == "confirmed"
    assert transport["calls"] == []


@pytest.mark.parametrize("sender", ["chatgpt", "grok_app", "codex", "grok"])
async def test_busy_wait_does_not_claim_insert_or_complete_then_dispatches_once(
    visible, monkeypatch, sender
):
    bridge, transport = visible
    target = "codex" if sender == "grok" else "grok"
    transport["target"] = target
    transport["text"] = (
        "Thinking…\nesc to interrupt\n› " if target == "codex" else "╭\nThinking…\n│ ❯ │\n╰"
    )
    bridge.config.visible_handoffs.bindings[target].busy_pattern = "Thinking…"
    sent = enqueue(bridge, sender, target)
    processed = []
    fake_receiver(monkeypatch, bridge, processed)
    for _ in range(2):
        assert not await bridge.message_receiver._dispatch_next()
    current = bridge.messages.get(sender, sent["id"])["processing"]
    assert current["state"] == "queued" and current["claimed"] is None
    assert current["evidence"]["waiting_for_visible_target"]
    assert not transport["calls"] and not processed
    assert bridge.store.db.execute("SELECT count(*) FROM completion_notices").fetchone()[0] == 0
    assert (
        bridge.store.db.execute(
            "SELECT count(*) FROM message_events WHERE kind='message.waiting_for_visible_target'"
        ).fetchone()[0]
        == 1
    )
    transport["text"] = "› " if target == "codex" else "╭\n│ ❯ │\n╰"
    assert await bridge.message_receiver._dispatch_next()
    assert processed == [sent["id"]]
    assert not await bridge.message_receiver._dispatch_next()
    assert processed == [sent["id"]] and not transport["calls"]


async def test_busy_codex_does_not_block_ready_grok_and_same_target_keeps_order(
    visible, monkeypatch
):
    bridge, transport = visible
    first = enqueue(bridge, target="codex", key="codex-first")
    second = enqueue(bridge, target="codex", key="codex-second")
    third = enqueue(bridge, target="grok", key="grok-first")
    processed = []
    fake_receiver(monkeypatch, bridge, processed)
    original = bridge.sessions.read

    async def read(principal, pane, pid):
        if pane == bridge.config.visible_handoffs.bindings["codex"].pane_id:
            return {"text": "Not an empty Codex input"}
        return await original(principal, pane, pid)

    monkeypatch.setattr(bridge.sessions, "read", read)
    assert await bridge.message_receiver._dispatch_next()
    assert processed == [third["id"]]
    assert bridge.messages.get("chatgpt", first["id"])["processing"]["claimed"] is None
    assert bridge.messages.get("chatgpt", second["id"])["processing"]["claimed"] is None


async def test_unacknowledged_unknown_reservation_is_not_replayed_or_expired(visible, monkeypatch):
    bridge, transport = visible
    old = enqueue(bridge, sender="codex", key="old-unknown")
    bridge.store.db.execute(
        "UPDATE message_jobs SET state='unknown' WHERE message_id=?", (old["id"],)
    )
    binding = bridge.config.visible_handoffs.bindings["grok"]
    from kirabridge.bridge_core.models import canonical

    bridge.store.db.execute(
        "INSERT INTO visible_handoffs "
        "VALUES('old-run','codex','grok','hash',?,?,'unknown',1,1,'{}')",
        (canonical(binding.model_dump()), old["id"]),
    )
    sent = enqueue(bridge, key="new-after-old")
    processed = []
    fake_receiver(monkeypatch, bridge, processed)
    assert not await bridge.message_receiver._dispatch_next()
    assert not transport["calls"] and not processed
    assert bridge.messages.get("chatgpt", sent["id"])["processing"]["state"] == "queued"
    assert (
        bridge.store.db.execute("SELECT state FROM visible_handoffs WHERE id='old-run'").fetchone()[
            0
        ]
        == "unknown"
    )
    # Actual receipt + response by the original agent permits reconciliation,
    # even though the next queued sender is a different identity.
    incoming = next(m for m in bridge.messages.receive("grok")["messages"] if m["id"] == old["id"])
    bridge.messages.ack("grok", old["id"], incoming["receipt"])
    bridge.messages.send(
        "grok",
        MessageSend(
            recipient="codex",
            conversation_id="old-unknown",
            idempotency_key="old-result",
            reply_to=old["id"],
            kind="result",
            request_reply=False,
            body="Actually received",
        ),
    )
    assert await bridge.message_receiver._dispatch_next()
    assert processed == [sent["id"]]
    assert (
        bridge.store.db.execute("SELECT state FROM visible_handoffs WHERE id='old-run'").fetchone()[
            0
        ]
        == "completed"
    )


@pytest.mark.parametrize("guard", ["unknown", "started", "ack", "handoff", "wrong_error"])
def test_explicit_resume_refuses_any_possibly_executed_message(visible, guard):
    bridge, transport = visible
    sent = enqueue(bridge)
    bridge.message_receiver._claim(sent["id"])
    run_id = bridge.messages.get("chatgpt", sent["id"])["processing"]["run_id"]
    with bridge.store.transaction():
        bridge.message_receiver._finish(sent["id"], "failed", {}, "visible_target_busy")
        if guard == "unknown":
            bridge.store.db.execute(
                "UPDATE message_jobs SET state='unknown' WHERE message_id=?", (sent["id"],)
            )
        elif guard == "started":
            bridge.store.db.execute(
                "UPDATE message_jobs SET started=1 WHERE message_id=?", (sent["id"],)
            )
        elif guard == "ack":
            incoming = bridge.messages.receive("grok")["messages"][0]
            bridge.messages.ack("grok", sent["id"], incoming["receipt"])
        elif guard == "wrong_error":
            bridge.store.db.execute(
                "UPDATE message_jobs SET error='peer_unknown' WHERE message_id=?", (sent["id"],)
            )
        else:
            binding = json.dumps(bridge.config.visible_handoffs.bindings["grok"].model_dump())
            bridge.store.db.execute(
                "INSERT INTO visible_handoffs "
                "VALUES(?,'chatgpt','grok','h',?,?,'unknown',1,1,'{}')",
                (run_id, binding, sent["id"]),
            )
    with pytest.raises(BridgeError, match="do not resend"):
        bridge.message_receiver.resume_unsent(sent["id"])
    assert not transport["calls"]


def test_explicit_resume_of_proven_unsent_failure_preserves_old_completion_and_events(visible):
    bridge, transport = visible
    sent = enqueue(bridge)
    bridge.message_receiver._claim(sent["id"])
    with bridge.store.transaction():
        bridge.message_receiver._finish(sent["id"], "failed", {}, "visible_target_busy")
    notices = [tuple(r) for r in bridge.store.db.execute("SELECT * FROM completion_notices")]
    events = [tuple(r) for r in bridge.store.db.execute("SELECT * FROM message_events")]
    bridge.message_receiver.resume_unsent(sent["id"])
    current = bridge.messages.get("chatgpt", sent["id"])["processing"]
    assert current["state"] == "queued" and current["claimed"] is current["run_id"] is None
    assert [
        tuple(r) for r in bridge.store.db.execute("SELECT * FROM completion_notices")
    ] == notices
    assert [tuple(r) for r in bridge.store.db.execute("SELECT * FROM message_events")][
        : len(events)
    ] == events
    assert not transport["calls"]


async def test_readiness_race_after_claim_returns_to_queue_before_any_input(visible, monkeypatch):
    from types import SimpleNamespace

    bridge, transport = visible
    sent = enqueue(bridge)
    message, run_id = bridge.message_receiver._claim(sent["id"])

    class Pool:
        async def call(self, connection, tool, arguments):
            assert tool == "message_receive"
            value = bridge.messages.receive("grok", **arguments)
            return SimpleNamespace(structuredContent=value, isError=False)

    async def busy(*args, **kwargs):
        raise BridgeError("visible_target_not_ready", "Became busy before paste")

    monkeypatch.setattr(bridge.agents, "execute", busy)
    await bridge.message_receiver._process(Pool(), message, run_id)
    job = bridge.messages.get("chatgpt", sent["id"])["processing"]
    assert job["state"] == "queued" and job["run_id"] is None
    assert job["evidence"]["terminal_input_attempted"] is False
    assert not transport["calls"]
    assert bridge.store.db.execute("SELECT count(*) FROM completion_notices").fetchone()[0] == 0


async def test_waiting_reason_and_unclaimed_job_survive_reopen(visible, monkeypatch):
    from kirabridge.bridge_core.bridge import Bridge

    bridge, _ = visible
    sent = enqueue(bridge)
    processed = []
    fake_receiver(monkeypatch, bridge, processed)

    async def locked(*args):
        raise BridgeError("desktop_locked", "Mac locked")

    monkeypatch.setattr(bridge.visible_handoffs, "dispatch_ready", locked)
    assert not await bridge.message_receiver._dispatch_next()
    reopened = Bridge(bridge.config)
    try:
        job = reopened.messages.get("chatgpt", sent["id"])["processing"]
        assert job["state"] == "queued" and job["run_id"] is job["claimed"] is None
        assert job["evidence"]["reason"] == "desktop_locked"
        assert not processed
    finally:
        reopened.store.close()


async def test_real_http_refuses_busy_once_and_delivers_only_a_fresh_authorized_request(
    visible,
    http_bridge,
    config,
    monkeypatch,  # noqa: F811
):
    import asyncio

    from kirabridge.mcp_gateway.client import MCPClientPool, Peer

    bridge, transport = visible
    _, endpoint = http_bridge
    for identity in ["chatgpt", "grok"]:
        config.principals[identity].token_env = "WAIT_TEST_" + identity.upper()
        monkeypatch.setenv(config.principals[identity].token_env, identity + "-" + "x" * 48)
    config.messaging.receivers["grok"] = ReceiverConfig(
        cwd=config.principals["grok"].roots[0], timeout=3
    )
    config.visible_handoffs.bindings["grok"].busy_pattern = "Thinking…"
    fullbox_grok_insert(bridge, transport)
    transport["text"] = GROK_BOX_TOP + "\nThinking…\n│ ❯      │\n" + GROK_BOX_BOTTOM
    await bridge.message_receiver.start()
    async with MCPClientPool() as clients:
        await clients.connect(Peer("caller", url=endpoint, token="chatgpt-" + "x" * 48))
        sent = (
            await clients.call(
                "caller",
                "message_send",
                {
                    "completion_target": "wait-real-http",
                    "message": {
                        "recipient": "grok",
                        "conversation_id": "wait-http",
                        "idempotency_key": "one-message",
                        "kind": "work",
                        "body": "Multiline instruction\nSecond line",
                        "dispatch": True,
                    },
                },
            )
        ).structuredContent
        assert sent["error"]["code"] == "visible_target_working"
        assert sent["processing"]["state"] == "failed"
        assert sent["processing"]["claimed"] is None
        assert transport["calls"] == []
        transport["text"] = GROK_EMPTY_FULL
        bridge.messages.wake.set()
        repeated = (
            await clients.call(
                "caller",
                "message_send",
                {
                    "completion_target": "wait-real-http",
                    "message": {
                        "recipient": "grok",
                        "conversation_id": "wait-http",
                        "idempotency_key": "one-message",
                        "kind": "work",
                        "body": "Multiline instruction\nSecond line",
                        "dispatch": True,
                    },
                },
            )
        ).structuredContent
        assert repeated["id"] == sent["id"] and repeated["processing"]["state"] == "failed"
        assert transport["calls"] == []
        sent = (
            await clients.call(
                "caller",
                "message_send",
                {
                    "message": {
                        "recipient": "grok",
                        "conversation_id": "fresh-http",
                        "idempotency_key": "fresh-authorized-request",
                        "kind": "work",
                        "body": "A separate freshly authorized request",
                        "dispatch": True,
                    },
                },
            )
        ).structuredContent
        async with asyncio.timeout(5):
            while bridge.messages.get("chatgpt", sent["id"])["processing"]["state"] != "completed":
                await asyncio.sleep(0.02)
        result = bridge.messages.get("chatgpt", sent["id"])
        assert result["acknowledged"] and result["processing"]["reply_id"]
        assert transport["calls"] == ["insert", "return"]
        assert bridge.store.db.execute("SELECT count(*) FROM visible_handoffs").fetchone()[0] == 1
        reply = bridge.messages.get("chatgpt", result["processing"]["reply_id"])
        assert reply["body"] == "independent review"
