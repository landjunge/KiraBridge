"""Direct delivery: bounded failure, no backlog replay, isolated active recipients."""

# ruff: noqa: F811
import asyncio
import time

import pytest
from test_visible_handoff import visible  # noqa: F401

from kirabridge.bridge_core.config import ReceiverConfig
from kirabridge.bridge_core.models import BridgeError
from kirabridge.message_manager import MessageSend


@pytest.fixture
def direct(visible, monkeypatch):
    bridge, transport = visible
    for name in ("codex", "grok"):
        bridge.config.messaging.receivers[name] = ReceiverConfig(cwd="/tmp", timeout=3)

    class Pool:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def connect(self, connection):
            pass

    monkeypatch.setattr("kirabridge.message_manager.direct.MCPClientPool", Pool)
    monkeypatch.setattr("kirabridge.message_manager.direct.peer", lambda *args: None)

    async def ready(*args, **kwargs):
        return {}

    monkeypatch.setattr(bridge.visible_handoffs, "check_target", ready)
    return bridge, transport


def send(bridge, key, target="grok"):
    return bridge.messages.send(
        "chatgpt",
        MessageSend(
            recipient=target,
            conversation_id=key,
            idempotency_key=key,
            body="One authorized direct request",
            kind="work",
        ),
    )


@pytest.mark.parametrize("reason", ["desktop_locked", "visible_target_working", "peer_connection"])
async def test_preinput_failure_is_terminal_and_never_retried_after_restart(
    direct, monkeypatch, reason
):
    bridge, transport = direct
    receiver = bridge.message_receiver
    attempts = []

    async def refuse(*args, **kwargs):
        attempts.append(1)
        raise BridgeError(reason, "Private diagnostic must not be exposed")

    monkeypatch.setattr(bridge.visible_handoffs, "check_target", refuse)
    await receiver.start()
    first = send(bridge, "failed")
    await receiver.direct.wait_delivery(first["id"])
    failed = bridge.messages.get("chatgpt", first["id"])
    assert failed["processing"]["state"] == "failed"
    assert failed["processing"]["error"] == reason
    assert "Private diagnostic" not in str(failed["processing"])
    await receiver.stop()
    await receiver.start()
    assert send(bridge, "failed")["id"] == first["id"]
    assert len(attempts) == 1 and not transport["calls"]
    assert not bridge.store.db.execute("SELECT 1 FROM message_jobs WHERE state='queued'").fetchone()
    await receiver.stop()


async def test_busy_recipient_fails_immediately_other_recipient_runs_and_no_second_execution(
    direct, monkeypatch
):
    bridge, _ = direct
    receiver = bridge.message_receiver
    entered, release = asyncio.Event(), asyncio.Event()
    processed = []

    async def process(pool, message, run_id, **kwargs):
        processed.append(message["id"])
        if message["recipient"] == "codex":
            entered.set()
            await release.wait()
        with bridge.store.transaction():
            receiver._finish(message["id"], "completed", {"unit_test_delivery": True})

    monkeypatch.setattr(receiver, "_process", process)
    await receiver.start()
    first = send(bridge, "first", "codex")
    await asyncio.wait_for(entered.wait(), 1)
    second = send(bridge, "busy", "codex")
    other = send(bridge, "other", "grok")
    await receiver.direct.wait_delivery(second["id"])
    await receiver.direct.wait_delivery(other["id"])
    assert bridge.messages.get("chatgpt", second["id"])["processing"]["error"] == "execution_busy"
    assert other["id"] in processed and second["id"] not in processed
    release.set()
    await receiver.direct.wait_delivery(first["id"])
    assert send(bridge, "busy", "codex")["processing"]["state"] == "failed"
    assert second["id"] not in processed
    await receiver.stop()


async def test_postinput_uncertainty_is_preserved_and_shutdown_never_replays(direct, monkeypatch):
    bridge, _ = direct
    receiver = bridge.message_receiver

    async def partial(pool, message, run_id, **kwargs):
        bridge.store.db.execute(
            "UPDATE message_jobs SET started=? WHERE message_id=?", (time.time(), message["id"])
        )
        raise RuntimeError("private process output")

    monkeypatch.setattr(receiver, "_process", partial)
    await receiver.start()
    first = send(bridge, "unknown")
    await receiver.direct.wait_delivery(first["id"])
    result = bridge.messages.get("chatgpt", first["id"])
    assert result["processing"]["state"] == "unknown"
    assert "private process output" not in str(result["processing"])
    await receiver.stop()
    await receiver.start()
    assert send(bridge, "unknown")["processing"]["state"] == "unknown"
    assert bridge.store.db.execute("SELECT count(*) FROM completion_notices").fetchone()[0] == 1
    await receiver.stop()


async def test_offline_requests_are_refused_without_persisting_a_queue(direct):
    bridge, _ = direct
    with pytest.raises(BridgeError, match="offline"):
        send(bridge, "offline")
    assert not bridge.store.db.execute("SELECT 1 FROM message_jobs").fetchone()


async def test_legacy_queued_label_with_claim_is_unknown_and_never_dispatched(direct):
    from test_visible_dispatch_wait import archive_request

    bridge, _ = direct
    original = archive_request(bridge)
    bridge.store.db.execute(
        "INSERT INTO message_jobs(message_id,state,run_id,claimed) VALUES(?,'queued','old-run',1)",
        (original["id"],),
    )
    await bridge.message_receiver.start()
    try:
        result = bridge.messages.get("chatgpt", original["id"])
        assert result["processing"]["state"] == "unknown"
        assert result["processing"]["run_id"] == "old-run"
        assert not bridge.message_receiver.direct.active
    finally:
        await bridge.message_receiver.stop()
