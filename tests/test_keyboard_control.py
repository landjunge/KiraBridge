"""Automatic target resolution through the real Core; only native transport is fake."""

import asyncio
import base64
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from kirabridge import keyboard_control as control_module
from kirabridge.bridge_core.models import BridgeError, TaskRequest, UncertainExecution
from kirabridge.keyboard_control import KeyboardControlInput

APP = {
    "pid": 321,
    "started_at": 1700000000.125,
    "bundle_id": "org.example.Editor",
    "name": "Editor",
    "app_path": "/Applications/Editor.app",
    "executable": "/app/editor",
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


def setup(bridge, config, *, active=True):
    config.principals["local"].capabilities += ["keyboard.execute"]
    app = {**APP, "active": active}
    calls, state = [], {"chunks": 0, "units": 0}

    async def native(operation, arguments, *, before_send, **kwargs):
        assert bridge.sessions.lock.locked()
        before_send()
        calls.append((operation, arguments))
        if operation == "apps.list":
            return {"applications": [app], "eof": True}
        if operation == "app.focus":
            return {"active_observed": True}
        if operation == "keyboard.inspect":
            return {"target": TARGET, "application": app}
        if operation == "keyboard.text.begin":
            state.update(arguments)
            return {
                "transfer_id": state["transfer_id"],
                "state": "accepted",
                "input_attempted": False,
            }
        if operation == "keyboard.text.chunk":
            state["chunks"] += 1
            state["units"] += len(base64.b64decode(arguments["data_b64"])) // 2
            return {
                "transfer_id": state["transfer_id"],
                "state": "received",
                "input_attempted": False,
                "received_chunks": state["chunks"],
                "received_utf16_units": state["units"],
            }
        if operation == "keyboard.text.commit":
            return {
                "transfer_id": state["transfer_id"],
                "task_id": "control",
                "staging_verified": True,
                "text_verified": True,
                "selection_verified": True,
                "return_posted": state["submit"],
                "text_sha256": state["sha256"],
            }
        assert operation in {"keyboard.key", "keyboard.chord"}
        return {"post_calls_returned": 2, "app_processing_confirmed": False}

    bridge.keyboard.transport.request = AsyncMock(side_effect=native)
    return calls, app, native


async def execute(bridge, arguments):
    return await bridge.execute(
        {"id": "control", "principal": "local", "operation": "keyboard.control", "args": arguments},
        AsyncMock(),
        AsyncMock(),
    )


@pytest.mark.parametrize(
    "selector",
    [
        {},
        {"app": "editor"},
        {"app": APP["bundle_id"]},
        {"pid": 321, "expected_started_at": APP["started_at"]},
    ],
)
async def test_automatic_selection_without_profile_or_nested_lock(bridge, config, selector):
    calls, _, _ = setup(bridge, config)
    result = await execute(bridge, {**selector, "key": {"named": "escape"}})
    assert result["automatic_target"] and result["resolved_application"]["pid"] == 321
    assert [op for op, _ in calls] == ["apps.list", "keyboard.inspect", "keyboard.key"]
    assert not bridge.sessions.lock.locked()


async def test_named_inactive_program_gets_exactly_one_focus(bridge, config):
    calls, _, _ = setup(bridge, config, active=False)
    await execute(bridge, {"app": "Editor", "key": {"character": "a"}, "modifiers": ["command"]})
    assert [op for op, _ in calls] == [
        "apps.list",
        "app.focus",
        "keyboard.inspect",
        "keyboard.chord",
    ]
    assert calls[1][1] == {"expected_pid": 321, "expected_start": "1700000000.125000"}


async def test_focus_observation_waits_for_activation_without_replay(bridge, config, monkeypatch):
    calls, app, native = setup(bridge, config, active=False)
    monkeypatch.setattr(control_module, "_FOCUS_OBSERVATION_INTERVAL", 0.001)
    observed_reads, authorized = 0, []
    original_authorize = bridge.keyboard.authorize

    def authorize(principal, operation):
        authorized.append(operation)
        return original_authorize(principal, operation)

    bridge.keyboard.authorize = authorize

    async def delayed(op, args, **kwargs):
        nonlocal observed_reads
        result = await native(op, args, **kwargs)
        if op == "app.focus":
            return {"active_observed": False}
        if op == "apps.list":
            observed_reads += 1
            if observed_reads == 3:
                app["active"] = True
        return result

    bridge.keyboard.transport.request.side_effect = delayed
    result = await execute(bridge, {"app": "Editor", "key": {"named": "escape"}})
    assert [op for op, _ in calls] == [
        "apps.list", "app.focus", "apps.list", "apps.list", "keyboard.inspect", "keyboard.key"
    ]
    assert authorized.count("apps.list") == 2 * observed_reads
    assert result["resolved_application"]["active"] is True
    assert result["automatic_retry"] is False
    assert not bridge.sessions.lock.locked()


@pytest.mark.parametrize(
    "change",
    [
        "pid", "started_at", "bundle_id", "app_path", "executable",
        "duplicate", "missing", "incomplete",
    ],
)
async def test_focus_observation_refuses_changed_identity(bridge, config, monkeypatch, change):
    calls, app, native = setup(bridge, config, active=False)
    monkeypatch.setattr(control_module, "_FOCUS_OBSERVATION_INTERVAL", 0.001)
    observed_reads = 0

    async def changed(op, args, **kwargs):
        nonlocal observed_reads
        result = await native(op, args, **kwargs)
        if op == "app.focus":
            return {"active_observed": False}
        if op == "apps.list":
            observed_reads += 1
            if observed_reads > 1:
                current = {**app, "active": True}
                if change in {"pid", "started_at"}:
                    current[change] += 1
                elif change in {"bundle_id", "app_path", "executable"}:
                    current[change] += ".changed"
                result = {"applications": [current], "eof": True}
                if change == "duplicate":
                    result["applications"].append(dict(current))
                elif change == "missing":
                    result["applications"] = []
                elif change == "incomplete":
                    result["eof"] = False
        return result

    bridge.keyboard.transport.request.side_effect = changed
    with pytest.raises(BridgeError) as error:
        await execute(bridge, {"app": "Editor", "key": {"named": "escape"}})
    assert error.value.code == (
        "keyboard_catalog_incomplete" if change == "incomplete" else "keyboard_application_changed"
    )
    assert [op for op, _ in calls] == ["apps.list", "app.focus", "apps.list"]
    assert not bridge.sessions.lock.locked()


async def test_focus_observation_timeout_bounds_stalled_read(bridge, config, monkeypatch):
    calls, _, native = setup(bridge, config, active=False)
    monkeypatch.setattr(control_module, "_FOCUS_OBSERVATION_TIMEOUT", 0.02)
    monkeypatch.setattr(control_module, "_FOCUS_OBSERVATION_INTERVAL", 0.001)
    observed_reads = 0

    async def stalled(op, args, **kwargs):
        nonlocal observed_reads
        result = await native(op, args, **kwargs)
        if op == "app.focus":
            return {"active_observed": False}
        if op == "apps.list":
            observed_reads += 1
            if observed_reads > 1:
                await asyncio.Event().wait()
        return result

    bridge.keyboard.transport.request.side_effect = stalled
    with pytest.raises(BridgeError) as error:
        await execute(bridge, {"app": "Editor", "text": "never sent", "submit": True})
    assert error.value.code == "keyboard_focus_unconfirmed"
    assert [op for op, _ in calls] == ["apps.list", "app.focus", "apps.list"]
    assert not bridge.sessions.lock.locked()


@pytest.mark.parametrize("submit", [False, True])
async def test_text_reuses_staging_and_authorization_callback_without_recursion(
    bridge, config, submit
):
    calls, _, _ = setup(bridge, config)
    result = await execute(
        bridge, {"app": "Editor", "text": "\ufeffä😀\n" * 9000, "submit": submit}
    )
    assert result["text_verified"] and result["return_posted"] is submit
    assert sum(op == "keyboard.text.commit" for op, _ in calls) == 1
    assert sum(op == "keyboard.text.chunk" for op, _ in calls) > 1
    assert not any(op.startswith("clipboard") for op, _ in calls)


@pytest.mark.parametrize(
    "change,code",
    [
        ("stale", "keyboard_application_unavailable"),
        ("ambiguous", "keyboard_application_ambiguous"),
        ("changed", "keyboard_application_changed"),
    ],
)
async def test_ambiguous_stale_or_changed_target_never_sends_keys(bridge, config, change, code):
    calls, app, native = setup(bridge, config)

    async def altered(op, args, **kwargs):
        result = await native(op, args, **kwargs)
        if change == "ambiguous" and op == "apps.list":
            result["applications"].append({**app, "pid": 999})
        if change == "changed" and op == "keyboard.inspect":
            result["application"] = {**app, "bundle_id": "org.example.Other"}
        return result

    bridge.keyboard.transport.request.side_effect = altered
    arguments = {"app": "Editor", "key": {"named": "enter"}}
    if change == "stale":
        arguments = {"pid": 321, "expected_started_at": 1, "key": {"named": "enter"}}
    with pytest.raises(BridgeError) as error:
        await execute(bridge, arguments)
    assert error.value.code == code
    assert not any(
        op in {"keyboard.key", "keyboard.chord", "keyboard.text.commit"} for op, _ in calls
    )


async def test_lost_key_reply_is_not_replayed(bridge, config):
    calls, _, native = setup(bridge, config)

    async def lost(op, args, **kwargs):
        result = await native(op, args, **kwargs)
        if op == "keyboard.key":
            raise UncertainExecution("keyboard_unknown", "reply lost")
        return result

    bridge.keyboard.transport.request.side_effect = lost
    with pytest.raises(UncertainExecution):
        await execute(bridge, {"key": {"named": "escape"}})
    assert sum(op == "keyboard.key" for op, _ in calls) == 1


async def test_revoked_control_dependency_blocks_commit(bridge, config):
    calls, _, native = setup(bridge, config)

    async def revoke(op, args, **kwargs):
        if op == "keyboard.text.commit":
            config.principals["local"].capabilities.remove("app.focus")
        return await native(op, args, **kwargs)

    bridge.keyboard.transport.request.side_effect = revoke
    with pytest.raises(BridgeError):
        await execute(bridge, {"text": "native", "submit": True})
    assert not any(op == "keyboard.text.commit" for op, _ in calls)


async def test_real_task_lifecycle_enters_running_only_once(bridge, config):
    calls, _, _ = setup(bridge, config)
    bridge.tasks.preflight = None  # Only the native technical probe is synthetic.
    request = TaskRequest(
        task_id="control",
        idempotency_key="control",
        operation="keyboard.control",
        arguments={"app": "Editor", "text": "native", "submit": True},
    )
    created = bridge.prepare("local", request)
    assert created["state"] == "created"
    bridge.tasks.approve("control")
    claimed = bridge.store.claim_exact(bridge.tasks.owner, config.lease_seconds, "control")
    await bridge.tasks._execute(claimed)
    result = bridge.task("local", "control")
    assert result["state"] == "completed", result
    assert result["result"]["automatic_target"] is True
    events = bridge.events("local", "control")["events"]
    # Progress entries also carry state=running; they are not transitions.
    assert (
        sum(e["evidence"].get("evidence_type") == "automatic_keyboard_resolution" for e in events)
        == 1
    )
    assert sum(e["evidence"].get("evidence_type") == "native_keyboard_attempt" for e in events) == 1
    assert sum(op == "keyboard.text.commit" for op, _ in calls) == 1


@pytest.mark.parametrize(
    "invalid",
    [
        {"text": "x", "key": {"named": "enter"}},
        {"key": {"named": "tab"}, "submit": True},
        {"text": "x", "modifiers": ["command"]},
        {"pid": 1, "text": "x"},
    ],
)
def test_invalid_intents_refuse_before_runtime(invalid):
    with pytest.raises(ValidationError):
        KeyboardControlInput.model_validate(invalid)
