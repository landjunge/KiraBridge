"""Independent direct-input boundary checks; no native worker or GUI is started."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.desktop_input import DesktopInput
from kirabridge.keyboard_manager import KeyboardManager
from kirabridge.keyboard_models import KeyboardInput

APP = {
    "pid": 321,
    "started_at": 1700000000.125,
    "bundle_id": "example.review.editor",
    "name": "Review Editor",
    "active": True,
}
TARGET = {
    "pid": APP["pid"],
    "expected_started_at": APP["started_at"],
    "target_token": "a" * 32,
    "helper_pid": 123,
    "worker_generation": "12345678-1234-1234-1234-123456789012",
    "expected_revision": "b" * 64,
}


def inspection():
    return {
        "target": deepcopy(TARGET),
        "application": deepcopy(APP),
        "window_token": "c" * 32,
        "field": {
            "role": "AXTextArea",
            "subrole": "",
            "enabled": True,
            "focused": True,
            "secure": False,
            "value_sha256": "d" * 64,
            "selection_utf16": {"location": 0, "length": 0},
        },
        "permissions": {"accessibility": True, "post_events": True},
        "supported": True,
        "input_attempted": False,
    }


def make_manager(send, authorize=lambda *_: None):
    return KeyboardManager(
        transport=SimpleNamespace(request=AsyncMock(side_effect=send)),
        desktop_input=DesktopInput(asyncio.Lock()),
        authorize=authorize,
    )


async def execute(manager, **arguments):
    return await manager.execute(
        {"id": "independent-keyboard-input", "principal": "review", "operation": "keyboard.input"},
        KeyboardInput(**arguments),
        AsyncMock(),
        AsyncMock(),
    )


async def test_duplicate_exact_application_names_never_send_input():
    effects = []

    async def send(operation, arguments, *, principal, before_send=None):
        if before_send:
            before_send()
        if operation == "apps.list":
            other = {**APP, "pid": 322, "bundle_id": "example.review.other"}
            return {"applications": [deepcopy(APP), other], "truncated": False}
        effects.append(operation)
        pytest.fail("Ambiguous application must stop before focus or keyboard dispatch")

    manager = make_manager(send)
    with pytest.raises(BridgeError):
        await execute(manager, app=APP["name"], key={"named": "enter"})
    assert effects == []


@pytest.mark.parametrize("changed", ["field", "window", "generation"])
async def test_repeat_does_not_follow_a_new_target_after_first_dispatch(changed):
    posts = []
    changed_observations = []

    async def send(operation, arguments, *, principal, before_send=None):
        if before_send:
            before_send()
        if operation == "apps.list":
            return {"applications": [deepcopy(APP)], "truncated": False}
        if operation == "keyboard.inspect":
            result = inspection()
            if posts:
                changed_observations.append(changed)
                result["target"]["expected_revision"] = "e" * 64
                if changed == "field":
                    result["target"]["target_token"] = "f" * 32
                elif changed == "window":
                    result["window_token"] = "f" * 32
                else:
                    result["target"]["worker_generation"] = "87654321-4321-4321-4321-210987654321"
            return result
        if operation == "keyboard.key":
            posts.append(deepcopy(arguments))
            return {
                "post_calls_returned": 2,
                "input_attempted": True,
                "app_processing_confirmed": False,
            }
        pytest.fail(f"Unexpected operation {operation}")

    manager = make_manager(send)
    with pytest.raises(UncertainExecution):
        await execute(manager, key={"named": "enter"}, repeat=2)
    assert len(posts) == 1
    assert changed_observations
    assert not manager.desktop_input.lock.locked()


async def test_unknown_first_pair_never_dispatches_the_second():
    posts = []

    async def send(operation, arguments, *, principal, before_send=None):
        if before_send:
            before_send()
        if operation == "apps.list":
            return {"applications": [deepcopy(APP)], "truncated": False}
        if operation == "keyboard.inspect":
            return inspection()
        if operation == "keyboard.key":
            posts.append(operation)
            raise UncertainExecution("keyboard_input_unknown", "Lost native receipt")
        pytest.fail(f"Unexpected operation {operation}")

    manager = make_manager(send)
    with pytest.raises(UncertainExecution):
        await execute(manager, key={"named": "enter"}, repeat=2)
    assert posts == ["keyboard.key"]
    assert not manager.desktop_input.lock.locked()


async def test_permission_revoked_at_send_is_not_a_keyboard_attempt():
    revoked = False
    posts = []

    def authorize(principal, operation):
        if revoked:
            raise BridgeError("permission_denied", "Permission changed before dispatch")

    async def send(operation, arguments, *, principal, before_send=None):
        nonlocal revoked
        if operation == "keyboard.key":
            revoked = True
        if before_send:
            before_send()
        if operation == "apps.list":
            return {"applications": [deepcopy(APP)], "truncated": False}
        if operation == "keyboard.inspect":
            return inspection()
        posts.append(operation)
        pytest.fail("Permission revocation must precede a native post")

    manager = make_manager(send, authorize)
    with pytest.raises(BridgeError) as error:
        await execute(manager, key={"named": "enter"})
    assert not isinstance(error.value, UncertainExecution)
    assert posts == []
    assert not manager.desktop_input.lock.locked()


async def test_incomplete_pair_receipt_never_counts_as_completed_repeat():
    posts = []

    async def send(operation, arguments, *, principal, before_send=None):
        if before_send:
            before_send()
        if operation == "apps.list":
            return {"applications": [deepcopy(APP)], "truncated": False}
        if operation == "keyboard.inspect":
            return inspection()
        if operation == "keyboard.key":
            posts.append(operation)
            return {
                "post_calls_returned": 1,
                "input_attempted": True,
                "app_processing_confirmed": False,
            }
        pytest.fail(f"Unexpected operation {operation}")

    manager = make_manager(send)
    with pytest.raises(UncertainExecution):
        await execute(manager, key={"named": "enter"}, repeat=2)
    assert posts == ["keyboard.key"]
