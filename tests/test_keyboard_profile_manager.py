"""Local profile routes and caller-only previews; no native transport or GUI."""

import asyncio
import hashlib
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from kirabridge import keyboard_profiles
from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.keyboard_profile_manager import PROFILE_INPUTS, ProfileResolveInput, resolve_preview
from kirabridge.keyboard_profiles import KeyboardProfile, ProfileSnapshot
from kirabridge.operations import OPERATIONS
from kirabridge.system_operations import SYSTEM_LEAVES

pytestmark = pytest.mark.skipif(
    keyboard_profiles.fcntl is None, reason="POSIX profile store required"
)


@pytest.fixture
def tmp_path(tmp_path):
    return tmp_path.resolve()


def definition(identifier="editor", provenance="user", **constraints):
    return {
        "id": identifier,
        "app": {"bundle_id": "org.example.Editor", **constraints},
        "actions": {
            "submit": {"key": {"named": "enter"}, "modifiers": [], "provenance": provenance}
        },
    }


def snapshot(identifier="editor", provenance="user", **constraints):
    model = KeyboardProfile.model_validate(definition(identifier, provenance, **constraints))
    raw = canonical(model.model_dump(mode="json", by_alias=True, exclude_none=True)).encode()
    return ProfileSnapshot(identifier, hashlib.sha256(raw).hexdigest(), raw)


def preview(*profiles, **arguments):
    value = {"action": "submit", "context": {"bundle_id": "org.example.Editor"}, **arguments}
    return resolve_preview(profiles, ProfileResolveInput.model_validate(value))


async def route(bridge, operation, arguments=None, running=None):
    return await bridge.execute(
        {
            "id": "local-profile",
            "principal": "local",
            "operation": operation,
            "args": arguments or {},
        },
        running or AsyncMock(),
        AsyncMock(),
    )


async def test_crud_routes_aliases_cas_and_preview_never_dispatch_native(bridge, config):
    folder = config.state_path / "keyboard"
    assert not folder.exists() and bridge.keyboard_profiles._store is None
    bridge.system_modules.transport.request = AsyncMock(side_effect=AssertionError("No native IO"))
    bridge.keyboard.execute = AsyncMock(side_effect=AssertionError("No keyboard IO"))
    with pytest.raises(BridgeError):
        await route(bridge, "keyboard.profiles.put", {"profile": definition()})
    assert not folder.exists()
    config.principals["local"].capabilities += [
        "keyboard.profiles.read",
        "keyboard.profiles.manage",
    ]
    first = await route(bridge, "keyboard.profiles.put", {"profile": definition()})
    assert first["effect"] == "profile_updated" and not first["input_attempted"]
    listed = await route(bridge, "keyboard.profiles.list")
    assert listed["profiles"][0]["revision"] == first["revision"]
    assert "profile" not in listed["profiles"][0]
    assert listed["profiles"][0]["action_count"] == 1
    assert listed["profiles"][0]["app"] == {"bundle_id": "org.example.Editor"}
    assert (await route(bridge, "keyboard.profiles.get", {"profile_id": "editor"}))[
        "profile"
    ] == first["profile"]
    second = await route(
        bridge,
        "keyboard.profiles.put",
        {"profile": definition(provenance="confirmed_app"), "expected_revision": first["revision"]},
    )
    previous = await route(
        bridge, "keyboard.profiles.get", {"profile_id": "editor", "previous": True}
    )
    assert previous["revision"] == first["revision"] and previous["previous"]
    with pytest.raises(BridgeError) as error:
        await route(
            bridge,
            "keyboard.profiles.resolve",
            {
                "action": "submit",
                "profile_id": "editor",
                "expected_revision": first["revision"],
                "context": {"bundle_id": "org.example.Editor"},
            },
        )
    assert error.value.code == "keyboard_profile_conflict"
    await route(
        bridge,
        "keyboard.profiles.delete",
        {"profile_id": "editor", "expected_revision": second["revision"]},
    )
    assert (await route(bridge, "keyboard.profiles.list"))["profiles"] == []
    bridge.system_modules.transport.request.assert_not_awaited()
    bridge.keyboard.execute.assert_not_awaited()
    for operation in PROFILE_INPUTS:
        assert operation not in SYSTEM_LEAVES
        write = operation.endswith(("put", "delete"))
        assert OPERATIONS[operation].capability == "keyboard.profiles." + (
            "manage" if write else "read"
        )
        assert OPERATIONS[operation].effect == ("write" if write else "read")


async def test_write_rechecks_authorization_after_wait_without_creating_store(bridge, config):
    policy = config.principals["local"]
    policy.capabilities.append("keyboard.profiles.manage")
    await bridge.sessions.lock.acquire()
    task = asyncio.create_task(route(bridge, "keyboard.profiles.put", {"profile": definition()}))
    await asyncio.sleep(0)
    assert not task.done() and bridge.keyboard_profiles._store is None
    policy.capabilities.remove("keyboard.profiles.manage")
    bridge.sessions.lock.release()
    with pytest.raises(BridgeError):
        await task
    assert bridge.keyboard_profiles._store is None and not (config.state_path / "keyboard").exists()


