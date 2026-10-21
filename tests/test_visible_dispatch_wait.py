# Imported pytest fixture is intentionally used as test parameters.
# ruff: noqa: F811
import json

import pytest
from test_mcp import http_bridge  # noqa: F401
from test_visible_handoff import visible  # noqa: F401

from kirabridge.bridge_core.config import ReceiverConfig
from kirabridge.bridge_core.models import BridgeError
from kirabridge.message_manager import MessageSend


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

    async def process(pool, message, run_id):
        processed.append(message["id"])

    monkeypatch.setattr(bridge.message_receiver, "_process", process)


@pytest.mark.parametrize("sender", ["chatgpt", "grok_app", "codex", "grok"])
async def test_busy_wait_does_not_claim_insert_or_complete_then_dispatches_once(
    visible, monkeypatch, sender
):
    bridge, transport = visible
    target = "codex" if sender == "grok" else "grok"
    transport["target"] = target
    transport["text"] = (
        "Thinking…\nesc to interrupt\n› " if target == "codex" else "Thinking…\n╭\n│ ❯ │\n╰"
    )
    bridge.config.visible_handoffs.bindings[target].busy_pattern = "Thinking…"
    sent = enqueue(bridge, sender, target)
    processed = []
    fake_receiver(monkeypatch, bridge, processed)
    if target == "codex":
        assert await bridge.message_receiver._dispatch_next()
        assert processed == [sent["id"]]
        assert not await bridge.message_receiver._dispatch_next()
        assert processed == [sent["id"]]
        return
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


async def test_real_http_wait_then_one_paste_return_and_authenticated_reply(
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
    transport["text"] = "Thinking…\n╭\n│ ❯ │\n╰"
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
        async with asyncio.timeout(5):
            while not bridge.messages.get("chatgpt", sent["id"])["processing"]["evidence"].get(
                "waiting_for_visible_target"
            ):
                await asyncio.sleep(0.02)
        assert transport["calls"] == []
        assert bridge.messages.get("chatgpt", sent["id"])["processing"]["state"] == "queued"
        transport["text"] = "╭\n│ ❯ │\n╰"
        bridge.messages.wake.set()
        async with asyncio.timeout(5):
            while bridge.messages.get("chatgpt", sent["id"])["processing"]["state"] != "completed":
                await asyncio.sleep(0.02)
        result = bridge.messages.get("chatgpt", sent["id"])
        assert result["acknowledged"] and result["processing"]["reply_id"]
        assert transport["calls"] == ["insert", "return"]
        assert bridge.store.db.execute("SELECT count(*) FROM visible_handoffs").fetchone()[0] == 1
        reply = bridge.messages.get("chatgpt", result["processing"]["reply_id"])
        assert reply["body"] == "independent review"
