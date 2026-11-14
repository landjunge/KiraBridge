"""Failure evidence survives the existing task path without screen/title data."""

import json
from copy import deepcopy

import pytest
from conftest import request
from test_literal_session_input import literal_visible  # noqa: F401
from test_session_return import key_visible  # noqa: F401
from test_terminal_window_creation import product  # noqa: F401
from test_visible_handoff import visible  # noqa: F401

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.platform_adapters.macos.terminal_window import TerminalWindowProof, geometry_pair
from kirabridge.visible_handoff import VisibleReadinessError


@pytest.mark.parametrize("fault", [None, "missing_child", "worker", "application"])
async def test_replaced_host_wrapper_requires_retained_child_and_generation_evidence(
    product,  # noqa: F811
    fault,
):
    scene, leaf, events, _, created = product
    native_request = leaf.system_transport.request

    async def changed_layout(operation, arguments, **kwargs):
        forwarded = dict(arguments)
        if scene.phase == "tagged" and forwarded.get("element_token") == "f" * 32:
            forwarded["element_token"] = f"{1:032x}"
        value = await native_request(operation, forwarded, **kwargs)
        if arguments.get("element_token") == "f" * 32:
            value["element_token"] = "f" * 32
        if scene.phase in {"tagged", "detached"}:
            if operation == "windows.list":
                host_id = 777 if scene.phase == "tagged" else 231
                next(w for w in value["windows"] if w["window_id"] == host_id)["bounds"].update(
                    Y=30, Height=580
                )
            elif operation == "accessibility.inspect":
                host_token = "f" * 32 if scene.phase == "tagged" else f"{2:032x}"
                if scene.phase == "tagged" and "element_token" not in arguments:
                    value["children"][0]["element_token"] = host_token
                if arguments.get("element_token") == host_token:
                    value["element"].update(position=[0, 30], size=[800, 580])
        if scene.phase == "tagged":
            if (
                fault == "missing_child"
                and operation == "accessibility.inspect"
                and value["element"]["role"] == "AXTabGroup"
            ):
                value["children"][0]["element_token"] = "e" * 32
            if fault == "worker":
                value["native_helper"]["generation"] = "c" * 36
            if fault == "application" and "application" in value:
                value["application"]["started_at"] += 1
        return value

    leaf.system_transport.request = changed_layout
    if fault:
        with pytest.raises(UncertainExecution):
            await leaf.open("", on_created=created, principal="chatgpt")
        assert events == ["create", "receipt", "focus"]
    else:
        result = await leaf.open("", on_created=created, principal="chatgpt")
        proof = result["physical_window"]
        assert proof["host_identity_basis"] == "retained_tab_identities"
        assert proof["own_identity_basis"] == "same_cg_window"
        assert proof["move_confirmed"] and result["separate_window"]
        assert events == ["create", "receipt", "focus", "move"]
        await leaf.verify_opened(result, principal="chatgpt")


@pytest.mark.parametrize("position,size", [([0, 30], [800, 580]), ([120, 70], [900, 640])])
async def test_same_host_reflow_or_resize_binds_identity_and_preserves_fresh_layout(
    product,  # noqa: F811
    position,
    size,
):
    scene, leaf, events, _, created = product
    native_request = leaf.system_transport.request

    async def changed_layout(operation, arguments, **kwargs):
        value = await native_request(operation, arguments, **kwargs)
        if scene.phase in {"tagged", "detached"}:
            if operation == "windows.list":
                host = 777 if scene.phase == "tagged" else 231
                next(w for w in value["windows"] if w["window_id"] == host)["bounds"] = {
                    "X": position[0],
                    "Y": position[1],
                    "Width": size[0],
                    "Height": size[1],
                }
            elif operation == "accessibility.inspect":
                host_token = f"{1 if scene.phase == 'tagged' else 2:032x}"
                if arguments.get("element_token") == host_token:
                    value["element"].update(position=position, size=size)
        return value

    leaf.system_transport.request = changed_layout
    result = await leaf.open("", on_created=created, principal="chatgpt")
    assert result["separate_window"] and result["physical_window"]["move_confirmed"]
    assert events == ["create", "receipt", "focus", "move"]
    await leaf.verify_opened(result, principal="chatgpt")


