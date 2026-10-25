"""Visible reservation safety retained after removal of automatic wait/retry queues."""

# ruff: noqa: F811
import pytest
from test_visible_handoff import callback, visible  # noqa: F401

from kirabridge.bridge_core.config import ReceiverConfig
from kirabridge.bridge_core.models import AgentInput, BridgeError, canonical
from kirabridge.message_manager import MessageSend


def archive_request(bridge, sender="chatgpt", target="grok", key="archive"):
    """Seed a historical accepted message; this is not a live dispatch API."""
    return bridge.messages._send(
        sender,
        MessageSend(
            recipient=target,
            conversation_id=key,
            idempotency_key=key,
            body="Historical accepted question",
            kind="work",
            dispatch=False,
        ),
        visible_internal=True,
    )


def enqueue(bridge, sender="chatgpt", target="grok", key="legacy-fixture"):
    """Legacy accepted fixture for tests that exercise an already-owned turn."""
    bridge.config.messaging.receivers[target] = ReceiverConfig(cwd="/tmp", timeout=3)
    result = archive_request(bridge, sender, target, key)
    bridge.store.db.execute(
        "INSERT INTO message_jobs(message_id,state) VALUES(?,'accepted')", (result["id"],)
    )
    return bridge.messages.get(sender, result["id"])


def acknowledged_reservation(bridge, *, target="codex", state="unknown"):
    key = "old-" + target
    bridge.config.messaging.receivers[target] = ReceiverConfig(
        cwd=bridge.config.principals[target].roots[0], timeout=3
    )
    sent = bridge.messages._send(
        "chatgpt",
        MessageSend(
            recipient=target,
            conversation_id=key,
            idempotency_key=key,
            body="Previous accepted turn",
            kind="work",
            dispatch=False,
        ),
        visible_internal=True,
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
