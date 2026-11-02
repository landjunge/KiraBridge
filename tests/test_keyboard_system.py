"""Real Core routing of automatic/system intents; no real desktop effects here."""

import pytest
from pydantic import ValidationError
from test_keyboard_control import APP, TARGET

from kirabridge.bridge_core.models import TaskRequest, UncertainExecution
from kirabridge.keyboard_control import KeyboardControlInput
from kirabridge.keyboard_system import KeyboardSystemKeyInput, system_receipt_verified


def setup_system(bridge, config, *, enabled=True, receipt=True):
    config.principals["local"].capabilities += [
        "keyboard.inspect",
        "keyboard.execute",
        "apps.list",
        "app.focus",
    ]
    calls = []

    async def native(operation, args, *, before_send, **kwargs):
        assert bridge.sessions.lock.locked()
        before_send()
        calls.append((operation, args))
        if operation == "apps.list":
            return {"applications": [APP], "eof": True}
        if operation == "keyboard.system_inventory":
            return {
                "actions": [
                    {"action": "volume_up", "available": True, "key": None},
                    {
                        "action": "space_left",
                        "available": enabled,
                        "key": {"key_code": 123},
                        "modifiers": ["control", "fn"],
                    },
                ]
            }
        if operation == "keyboard.inspect":
            return {"target": TARGET, "application": APP}
        return {"post_calls_returned": 2 * args.get("repeat", 1)} if receipt else {}

    bridge.keyboard.transport.request = native
    return calls


async def execute(bridge, value):
    request = TaskRequest(
        task_id="system-control",
        idempotency_key="system-control",
        operation="keyboard.control",
        arguments=value,
    )
    task = bridge.prepare("local", request)

    async def running(evidence):
        pass

    return await bridge.execute(task, running, running)


@pytest.mark.parametrize("key", [{"named": "left"}, {"key_code": 123}])
async def test_configured_control_arrow_reaches_system_without_text_inspection(bridge, config, key):
    calls = setup_system(bridge, config)
    result = await execute(bridge, {"key": key, "modifiers": ["control"]})
    assert result["native_operation"] == "keyboard.system_key"
    assert [op for op, _ in calls] == [
        "apps.list",
        "keyboard.system_inventory",
        "keyboard.system_key",
    ]
    assert calls[-1][1]["action"] == "space_left"


async def test_explicit_app_scope_keeps_control_arrow_in_target_program(bridge, config):
    calls = setup_system(bridge, config)
    result = await execute(
        bridge, {"scope": "app", "key": {"named": "left"}, "modifiers": ["control"]}
    )
    assert result["native_operation"] == "keyboard.chord"
    assert "keyboard.system_inventory" not in [op for op, _ in calls]


async def test_disabled_system_shortcut_is_never_guessed(bridge, config):
    calls = setup_system(bridge, config, enabled=False)
    result = await execute(bridge, {"key": {"named": "left"}, "modifiers": ["control"]})
    assert result["native_operation"] == "keyboard.chord"
    assert "keyboard.system_key" not in [op for op, _ in calls]


async def test_explicit_fn_is_not_reinterpreted_as_an_unmodified_system_shortcut(bridge, config):
    calls = setup_system(bridge, config)
    result = await execute(bridge, {"key": {"named": "left"}, "modifiers": ["control", "fn"]})
    assert result["native_operation"] == "keyboard.chord"
    assert calls[-1][1]["modifiers"] == ["control", "fn"]
    assert "keyboard.system_key" not in [op for op, _ in calls]


async def test_system_action_needs_no_text_field_and_preserves_repeat(bridge, config):
    calls = setup_system(bridge, config)
    result = await execute(bridge, {"scope": "system", "action": "volume_up", "repeat": 3})
    assert result["post_calls_returned"] == 6
    assert [op for op, _ in calls] == ["apps.list", "keyboard.system_key"]
    assert calls[-1][1]["repeat"] == 3


async def test_missing_system_receipt_is_unknown_and_never_replayed(bridge, config):
    calls = setup_system(bridge, config, receipt=False)
    with pytest.raises(UncertainExecution):
        await execute(bridge, {"scope": "system", "action": "brightness_down"})
    assert sum(op == "keyboard.system_key" for op, _ in calls) == 1


@pytest.mark.parametrize("value", [0, 21, True, 1.5, "2"])
def test_repetition_requires_a_bounded_explicit_integer(value):
    with pytest.raises(ValidationError):
        KeyboardControlInput(scope="system", action="volume_up", repeat=value)


def test_system_scope_does_not_accept_text_or_ambiguous_intents():
    for data in [
        {"scope": "system", "text": "do not type"},
        {"scope": "app", "action": "volume_up"},
        {"scope": "system", "action": "volume_up", "key": {"named": "f1"}},
    ]:
        with pytest.raises(ValidationError):
            KeyboardControlInput(**data)
    with pytest.raises(ValidationError):
        KeyboardSystemKeyInput(
            scope="system",
            target={"pid": 1, "expected_started_at": 1},
            action="space_left",
            modifiers=["shift"],
        )


@pytest.mark.parametrize("action", ["volume_up", "brightness_down", "play_pause"])
async def test_hardware_action_preserves_explicit_fine_step_modifiers(bridge, config, action):
    calls = setup_system(bridge, config)
    await execute(
        bridge,
        {"scope": "system", "action": action, "modifiers": ["option", "shift"]},
    )
    assert calls[-1][1]["modifiers"] == ["option", "shift"]
    assert calls[-1][1]["action"] == action
    assert [op for op, _ in calls] == ["apps.list", "keyboard.system_key"]


def test_caps_lock_needs_state_readback_parity_not_invented_event_posts():
    receipt = {
        "scope": "native_state_readback",
        "event_scope": "system",
        "modifier": "caps_lock",
        "resolved": {"route": "modifier_lock_state", "action": "caps_lock"},
        "effect_verified": True,
        "system_processing_confirmed": True,
        "requested_repeat": 2,
        "completed_repeat": 2,
        "state_set_calls_returned": 2,
        "post_calls_returned": 0,
        "state_before": False,
        "state_after": False,
    }
    assert system_receipt_verified(receipt, action="caps_lock", repeat=2)
    for changed in [
        {"effect_verified": False},
        {"state_after": True},
        {"state_set_calls_returned": 1},
        {"post_calls_returned": 4},
        {"requested_repeat": 1},
        {"state_before": 0},
    ]:
        assert not system_receipt_verified({**receipt, **changed}, action="caps_lock", repeat=2)
