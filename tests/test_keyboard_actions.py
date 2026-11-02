"""Revision-bound profile actions through Core; no native worker, input or GUI."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from kirabridge import keyboard_profiles
from kirabridge.bridge_core.models import BridgeError, TaskRequest, UncertainExecution
from kirabridge.keyboard_models import KeyboardActionInput
from kirabridge.keyboard_profiles import KeyboardProfileStore
from kirabridge.permissions import decision
from kirabridge.system_operations import SYSTEM_LEAVES

pytestmark = pytest.mark.skipif(
    keyboard_profiles.fcntl is None, reason="POSIX profile store required"
)
TARGET = {
    "pid": 321,
    "expected_started_at": 1700000000.125,
    "target_token": "a" * 32,
    "helper_pid": 123,
    "worker_generation": "12345678-1234-1234-1234-123456789012",
    "expected_revision": "b" * 64,
}


@pytest.fixture
def tmp_path(tmp_path):
    return tmp_path.resolve()


def definition(*, modifiers=(), provenance="user", key="enter"):
    return {
        "id": "editor",
        "app": {"bundle_id": "org.example.Editor", "layout_id": "org.example.Layout"},
        "actions": {
            "submit": {
                "key": {"named": key},
                "modifiers": list(modifiers),
                "provenance": provenance,
            }
        },
    }


def setup(bridge, config, **definition_args):
    config.principals["local"].capabilities += ["keyboard.execute", "keyboard.profiles.read"]
    bridge.macos.capability_probe.facts.update(platform="darwin", os_version="15.7.4")
    bridge.macos.capability_probe.native_metadata = lambda: {
        "available": True,
        "keyboard_protocol": 1,
    }
    store = KeyboardProfileStore(config.state_path)
    snapshot = store.put(definition(**definition_args))
    bridge.keyboard_profiles._store = store
    arguments = {
        "target": TARGET,
        "profile_id": snapshot.id,
        "expected_revision": snapshot.revision,
        "action": "submit",
    }
    return store, snapshot, arguments


def receipt(payload):
    binding = {key: payload["profile_context"][key] for key in ("id", "revision", "action")}
    return {
        "profile_binding_verified": True,
        "profile_binding": binding,
        "post_calls_returned": 2,
        "app_processing_confirmed": False,
    }


async def execute(bridge, arguments, running=None, progress=None):
    return await bridge.execute(
        {
            "id": "profile-action",
            "principal": "local",
            "operation": "keyboard.action",
            "args": arguments,
        },
        running or AsyncMock(),
        progress or AsyncMock(),
    )


@pytest.mark.parametrize(
    "modifiers,opcode",
    [((), "keyboard.profile.key"), (("command", "shift"), "keyboard.profile.chord")],
)
async def test_action_reuses_one_lease_and_sends_only_private_bound_opcode(
    bridge, config, monkeypatch, modifiers, opcode
):
    _, snapshot, arguments = setup(bridge, config, modifiers=modifiers)
    original = bridge.desktop_input.transaction
    turns = []

    @asynccontextmanager
    async def transaction():
        async with original() as turn:
            turns.append(turn)
            yield turn

    monkeypatch.setattr(bridge.desktop_input, "transaction", transaction)
    observed = []

    async def send(operation, payload, *, principal, before_send):
        assert len(turns) == 1 and bridge.sessions.lock.locked() and not turns[0].attempted
        assert operation == opcode and principal == "local" and payload["target"] == TARGET
        assert payload["profile_context"]["app"] == snapshot.document["app"]
        assert payload.get("modifiers", []) == list(modifiers)
        before_send()
        assert turns[0].attempted
        observed.append(operation)
        return receipt(payload)

    bridge.keyboard.transport.request = AsyncMock(side_effect=send)
    progress = AsyncMock()
    result = await asyncio.wait_for(execute(bridge, arguments, progress=progress), 1)
    assert observed == [opcode] and len(turns) == 1 and not bridge.sessions.lock.locked()
    assert (
        result["profile_revision"] == snapshot.revision
        and result["app_processing_confirmed"] is False
    )
    evidence = progress.await_args.args[0]
    assert evidence["profile_snapshot"] == snapshot.document
    assert evidence["profile_binding"]["revision"] == snapshot.revision
    assert "keyboard.action" not in SYSTEM_LEAVES and "keyboard.profile.key" not in SYSTEM_LEAVES


@pytest.mark.parametrize("missing", ["keyboard.execute", "keyboard.profiles.read"])
async def test_both_capabilities_required_at_admission_and_before_send(bridge, config, missing):
    _, _, arguments = setup(bridge, config)
    policy = config.principals["local"]
    policy.capabilities.remove(missing)
    verdict = decision(config, "local", "keyboard.action")
    assert not verdict["authorized"] and missing in verdict["missing_capabilities"]
    bridge.keyboard.transport.request = AsyncMock()
    with pytest.raises(BridgeError):
        await execute(bridge, arguments)
    bridge.keyboard.transport.request.assert_not_awaited()
    policy.capabilities.append(missing)
    posted = []

    async def revoke(operation, payload, *, before_send, **kwargs):
        policy.capabilities.remove(missing)
        before_send()
        posted.append(operation)
        return receipt(payload)

    bridge.keyboard.transport.request = AsyncMock(side_effect=revoke)
    with pytest.raises(BridgeError):
        await execute(bridge, arguments)
    assert posted == [] and bridge.keyboard.transport.request.await_count == 1


@pytest.mark.parametrize("failure", ["candidate", "missing_action", "stale"])
async def test_preconditions_refuse_before_native_and_snapshot_progress(bridge, config, failure):
    store, snapshot, arguments = setup(
        bridge, config, provenance="observed_menu" if failure == "candidate" else "user"
    )
    if failure == "missing_action":
        arguments["action"] = "not_defined"
    if failure == "stale":
        store.put(definition(key="tab"), expected_revision=snapshot.revision)
    bridge.keyboard.transport.request = AsyncMock()
    progress = AsyncMock()
    with pytest.raises(BridgeError):
        await execute(bridge, arguments, progress=progress)
    bridge.keyboard.transport.request.assert_not_awaited()
    progress.assert_not_awaited()


async def test_shadow_update_after_binding_refuses_at_native_send(bridge, config):
    store, snapshot, arguments = setup(bridge, config)
    posted = []

    async def shadow(operation, payload, *, before_send, **kwargs):
        store.put(definition(key="tab"), expected_revision=snapshot.revision)
        before_send()
        posted.append(operation)
        return receipt(payload)

    bridge.keyboard.transport.request = AsyncMock(side_effect=shadow)
    progress = AsyncMock()
    with pytest.raises(BridgeError) as error:
        await execute(bridge, arguments, progress=progress)
    assert error.value.code == "keyboard_profile_conflict" and posted == []
    assert progress.await_args.args[0]["profile_snapshot"] == snapshot.document
    assert store.get("editor").revision != snapshot.revision


@pytest.mark.parametrize(
    "change", ["missing_verified", "wrong_id", "wrong_revision", "wrong_action"]
)
async def test_bad_native_binding_receipt_is_unknown_without_retry(bridge, config, change):
    _, _, arguments = setup(bridge, config)

    async def send(operation, payload, *, before_send, **kwargs):
        before_send()
        result = receipt(payload)
        if change == "missing_verified":
            result.pop("profile_binding_verified")
        else:
            field = {"wrong_id": "id", "wrong_revision": "revision", "wrong_action": "action"}[
                change
            ]
            result["profile_binding"][field] = "wrong"
        return result

    bridge.keyboard.transport.request = AsyncMock(side_effect=send)
    with pytest.raises(UncertainExecution) as error:
        await execute(bridge, arguments)
    assert error.value.code == "keyboard_profile_action_unknown"
    assert bridge.keyboard.transport.request.await_count == 1


async def test_complete_snapshot_is_durable_after_profile_deletion(bridge, config):
    store, snapshot, arguments = setup(bridge, config)
    bridge.tasks.preflight = None
    identifier = "durable-profile-action"

    async def send(operation, payload, *, before_send, **kwargs):
        before_send()
        events = bridge.events("local", identifier)["events"]
        assert any(
            event["evidence"].get("profile_snapshot") == snapshot.document for event in events
        )
        return receipt(payload)

    bridge.keyboard.transport.request = AsyncMock(side_effect=send)
    request = TaskRequest(
        task_id=identifier,
        idempotency_key=identifier,
        operation="keyboard.action",
        arguments=arguments,
    )
    bridge.submit("local", request, bridge.security.grant("local", request))
    await bridge.tasks.start()
    try:
        final = await bridge.tasks.wait("local", identifier, timeout=5)
        assert final["state"] == "completed", final
    finally:
        await bridge.tasks.stop()
    store.delete("editor", expected_revision=snapshot.revision)
    evidence = [
        event["evidence"]
        for event in bridge.events("local", identifier)["events"]
        if event["evidence"].get("evidence_type") == "keyboard_profile_snapshot_bound"
    ]
    assert len(evidence) == 1 and evidence[0]["profile_snapshot"] == snapshot.document


@pytest.mark.parametrize("extra", ["context", "profile_context", "key", "modifiers"])
def test_public_action_cannot_supply_native_context_or_key(extra):
    arguments = {
        "target": TARGET,
        "profile_id": "editor",
        "expected_revision": "c" * 64,
        "action": "submit",
        extra: {},
    }
    with pytest.raises(ValidationError):
        KeyboardActionInput.model_validate(arguments)
