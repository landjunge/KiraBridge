"""Keyboard uses existing dispatch/permission/lease paths; no events or worker starts."""

import asyncio
import base64
import hashlib
from types import SimpleNamespace
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
        assert arguments == {**task["args"], "repeat": 1}
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
        assert operation == "keyboard.chord" and arguments == {**task["args"], "repeat": 1}
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


@pytest.mark.parametrize(
    "literal", [" /resume go-go-go \r\n e\u0301 👩‍💻 ", "\ufeff" + "ä😀x" * 20000]
)
@pytest.mark.parametrize("submit", [False, True])
async def test_native_text_is_literal_and_does_not_touch_clipboard(bridge, literal, submit):
    task = setup_keyboard(bridge)
    task["operation"] = "keyboard.text"
    task["args"] = {
        "target": TARGET,
        "text": literal,
        "submit": submit,
    }
    bridge.clipboard.read = AsyncMock(
        side_effect=AssertionError("Native text must not read clipboard")
    )
    bridge.clipboard.write = AsyncMock(
        side_effect=AssertionError("Native text must not write clipboard")
    )
    receiver = staged_receiver(bridge, task)
    bridge.keyboard.transport.request = AsyncMock(side_effect=receiver)
    result = await bridge.execute(task, AsyncMock(), AsyncMock())
    assert result["text_verified"] is True
    assert receiver.manifest["submit"] is submit and result["return_posted"] is submit
    assert receiver.raw.decode("utf-16-le") == literal
    operations = [call.args[0] for call in bridge.keyboard.transport.request.await_args_list]
    assert operations[0] == "keyboard.text.begin" and operations[-1] == "keyboard.text.commit"
    assert operations.count("keyboard.text.commit") == 1
    assert "keyboard.text" not in SYSTEM_LEAVES
    assert not bridge.sessions.lock.locked()
    bridge.clipboard.read.assert_not_awaited()
    bridge.clipboard.write.assert_not_awaited()


@pytest.mark.parametrize("submit", [False, True])
async def test_text_return_receipt_must_match_bound_intent_without_replay(bridge, submit):
    task = setup_keyboard(bridge)
    task["operation"] = "keyboard.text"
    task["args"] = {"target": TARGET, "text": "literal", "submit": submit}
    receiver = staged_receiver(bridge, task)

    async def send(operation, arguments, **context):
        reply = await receiver(operation, arguments, **context)
        if operation == "keyboard.text.commit":
            reply["return_posted"] = not submit
        return reply

    bridge.keyboard.transport.request = AsyncMock(side_effect=send)
    with pytest.raises(UncertainExecution):
        await bridge.execute(task, AsyncMock(), AsyncMock())
    operations = [call.args[0] for call in bridge.keyboard.transport.request.await_args_list]
    assert operations.count("keyboard.text.commit") == 1 and "keyboard.text.abort" not in operations


def staged_receiver(bridge, task):
    from kirabridge.bridge_core.models import canonical
    from kirabridge.keyboard_text import native_frame_bytes

    async def receive(operation, arguments, *, principal, before_send=None):
        assert bridge.sessions.lock.locked() and principal == task["principal"]
        assert len(native_frame_bytes(operation, arguments, principal=principal)) <= 65536
        if before_send:
            before_send()
        identifier = arguments["transfer_id"]
        if operation == "keyboard.text.begin":
            binding = {
                k: v for k, v in arguments.items() if k not in {"transfer_id", "binding_json"}
            }
            assert arguments["binding_json"] == canonical(binding)
            assert hashlib.sha256(arguments["binding_json"].encode()).hexdigest() == identifier
            assert binding["target"] == TARGET and binding["task_id"] == task["id"]
            receive.manifest = arguments
            return {"transfer_id": identifier, "state": "accepted", "input_attempted": False}
        if operation == "keyboard.text.chunk":
            assert arguments["index"] == receive.chunks
            receive.raw += base64.b64decode(arguments["data_b64"], validate=True)
            receive.chunks += 1
            return {
                "transfer_id": identifier,
                "state": "received",
                "received_chunks": receive.chunks,
                "received_utf16_units": len(receive.raw) // 2,
                "input_attempted": False,
            }
        assert arguments == {"transfer_id": receive.manifest["transfer_id"]}
        if operation == "keyboard.text.abort":
            return {"transfer_id": identifier, "state": "aborted", "input_attempted": False}
        assert operation == "keyboard.text.commit"
        assert (
            hashlib.sha256(receive.raw.decode("utf-16-le").encode()).hexdigest()
            == receive.manifest["sha256"]
        )
        return {
            "transfer_id": identifier,
            "task_id": task["id"],
            "staging_verified": True,
            "text_verified": True,
            "selection_verified": True,
            "return_posted": receive.manifest["submit"],
            "text_sha256": receive.manifest["sha256"],
        }

    receive.raw, receive.chunks = b"", 0
    return receive