async def test_write_rechecks_policy_after_running_callback(bridge, config):
    policy = config.principals["local"]
    policy.capabilities.append("keyboard.profiles.manage")

    async def revoke(evidence):
        assert bridge.sessions.lock.locked() and evidence["input_attempted"] is False
        policy.capabilities.remove("keyboard.profiles.manage")

    with pytest.raises(BridgeError):
        await route(bridge, "keyboard.profiles.put", {"profile": definition()}, revoke)
    assert bridge.keyboard_profiles._store is None


def test_precedence_preview_and_candidates_never_claim_authority():
    result = preview(
        snapshot("menu", "observed_menu"),
        snapshot("app", "confirmed_app"),
        snapshot("user", "user"),
    )
    assert result["status"] == "resolved" and result["selection"]["profile_id"] == "user"
    assert result["effect"] == "none" and result["input_attempted"] is False
    assert result["context_verified"] is False and result["context_source"] == "caller_preview"
    assert result["preview_only"] and result["execution_authorized"] is False
    candidate = preview(snapshot("menu", "observed_menu"))
    assert candidate["status"] == "candidate_only" and candidate["candidate_only"] is True
    assert candidate["selection"]["modifiers"] == []


def test_equal_rank_is_ambiguous_even_with_identical_keys():
    result = preview(snapshot("one"), snapshot("two"))
    assert result["status"] == "ambiguous" and "selection" not in result


@pytest.mark.parametrize(
    "provenance,expected",
    [
        ("user", "context_unknown"),
        ("confirmed_app", "context_unknown"),
        ("observed_menu", "resolved"),
    ],
)
def test_missing_equal_or_higher_context_blocks_fallback(provenance, expected):
    result = preview(
        snapshot("unknown", provenance, layout_id="org.example.Layout"),
        snapshot("known", "confirmed_app"),
    )
    assert result["status"] == expected
    if expected == "context_unknown":
        assert "selection" not in result and result["reasons"][0]["reason"] == "context_missing"


@pytest.mark.parametrize(
    "constraints,context",
    [
        ({"version": "2"}, {"version": "3"}),
        ({"build": "42"}, {"build": "43"}),
        ({"layout_id": "org.example.Layout"}, {"layout_id": "org.example.Other"}),
        ({"language": "de"}, {"language": "en"}),
        ({"keyboard_type": 40}, {"keyboard_type": 41}),
        ({"signing_team_id": "ABCD123456"}, {"signing_team_id": "ZYXW987654"}),
        ({"field_roles": ["AXTextArea"]}, {"field_role": "AXTextField"}),
    ],
)
def test_changed_context_is_definite_mismatch_not_unknown(constraints, context):
    result = preview(
        snapshot(**constraints), context={"bundle_id": "org.example.Editor", **context}
    )
    assert result["status"] == "not_found"
    assert result["reasons"][0]["reason"] == "context_mismatch"
    assert preview(snapshot(**constraints))["status"] == "context_unknown"


def test_filtered_or_explicit_profile_cannot_fall_back_to_unrelated_profile():
    result = preview(
        snapshot("other", version="2"),
        snapshot("known"),
        profile_id="other",
        context={"bundle_id": "org.example.Editor", "version": "3"},
    )
    assert result["status"] == "not_found" and "selection" not in result
    result = preview(
        snapshot("other", version="2", layout_id="missing"),
        snapshot("known"),
        context={"bundle_id": "org.example.Editor", "version": "3"},
    )
    assert result["selection"]["profile_id"] == "known"
    assert preview(snapshot(), context={"bundle_id": "org.example.Other"})["status"] == "not_found"


@pytest.mark.parametrize(
    "operation,arguments",
    [
        ("get", {"profile_id": "../x"}),
        ("delete", {"profile_id": "x", "expected_revision": None}),
        ("put", {"profile": definition(), "expected_revision": "invalid"}),
        ("resolve", {"action": "submit", "context": {"pid": 123}}),
        (
            "resolve",
            {
                "action": "submit",
                "context": {"bundle_id": "org.example.Editor", "target_token": "x"},
            },
        ),
        (
            "resolve",
            {
                "action": "submit",
                "context": {"bundle_id": "org.example.Editor"},
                "expected_revision": "a" * 64,
            },
        ),
    ],
)
def test_public_inputs_reject_unsafe_or_incomplete_bindings(operation, arguments):
    with pytest.raises(ValidationError):
        PROFILE_INPUTS["keyboard.profiles." + operation].model_validate(arguments)
