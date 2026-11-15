"""Remote observation and channel conversation changes never select a local root."""

# Fixtures imported across the existing isolated message harness.
# ruff: noqa: F811
import asyncio
from types import SimpleNamespace

import pytest
from test_direct_delivery import delivery, settled  # noqa: F401
from test_native_codex_delivery import Protocol, binding  # noqa: F401
from test_visible_handoff import visible  # noqa: F401

from kirabridge.message_manager import MessageSend


async def test_remote_observer_disconnect_preserves_local_binding_and_durable_attempt(
    delivery, binding
):
    bridge, transport, direct, _, _ = delivery
    bridge.config.visible_handoffs.native_codex = binding
    bridge.messages.delivery_hook = bridge.message_receiver._submit_new
    configured = binding.model_dump()
    legacy = bridge.config.visible_handoffs.bindings["codex"].model_dump()
    protocol = Protocol(binding)
    host = protocol.host()
    accepted, release = asyncio.Event(), asyncio.Event()

    async def delayed_delivery(*args):
        result = await host.deliver(*args)
        accepted.set()
        await release.wait()
        return result

    direct.codex_host = SimpleNamespace(prepare=host.prepare, deliver=delayed_delivery)
    request = MessageSend(
        message_id="remote-observer-original", recipient="codex",
        conversation_id="remote-observer-before-reconnect", idempotency_key="remote-observer-key",
        kind="question", body="One synthetic authorized request", dispatch=True,
        request_reply=False,
    )
    caller = asyncio.create_task(bridge.message_receiver.send("chatgpt", request))
    await asyncio.wait_for(accepted.wait(), 3)
    caller.cancel()  # Models the remote request/response observer disappearing, not the Mac.
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert len(protocol.inputs()) == 1 and request.message_id in direct.active
    release.set()
    await settled(direct)
    after_reconnect = await bridge.message_receiver.send("chatgpt", request)
    assert after_reconnect["id"] == request.message_id
    assert after_reconnect["processing"]["state"] == "completed"
    assert len(protocol.inputs()) == 1
    assert bridge.config.visible_handoffs.native_codex.model_dump() == configured
    assert bridge.config.visible_handoffs.bindings["codex"].model_dump() == legacy
    assert after_reconnect["receipt"] is after_reconnect["acknowledged"] is None
    assert not transport["calls"]


async def test_two_channel_conversations_keep_the_same_confirmed_local_root(delivery, binding):
    bridge, transport, direct, _, _ = delivery
    bridge.config.visible_handoffs.native_codex = binding
    bridge.messages.delivery_hook = bridge.message_receiver._submit_new
    protocol = Protocol(binding)
    direct.codex_host = protocol.host()
    configured = binding.model_dump()
    outcomes = []
    for index in range(2):
        outcomes.append(await bridge.message_receiver.send("chatgpt", MessageSend(
            message_id=f"conversation-original-{index}", recipient="codex",
            conversation_id=f"independent-channel-conversation-{index}",
            idempotency_key=f"independent-conversation-key-{index}",
            kind="question", body=f"Synthetic new request {index}",
            dispatch=True, request_reply=False,
        )))
        await settled(direct)
    assert len(protocol.inputs()) == 2
    assert len({row["conversation_id"] for row in outcomes}) == 2
    assert {row["params"]["threadId"] for row in protocol.inputs()} == {binding.thread_id}
    assert {row["processing"]["evidence"]["host_generation"] for row in outcomes} == {
        protocol.generation
    }
    assert bridge.config.visible_handoffs.native_codex.model_dump() == configured
    assert not transport["calls"]