@pytest.mark.parametrize(
    "failure", ["bad_ack", "bad_counts", "chunk_error", "revoke", "commit_revoke"]
)
async def test_text_stage_failure_aborts_owned_buffer_without_commit(bridge, failure):
    task = setup_keyboard(bridge)
    task.update(operation="keyboard.text", args={"target": TARGET, "text": "literal"})
    receiver = staged_receiver(bridge, task)
    bridge.keyboard.transport.process = SimpleNamespace(returncode=None)

    async def send(operation, arguments, **context):
        if operation == "keyboard.text.commit" and failure == "commit_revoke":
            bridge.config.principals["local"].capabilities.remove("keyboard.execute")
            context["before_send"]()
            pytest.fail("Revoked commit cannot reach the native writer")
        if operation == "keyboard.text.chunk" and failure in {"chunk_error", "revoke"}:
            if failure == "revoke":
                bridge.config.principals["local"].capabilities.remove("keyboard.execute")
                context["before_send"]()
            raise BridgeError("test_stage_failure", "failed before commit")
        reply = await receiver(operation, arguments, **context)
        if operation == "keyboard.text.chunk":
            if failure == "bad_ack":
                reply["input_attempted"] = 0
            if failure == "bad_counts":
                reply["received_chunks"] = True
        return reply

    bridge.keyboard.transport.request = AsyncMock(side_effect=send)
    with pytest.raises(BridgeError):
        await bridge.execute(task, AsyncMock(), AsyncMock())
    operations = [call.args[0] for call in bridge.keyboard.transport.request.await_args_list]
    expected = ["keyboard.text.begin", "keyboard.text.chunk"]
    if failure == "commit_revoke":
        expected.append("keyboard.text.commit")
    assert operations == [*expected, "keyboard.text.abort"]
    assert not bridge.sessions.lock.locked()
    bridge.keyboard.transport.process = None


@pytest.mark.parametrize("failure", ["lost", "invalid_receipt"])
async def test_text_commit_uncertainty_is_never_replayed_or_aborted(bridge, failure):
    task = setup_keyboard(bridge)
    task.update(operation="keyboard.text", args={"target": TARGET, "text": "literal"})
    receiver = staged_receiver(bridge, task)

    async def send(operation, arguments, **context):
        reply = await receiver(operation, arguments, **context)
        if operation == "keyboard.text.commit":
            if failure == "lost":
                raise UncertainExecution("lost", "unknown after commit")
            reply["text_sha256"] = "0" * 64
        return reply

    bridge.keyboard.transport.request = AsyncMock(side_effect=send)
    with pytest.raises(UncertainExecution):
        await bridge.execute(task, AsyncMock(), AsyncMock())
    operations = [call.args[0] for call in bridge.keyboard.transport.request.await_args_list]
    assert operations == ["keyboard.text.begin", "keyboard.text.chunk", "keyboard.text.commit"]


def test_private_staging_operations_are_not_public_inputs():
    from kirabridge.bridge_core.bridge import INPUTS

    for suffix in ("begin", "chunk", "commit", "abort"):
        assert "keyboard.text." + suffix not in INPUTS
        assert "keyboard.text." + suffix not in OPERATIONS
