"""Reproduce independent review findings without live terminals or providers."""

# Imported pytest fixture is intentionally used as a test parameter.
# ruff: noqa: F811
import asyncio
import json

import pytest
from test_visible_dispatch_wait import enqueue, fake_receiver
from test_visible_handoff import visible  # noqa: F401

from kirabridge.bridge_core.config import ReceiverConfig
from kirabridge.bridge_core.models import BridgeError


@pytest.mark.parametrize("wait_reason", ["desktop_locked", "visible_target_working"])
async def test_visible_wait_preserves_absolute_connection_deadline(
    visible, monkeypatch, wait_reason
):
    bridge, transport = visible
    fake_receiver(monkeypatch, bridge, [])
    sent = enqueue(bridge, key="retry-visible-flapping")
    clock, attempts = [1000.0], []
    blocked = [False]

    async def ready(*args):
        if blocked[0]:
            raise BridgeError(wait_reason, "Must wait without extending the connection deadline")

    async def connect(*args):
        attempts.append(clock[0])
        raise BridgeError("peer_connection", "Secret connection details")

    monkeypatch.setattr(bridge.visible_handoffs, "dispatch_ready", ready)
    monkeypatch.setattr("kirabridge.message_manager.receiver.MCPClientPool.connect", connect)
    monkeypatch.setattr("kirabridge.message_manager.receiver.time.time", lambda: clock[0])
    receiver = bridge.message_receiver
    assert not await receiver._dispatch_next()
    first = bridge.messages.get("chatgpt", sent["id"])["processing"]["evidence"]["receiver_retry"]
    clock[0], blocked[0] = 1002.0, True
    assert not await receiver._dispatch_next()
    waiting = bridge.messages.get("chatgpt", sent["id"])["processing"]
    assert waiting["evidence"].get("receiver_retry") == first
    clock[0], blocked[0] = 1003.0, False
    assert not await receiver._dispatch_next()
    ended = bridge.messages.get("chatgpt", sent["id"])["processing"]
    assert ended["state"] == "failed" and ended["error"] == "peer_connection"
    assert attempts == [1000.0] and not transport["calls"]
    assert ended["evidence"]["receiver_retry"]["deadline"] == 1003.0


@pytest.mark.parametrize(
    "error", [OSError("secret"), TimeoutError("secret"), json.JSONDecodeError("secret", "", 0)]
)
async def test_unexpected_preclaim_error_does_not_cancel_running_sibling(
    visible, monkeypatch, error
):
    bridge, transport = visible
    receiver = bridge.message_receiver
    fake_receiver(monkeypatch, bridge, [])
    for target in ("codex", "grok"):
        bridge.config.messaging.receivers[target] = ReceiverConfig(cwd="/tmp", timeout=3)
    entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def ready(sender, recipient):
        if recipient == "codex":
            await entered.wait()
            raise error

    async def process(pool, message, run_id, *, delivery_event, delivery_binding):
        assert message["id"] == grok["id"]
        entered.set()
        delivery_event.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        with bridge.store.transaction():
            receiver._finish(message["id"], "completed", {})

    monkeypatch.setattr(bridge.visible_handoffs, "dispatch_ready", ready)
    monkeypatch.setattr(receiver, "_process", process)
    await receiver.start()
    try:
        codex = enqueue(bridge, target="codex", key="fault-codex")
        grok = enqueue(bridge, target="grok", key="fault-grok")
        await asyncio.wait_for(entered.wait(), 1)

        async def settled():
            while not cancelled.is_set() and not receiver.worker.done():
                if bridge.messages.get("chatgpt", codex["id"])["processing"]["state"] == "failed":
                    return
                await asyncio.sleep(0)

        await asyncio.wait_for(settled(), 1)
        assert not cancelled.is_set() and not receiver.worker.done()
        failed = bridge.messages.get("chatgpt", codex["id"])["processing"]
        assert failed["error"] == "delivery_failed"
        assert failed["claimed"] is None and "secret" not in str(failed)
        assert failed["evidence"]["phase"] == "direct_admission"
        assert failed["evidence"]["terminal_input_attempted"] is False
        assert failed["evidence"]["automatic_retry"] is False
        assert bridge.messages.get("chatgpt", grok["id"])["processing"]["state"] == "running"
        assert not transport["calls"]
    finally:
        release.set()
        await asyncio.gather(*tuple(receiver.direct.active.values()), return_exceptions=True)
        await asyncio.gather(receiver.stop(), return_exceptions=True)
    assert bridge.messages.get("chatgpt", grok["id"])["processing"]["state"] == "completed"


async def test_outer_recipient_fault_does_not_stop_other_workers(visible, monkeypatch):
    bridge, transport = visible
    receiver = bridge.message_receiver
    fake_receiver(monkeypatch, bridge, [])
    for target in ("codex", "grok"):
        bridge.config.messaging.receivers[target] = ReceiverConfig(cwd="/tmp", timeout=3)
    entered, release, faulted = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    async def dispatch(recipient, *, include_visible):
        assert include_visible is False  # Runtime observation never resumes visible backlog.
        if recipient == "codex":
            await entered.wait()
            calls.append(recipient)
            faulted.set()
            raise OSError("Secret database observation failure")
        await release.wait()
        return False

    async def process(pool, message, run_id, *, delivery_event, delivery_binding):
        assert message["id"] == sibling["id"]
        entered.set()
        delivery_event.set()
        await release.wait()
        receiver._finish(message["id"], "completed", {})

    monkeypatch.setattr(receiver, "_dispatch_next", dispatch)
    monkeypatch.setattr(receiver, "_process", process)
    await receiver.start()
    try:
        sibling = enqueue(bridge, target="grok", key="loop-sibling")
        await asyncio.wait_for(faulted.wait(), 1)
        for _ in range(5):
            await asyncio.sleep(0)
        assert not receiver.worker.done()
        assert bridge.messages.get("chatgpt", sibling["id"])["processing"]["state"] == "running"
        audit = bridge.store.db.execute(
            "SELECT metadata FROM audit WHERE kind='message.receiver_loop_failed'"
        ).fetchall()
        assert audit and all(
            json.loads(row[0])["reason"] == "receiver_loop_failed" for row in audit
        )
        assert "Secret" not in str([tuple(row) for row in audit])
        assert not transport["calls"]
    finally:
        release.set()
        await asyncio.gather(*tuple(receiver.direct.active.values()), return_exceptions=True)
        await asyncio.gather(receiver.stop(), return_exceptions=True)
    assert calls
    assert bridge.messages.get("chatgpt", sibling["id"])["processing"]["state"] == "completed"


