"""Keyboard uses existing dispatch/permission/lease paths; no events or worker starts."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.keyboard_models import KeyboardKeyInput
from kirabridge.operations import OPERATIONS
from kirabridge.system_operations import SYSTEM_LEAVES

TARGET = {
    "pid": 321,
    "expected_started_at": 1700000000.125,
    "target_token": "a" * 32,
    "helper_pid": 123,
    "worker_generation": "12345678-1234-1234-1234-123456789012",
    "expected_revision": "b" * 64,
}


def setup_keyboard(bridge):
    bridge.config.principals["local"].capabilities.append("keyboard.execute")
    bridge.macos.capability_probe.facts.update(platform="darwin", os_version="15.7.4")
    bridge.macos.capability_probe.native_metadata = lambda: {
        "available": True,
        "keyboard_protocol": 1,
    }
    return {
        "id": "own-key-1",
        "principal": "local",
        "operation": "keyboard.key",
        "args": {"target": TARGET, "key": {"named": "enter"}},
    }


async def test_keyboard_dispatch_uses_exact_target_owner_and_same_session_lock(bridge):
    task = setup_keyboard(bridge)
    trace = []

    async def send(operation, arguments, *, principal, before_send):
        assert bridge.sessions.lock.locked()
        assert operation == "keyboard.key" and principal == "local"
        assert arguments == task["args"]
        before_send()
        trace.append("native")
        return {"post_calls_returned": 2, "app_processing_confirmed": False}

    bridge.keyboard.transport.request = AsyncMock(side_effect=send)

    async def running(evidence):
        assert evidence["automatic_retry"] is False
        trace.append("running")

    result = await bridge.execute(task, running, running)
    assert trace == ["running", "native"]
    assert result["app_processing_confirmed"] is False
    assert not bridge.sessions.lock.locked()
    assert "keyboard.key" not in SYSTEM_LEAVES
    assert OPERATIONS["keyboard.key"].capability == "keyboard.execute"
    assert OPERATIONS["keyboard.key"].effect == "write"


async def test_keyboard_authorization_is_checked_again_at_native_send(bridge):
    task = setup_keyboard(bridge)

    async def send(operation, arguments, *, principal, before_send):
        bridge.config.principals["local"].capabilities.remove("keyboard.execute")
        before_send()
        pytest.fail("Revoked keyboard authorization must stop before any native send")

    bridge.keyboard.transport.request = AsyncMock(side_effect=send)
    with pytest.raises(BridgeError):
        await bridge.execute(task, AsyncMock(), AsyncMock())
    assert not bridge.sessions.lock.locked()


async def test_unknown_keyboard_delivery_is_never_replayed(bridge):
    task = setup_keyboard(bridge)
    bridge.keyboard.transport.request = AsyncMock(
        side_effect=UncertainExecution("key_unknown", "lost")
    )
    with pytest.raises(UncertainExecution):
        await bridge.execute(task, AsyncMock(), AsyncMock())
    assert bridge.keyboard.transport.request.await_count == 1
    assert not bridge.sessions.lock.locked()


async def test_keyboard_waits_for_existing_session_before_marking_running(bridge):
    task = setup_keyboard(bridge)
    running = AsyncMock()
    bridge.keyboard.transport.request = AsyncMock(return_value={"post_calls_returned": 2})
    async with bridge.sessions.lock:
        pending = asyncio.create_task(bridge.execute(task, running, running))
        await asyncio.sleep(0)
        running.assert_not_awaited()
        bridge.keyboard.transport.request.assert_not_awaited()
    await pending


def test_keyboard_key_intent_does_not_silently_add_a_submit():
    request = KeyboardKeyInput(target=TARGET, key={"named": "enter"})
    assert "submit" not in request.model_dump()


async def test_chord_uses_same_lease_and_passes_exact_requested_modifiers(bridge):
    task = setup_keyboard(bridge)
    task["operation"] = "keyboard.chord"
    task["args"] = {"target": TARGET, "key": {"character": "z"}, "modifiers": ["command", "shift"]}

    async def send(operation, arguments, *, principal, before_send):
        assert bridge.sessions.lock.locked()
        assert operation == "keyboard.chord" and arguments == task["args"]
        assert principal == "local"
        before_send()
        return {"app_processing_confirmed": False, "post_calls_returned": 2}

    bridge.keyboard.transport.request = AsyncMock(side_effect=send)
    result = await bridge.execute(task, AsyncMock(), AsyncMock())
    assert result["app_processing_confirmed"] is False
    assert bridge.keyboard.transport.request.await_count == 1
    assert OPERATIONS["keyboard.chord"].capability == "keyboard.execute"
    assert "keyboard.chord" not in SYSTEM_LEAVES


async def test_chord_failure_never_falls_back_to_a_key_operation(bridge):
    task = setup_keyboard(bridge)
    task["operation"] = "keyboard.chord"
    task["args"]["modifiers"] = ["command"]
    bridge.keyboard.transport.request = AsyncMock(
        side_effect=UncertainExecution("chord_unknown", "lost")
    )
    with pytest.raises(UncertainExecution):
        await bridge.execute(task, AsyncMock(), AsyncMock())
    bridge.keyboard.transport.request.assert_awaited_once()
    assert bridge.keyboard.transport.request.await_args.args[0] == "keyboard.chord"


async def test_native_text_is_literal_and_does_not_touch_clipboard(bridge):
    task = setup_keyboard(bridge)
    task["operation"] = "keyboard.text"
    task["args"] = {
        "target": TARGET,
        "text": " /resume go-go-go \r\n e\u0301 👩‍💻 ",
        "submit": False,
    }
    bridge.clipboard.read = AsyncMock(
        side_effect=AssertionError("Native text must not read clipboard")
    )
    bridge.clipboard.write = AsyncMock(
        side_effect=AssertionError("Native text must not write clipboard")
    )
    bridge.keyboard.transport.request = AsyncMock(return_value={"text_insertion_confirmed": True})
    await bridge.execute(task, AsyncMock(), AsyncMock())
    call = bridge.keyboard.transport.request.await_args
    assert call.args == ("keyboard.text", task["args"])
    assert "keyboard.text" not in SYSTEM_LEAVES
    assert not bridge.sessions.lock.locked()
    bridge.clipboard.read.assert_not_awaited()
    bridge.clipboard.write.assert_not_awaited()


@pytest.mark.parametrize(
    "change,code",
    [
        ({"submit": True}, "keyboard_submit_pending"),
        ({"text": "x" * 100000}, "keyboard_staging_pending"),
    ],
)
async def test_unfinished_text_modes_refuse_before_running_or_native_send(bridge, change, code):
    task = setup_keyboard(bridge)
    task["operation"] = "keyboard.text"
    task["args"] = {"target": TARGET, "text": "literal", **change}
    running = AsyncMock()
    bridge.keyboard.transport.request = AsyncMock()
    with pytest.raises(BridgeError) as caught:
        await bridge.execute(task, running, running)
    assert caught.value.code == code
    running.assert_not_awaited()
    bridge.keyboard.transport.request.assert_not_awaited()