@pytest.mark.parametrize(
    "change", ["foreign_bounds", "reused_radio", "radio", "extra", "ambiguous", "reused_cg"]
)
def test_shared_host_reflow_never_adopts_foreign_or_unbound_surfaces(change):
    proof = TerminalWindowProof(object(), object(), "chatgpt")
    proof.worker = (99, "a" * 36, "b" * 40)
    original = ["tab-1", "tab-2"]
    host = {
        "token": "host",
        "position": [0, 0],
        "size": [800, 600],
        "radios": [{"token": token} for token in original],
    }
    other = {"token": "other", "position": [1000, 0], "size": [400, 600], "radios": None}
    old_host_cg = {"window_id": 231, "bounds": {"X": 0, "Y": 0, "Width": 800, "Height": 600}}
    other_cg = {"window_id": 888, "bounds": {"X": 1000, "Y": 0, "Width": 400, "Height": 600}}
    proof.before = {"cg": [old_host_cg, other_cg], "ax": [host, other]}
    own = {**deepcopy(host), "position": [0, 30], "size": [800, 580]}
    own["radios"].append({"token": "new-tab", "selected": True})
    own_cg = {"window_id": 777, "bounds": {"X": 0, "Y": 30, "Width": 800, "Height": 580}}
    current = {"cg": [own_cg, deepcopy(other_cg)], "ax": [own, deepcopy(other)]}
    if change == "foreign_bounds":
        current["cg"][1]["bounds"]["X"] += 1
    elif change == "reused_radio":
        own["radios"][-1]["token"] = "tab-1"
    elif change == "radio":
        original = ["tab-1", "foreign-tab"]
    elif change == "extra":
        current["cg"].append({"window_id": 999, "bounds": dict(own_cg["bounds"])})
    elif change == "ambiguous":
        other_cg["bounds"] = dict(old_host_cg["bounds"])
    elif change == "reused_cg":
        own_cg["window_id"] = 888
        current["cg"][1]["window_id"] = 999
    with pytest.raises(BridgeError):
        proof.bind_shared_host(current, own_cg, own, original)


@pytest.mark.parametrize("value", [["raw title", 20], [True, 20], [float("nan"), 20], [1]])
def test_geometry_diagnostics_never_copy_arbitrary_native_values(value):
    assert geometry_pair(value) is None


def test_readiness_error_only_retains_classifier_labels():
    error = VisibleReadinessError(
        {
            "state": "unknown",
            "reason": "unrecognized_footer_or_dialog",
            "target": "codex",
            "text": "secret screen",
            "protocol": {"body": "secret protocol"},
        }
    )
    assert error.provider_error == {
        "readiness": {
            "state": "unknown",
            "reason": "unrecognized_footer_or_dialog",
            "target": "codex",
        }
    }
    assert "secret" not in json.dumps(error.provider_error)
    error = VisibleReadinessError({"state": "unknown", "reason": "raw screen text"})
    assert error.provider_error == {"readiness": {"state": "unknown"}}


async def test_return_failure_persists_readiness_reason_before_any_input(key_visible):  # noqa: F811
    bridge, transport, _, observed = key_visible
    args = await observed("› Existing draft\n  Unrecognized private dialog\n")
    value = request("session.input", args, task_id="readiness-diagnostic")
    async with bridge:
        bridge.prepare("chatgpt", value)
        task = await bridge.tasks.wait("chatgpt", value.task_id, timeout=5)
        assert task["state"] == "failed"
        assert task["error"] == {"code": "visible_target_unknown"}
        assert task["evidence"]["provider_error"] == {
            "readiness": {
                "state": "unknown",
                "reason": "unrecognized_footer_or_dialog",
                "target": "codex",
            }
        }
        assert task["evidence"]["terminal_input_attempted"] is False
        assert "private dialog" not in json.dumps(task["evidence"]["provider_error"])
    assert not transport["literal_calls"]