async def test_unexpected_postclaim_error_is_unknown_and_never_replayed(visible, monkeypatch):
    bridge, transport = visible
    receiver = bridge.message_receiver
    fake_receiver(monkeypatch, bridge, [])
    sent = enqueue(bridge, key="claimed-fault")
    attempts = []

    async def process(pool, message, run_id):
        attempts.append(message["id"])
        raise OSError("Secret uncertain result")

    monkeypatch.setattr(receiver, "_process", process)
    assert not await receiver._dispatch_next()
    current = bridge.messages.get("chatgpt", sent["id"])["processing"]
    assert current["state"] == "unknown" and current["error"] == "receiver_interrupted"
    assert not await receiver._dispatch_next()
    assert attempts == [sent["id"]] and not transport["calls"]
    assert "Secret" not in str(current)


async def test_stop_clears_failed_worker_handle(visible, monkeypatch):
    receiver = visible[0].message_receiver
    enqueue(visible[0], key="worker-stop-fault")

    async def fail():
        raise OSError("Synthetic worker failure")

    monkeypatch.setattr(receiver, "_loop", fail)
    await receiver.start()
    for _ in range(3):
        await asyncio.sleep(0)
    with pytest.raises(OSError):
        await receiver.stop()
    assert receiver.worker is None


async def test_start_replaces_finished_worker_handle(visible, monkeypatch):
    receiver = visible[0].message_receiver
    enqueue(visible[0], key="worker-start-fault")

    async def fail():
        raise OSError("Synthetic worker failure")

    monkeypatch.setattr(receiver, "_loop", fail)
    await receiver.start()
    failed = receiver.worker
    for _ in range(3):
        await asyncio.sleep(0)
    assert failed.done()
    failed.exception()
    await receiver.start()
    try:
        assert receiver.worker is not failed
    finally:
        await asyncio.gather(receiver.stop(), return_exceptions=True)


async def test_cancelled_stop_keeps_running_worker_owned_until_it_finishes(visible, monkeypatch):
    bridge, transport = visible
    receiver = bridge.message_receiver
    fake_receiver(monkeypatch, bridge, [])
    historical = enqueue(bridge, key="historical-before-start")
    entered, cleanup_entered, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    cleanup_finished, cleanup_interrupted = asyncio.Event(), asyncio.Event()
    delivery_events = []
    calls = []

    async def process(pool, message, run_id, *, delivery_event, delivery_binding):
        calls.append(message["id"])
        delivery_events.append(delivery_event)
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleanup_entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cleanup_interrupted.set()
                raise
            cleanup_finished.set()
            raise

    monkeypatch.setattr(receiver, "_process", process)
    await receiver.start()
    worker = receiver.worker
    stopping = None
    try:
        sent = enqueue(bridge, key="cancelled-stop")
        await asyncio.wait_for(entered.wait(), 1)
        stopping = asyncio.create_task(receiver.stop())
        await asyncio.wait_for(cleanup_entered.wait(), 1)
        stopping.cancel()
        await asyncio.sleep(0)
        assert not stopping.done()  # Owned cleanup is still referenced and shielded.
        assert not cleanup_finished.is_set() and not cleanup_interrupted.is_set()
        assert sent["id"] in receiver.direct.active
        assert receiver.direct.targets and not delivery_events[0].is_set()
        assert receiver.stopping and not receiver.direct.accepting
        await receiver.start()
        assert receiver.worker is worker and calls == [sent["id"]]
        assert receiver.stopping and not receiver.direct.accepting
        assert bridge.messages.get("chatgpt", historical["id"])["processing"]["state"] == "queued"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await stopping
        assert cleanup_finished.is_set() and not cleanup_interrupted.is_set()
        assert delivery_events[0].is_set()
        assert not receiver.direct.active and not receiver.direct.targets
    finally:
        release.set()
        if stopping is not None:
            await asyncio.gather(stopping, return_exceptions=True)
        await asyncio.gather(receiver.stop(), return_exceptions=True)
    assert receiver.worker is None
    current = bridge.messages.get("chatgpt", sent["id"])["processing"]
    assert current["state"] == "unknown" and current["evidence"]["automatic_retry"] is False
    assert bridge.messages.get("chatgpt", historical["id"])["processing"]["state"] == "queued"
    await receiver.start()
    try:
        for _ in range(5):
            await asyncio.sleep(0)
        assert calls == [sent["id"]]
        assert bridge.messages.get("chatgpt", sent["id"])["processing"] == current
        assert bridge.messages.get("chatgpt", historical["id"])["processing"]["state"] == "queued"
        assert not transport["calls"]  # Coroutine shutdown says nothing about a CLI process.
    finally:
        await receiver.stop()
