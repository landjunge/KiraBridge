"""macOS mouse effects: typed bounds, session-lock binding, fail-closed native gate."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from macos_provider_fixture import bind_macos_provider
from pydantic import ValidationError

from kirabridge.bridge_core.models import BridgeError
from kirabridge.desktop_input import DESKTOP_EFFECT_OPERATIONS
from kirabridge.mcp_gateway.server import inline_task_timeout
from kirabridge.operations import OPERATIONS
from kirabridge.platform_adapters.macos.control_models import (
    MouseClickInput,
    MouseMoveInput,
    MouseScrollInput,
)
from kirabridge.system_operations import (
    SYSTEM_LEAVES,
    SYSTEM_PERMISSIONS,
    SYSTEM_READ_OPERATIONS,
)

MOUSE_OPERATIONS = ("mouse.move", "mouse.click", "mouse.scroll")
ARGS = {
    "mouse.move": {"x": 120.5, "y": 80},
    "mouse.click": {"x": 120, "y": 80, "button": "right"},
    "mouse.scroll": {"dx": -2, "dy": 0},
}


def native(bridge, *, mouse_protocol=1):
    bind_macos_provider(bridge)
    probe = bridge.macos.capability_probe
    probe.facts.update(platform="darwin", os_version="15.7.4")
    metadata = {"available": True, "revision": "fixture-v1", "keyboard_protocol": 1}
    if mouse_protocol is not None:
        metadata["mouse_protocol"] = mouse_protocol
    probe.native_metadata = lambda: metadata
    bridge.system_modules.execute = AsyncMock(return_value={"effect": "fixture_only"})


def task(operation):
    return {
        "id": "owned-mouse-test",
        "principal": "local",
        "operation": operation,
        "args": ARGS[operation],
    }


@pytest.mark.parametrize("operation", MOUSE_OPERATIONS)
def test_mouse_operations_are_bounded_desktop_effects(operation):
    assert operation in DESKTOP_EFFECT_OPERATIONS
    assert SYSTEM_LEAVES[operation] == "mouse"
    assert operation not in SYSTEM_READ_OPERATIONS
    assert OPERATIONS[operation].effect == "write"
    assert SYSTEM_PERMISSIONS[operation] == "accessibility"
    assert inline_task_timeout(operation) == 13


@pytest.mark.parametrize(
    "model,payload",
    [
        (MouseMoveInput, {"x": 1, "y": 2}),
        (MouseMoveInput, {"x": -100000, "y": 100000.0}),
        (MouseClickInput, {"x": 0, "y": 0}),
        (MouseClickInput, {"x": 0, "y": 0, "button": "right"}),
        (MouseScrollInput, {"dy": -3}),
        (MouseScrollInput, {"dx": 1000, "dy": -1000}),
    ],
)
def test_mouse_models_accept_bounded_coordinates_and_deltas(model, payload):
    assert model.model_validate(payload)


def test_mouse_click_defaults_to_left_button():
    assert MouseClickInput.model_validate({"x": 0, "y": 0}).button == "left"


@pytest.mark.parametrize(
    "model,payload",
    [
        (MouseMoveInput, {"x": 1}),
        (MouseMoveInput, {"x": True, "y": 2}),
        (MouseMoveInput, {"x": "1", "y": 2}),
        (MouseMoveInput, {"x": float("inf"), "y": 2}),
        (MouseMoveInput, {"x": 1, "y": float("nan")}),
        (MouseMoveInput, {"x": 100001, "y": 2}),
        (MouseMoveInput, {"x": 1, "y": -100001}),
        (MouseMoveInput, {"x": 1, "y": 2, "z": 3}),
        (MouseClickInput, {"x": 1, "y": 2, "button": "middle"}),
        (MouseClickInput, {"x": 1, "y": 2, "button": True}),
        (MouseScrollInput, {}),
        (MouseScrollInput, {"dx": 0, "dy": 0}),
        (MouseScrollInput, {"dx": 1001}),
        (MouseScrollInput, {"dy": -1001}),
        (MouseScrollInput, {"dx": 1.5}),
        (MouseScrollInput, {"dx": True}),
    ],
)
def test_mouse_models_reject_unbounded_or_untyped_input(model, payload):
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("operation", MOUSE_OPERATIONS)
async def test_mouse_effects_wait_for_session_lock_while_reads_stay_available(bridge, operation):
    native(bridge)
    observed = []

    async def running(evidence):
        observed.append(evidence["operation"])

    assert bridge.desktop_input.lock is bridge.sessions.lock
    async with bridge.sessions.lock:
        effect = asyncio.create_task(bridge.execute(task(operation), running, running))
        await asyncio.sleep(0)
        assert not effect.done() and not observed
        await asyncio.wait_for(
            bridge.execute(
                {
                    "id": "owned-mouse-read",
                    "principal": "local",
                    "operation": "keyboard.inspect",
                    "args": {"pid": 222, "expected_started_at": 123.0},
                },
                running,
                running,
            ),
            1,
        )
        assert observed == ["keyboard.inspect"]
    await effect
    assert observed == ["keyboard.inspect", operation]
    invocation = bridge.system_modules.execute.await_args
    assert invocation.args[0] == operation


@pytest.mark.parametrize("operation", MOUSE_OPERATIONS)
async def test_mouse_lock_timeout_does_not_dispatch_or_mark_running(bridge, operation):
    native(bridge)
    bridge.desktop_input.timeout = 0.01
    running = AsyncMock()
    async with bridge.sessions.lock:
        with pytest.raises(BridgeError) as caught:
            await bridge.execute(task(operation), running, running)
    assert caught.value.code == "desktop_input_busy"
    running.assert_not_awaited()
    bridge.system_modules.execute.assert_not_awaited()


@pytest.mark.parametrize("operation", MOUSE_OPERATIONS)
async def test_mouse_without_advertised_native_contract_stays_unavailable(bridge, operation):
    native(bridge, mouse_protocol=None)
    with pytest.raises(BridgeError) as caught:
        await bridge.execute(task(operation), AsyncMock(), AsyncMock())
    assert caught.value.code == "macos_capability_unavailable"
    bridge.system_modules.execute.assert_not_awaited()


async def test_mouse_effect_evidence_marks_attempt_without_retry(bridge):
    native(bridge)
    events = []

    async def running(evidence):
        events.append(evidence)

    result = await bridge.execute(task("mouse.click"), running, running)
    assert result == {"effect": "fixture_only"}
    assert events[0]["evidence_type"] == "native_system_operation"
    assert events[0]["effect_attempted"] is True
    assert events[0]["automatic_retry"] is False
