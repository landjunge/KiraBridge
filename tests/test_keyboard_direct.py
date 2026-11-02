"""Profile-free public intents reuse the existing native transaction, no real UI."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from kirabridge.bridge_core.bridge import INPUTS
from kirabridge.bridge_core.models import BridgeError
from kirabridge.keyboard_models import KeyboardInput
from kirabridge.operations import OPERATIONS

APP = {
    "pid": 321,
    "started_at": 1700000000.125,
    "bundle_id": "com.example.Note",
    "name": "Test Notes",
    "active": True,
}
TARGET = {
    "pid": 321,
    "expected_started_at": 1700000000.125,
    "target_token": "a" * 32,
    "helper_pid": 123,
    "worker_generation": "12345678-1234-1234-1234-123456789012",
    "expected_revision": "b" * 64,
}
SNAPSHOT = {"target": TARGET, "window_token": "c" * 32, "field": {"role": "AXTextArea"}}


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"text": "x", "key": {"named": "enter"}},
        {"key": {"named": "enter"}, "submit": True},
        {"text": "x", "modifiers": ["command"]},
        {"key": {"character": "z"}, "modifiers": ["command", "command"]},
        {"text": "x", "repeat": True},
        {"text": "x", "repeat": 21},
        {"text": "x" * 100000, "repeat": 20},
        {"text": "x", "app": " Notes "},
    ],
)
def test_direct_contract_refuses_mixed_or_unbounded_intents(args):
    with pytest.raises(ValidationError):
        KeyboardInput(**args)


def ready(bridge, arguments):
    bridge.config.principals["local"].capabilities.append("keyboard.execute")
    bridge.macos.capability_probe.facts.update(platform="darwin", os_version="15.7.4")
    bridge.macos.capability_probe.native_metadata = lambda: {
        "available": True,
        "keyboard_protocol": 1,
    }
    return {
        "id": "own-direct-1",
        "principal": "local",
        "operation": "keyboard.input",
        "args": arguments,
    }


async def test_direct_two_returns_resolves_once_and_refreshes_exact_field(bridge):
    task = ready(bridge, {"key": {"named": "enter"}, "repeat": 2})
    calls, snapshots = [], []

    async def send(operation, arguments, *, principal, before_send):
        assert principal == "local" and bridge.sessions.lock.locked()
        before_send()
        calls.append((operation, arguments))
        if operation == "apps.list":
            return {"applications": [APP], "truncated": False}
        if operation == "keyboard.inspect":
            current = deepcopy(SNAPSHOT)
            current["target"]["expected_revision"] = str(len(snapshots)) * 64
            current["field"]["observed_count"] = len(snapshots)
            snapshots.append(current)
            return current
        assert operation == "keyboard.key"
        return {
            "post_calls_returned": 2,
            "input_attempted": True,
            "app_processing_confirmed": False,
        }

    bridge.keyboard.transport.request = AsyncMock(side_effect=send)
    progress = AsyncMock()
    result = await bridge.execute(task, AsyncMock(), progress)
    assert [op for op, _ in calls] == [
        "apps.list",
        "keyboard.inspect",
        "keyboard.key",
        "keyboard.inspect",
        "keyboard.key",
        "keyboard.inspect",
    ]
    assert result["completed_count"] == result["requested_count"] == 2
    assert result["post_calls_returned"] == 4
    assert result["profile_required"] is False
    assert result["app_processing_confirmed"] is False
    assert result["field_change_observed"] is True
    assert calls[2][1]["target"]["expected_revision"] != calls[4][1]["target"]["expected_revision"]
    assert progress.await_count == 2
    assert not bridge.sessions.lock.locked()
    assert OPERATIONS["keyboard.input"].capability == "keyboard.execute"
    assert INPUTS["keyboard.input"] is KeyboardInput


async def test_named_app_activates_once_and_waits_for_observed_focus(bridge):
    task = ready(bridge, {"app": "com.example.Note", "key": {"named": "space"}})
    calls, observations = [], 0

    async def send(operation, arguments, *, principal, before_send):
        nonlocal observations
        before_send()
        calls.append(operation)
        if operation == "apps.list":
            return {"applications": [{**APP, "active": False}], "truncated": False}
        if operation == "keyboard.inspect":
            observations += 1
            if observations <= 2:
                raise BridgeError(
                    "keyboard_not_frontmost", "Native system operation refused or failed"
                )
            return deepcopy(SNAPSHOT)
        if operation == "app.focus":
            assert arguments == {"expected_pid": 321, "expected_start": "1700000000.125000"}
            return {"active_observed": False}
        assert operation == "keyboard.key"
        return {"post_calls_returned": 2, "input_attempted": True}

    bridge.keyboard.transport.request = AsyncMock(side_effect=send)
    result = await bridge.execute(task, AsyncMock(), AsyncMock())
    assert result["completed_count"] == 1
    assert calls.count("app.focus") == 1
    assert calls.index("keyboard.key") > calls.index("app.focus")


async def test_literal_copies_share_one_staged_payload_and_final_submit(bridge):
    task = ready(bridge, {"text": " ä\n", "repeat": 2, "submit": True})

    async def send(operation, arguments, *, principal, before_send):
        before_send()
        if operation == "apps.list":
            return {"applications": [APP], "truncated": False}
        assert operation == "keyboard.inspect"
        return deepcopy(SNAPSHOT)

    async def text(task, plan, begin, turn, progress, *, authorization_operation):
        assert authorization_operation == "keyboard.input"
        assert plan.manifest["utf8_bytes"] == len(" ä\n ä\n".encode())
        assert plan.manifest["submit"] is True
        return {
            "text_verified": True,
            "selection_verified": True,
            "input_attempted": True,
            "post_calls_returned": 8,
            "return_posted": True,
        }

    bridge.keyboard.transport.request = AsyncMock(side_effect=send)
    bridge.keyboard._text = AsyncMock(side_effect=text)
    result = await bridge.execute(task, AsyncMock(), AsyncMock())
    assert result["completed_count"] == 2 and result["text_verified"] is True
    bridge.keyboard._text.assert_awaited_once()
