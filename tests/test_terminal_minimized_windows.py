"""Opaque minimized anchors coexist with a newly created visible work window."""

import pytest
from test_terminal_window_creation import product  # noqa: F401

from kirabridge.bridge_core.models import BridgeError, UncertainExecution


def minimized_scene(fixture, *, all_minimized, change=None, incomplete=False):
    scene, leaf, events, receipt, created = fixture
    scene.already_isolated = all_minimized
    native_request = leaf.system_transport.request
    opaque_token = f"{1:032x}" if all_minimized else "e" * 32

    async def request(operation, arguments, **kwargs):
        after_creation = scene.phase != "baseline"
        changed = after_creation and change == "anchor"
        token = "f" * 32 if changed else opaque_token
        is_minimized = not (after_creation and change == "restore")
        opaque_request = arguments.get("element_token") == token
        forwarded = dict(arguments)
        if opaque_request and (not all_minimized or changed):
            forwarded["element_token"] = f"{1:032x}"
        value = await native_request(operation, forwarded, **kwargs)
        if operation == "windows.list":
            if all_minimized and is_minimized:
                value["windows"] = [w for w in value["windows"] if w["window_id"] != 231]
                value["total"] = value["next_offset"] = len(value["windows"])
            elif not all_minimized:
                value["accessibility_windows"].append({"role": "AXWindow"})
            if incomplete:
                value["windows"] = []
                value["total"] = value["next_offset"] = 0
        elif operation == "accessibility.inspect":
            if "element_token" not in arguments:
                if all_minimized:
                    value["children"][0]["element_token"] = token
                else:
                    value["children"].append({"role": "AXWindow", "element_token": token})
                    value["total_children"] += 1
            elif opaque_request:
                value["element_token"] = token
                value["element"].update(
                    role="AXWindow",
                    subrole="AXDialog" if is_minimized else "AXStandardWindow",
                    minimized=is_minimized,
                )
                if is_minimized:
                    value.update(children=[], total_children=0, next_offset=0)
        return value

    leaf.system_transport.request = request
    return scene, leaf, events, receipt, created


@pytest.mark.parametrize("all_minimized", [True, False])
async def test_minimized_anchors_allow_one_owned_window_without_restoring_old_windows(
    product,  # noqa: F811
    all_minimized,
):
    _, leaf, events, _, created = minimized_scene(product, all_minimized=all_minimized)
    result = await leaf.open("", on_created=created, principal="chatgpt")
    assert result["separate_window"]
    assert events == (
        ["create", "receipt", "focus"] if all_minimized else ["create", "receipt", "focus", "move"]
    )
    await leaf.verify_opened(result, principal="chatgpt")
    sources = [call.args[0] for call in leaf.native.await_args_list]
    assert not any("activation_sent" in source or "miniaturized=" in source for source in sources)


@pytest.mark.parametrize("change", ["anchor", "restore"])
async def test_minimized_anchor_change_during_creation_stops_without_detach_or_reopen(
    product,  # noqa: F811
    change,
):
    _, leaf, events, _, created = minimized_scene(product, all_minimized=True, change=change)
    with pytest.raises(UncertainExecution):
        await leaf.open("", on_created=created, principal="chatgpt")
    assert events == ["create", "receipt", "focus"]
    assert leaf.native.await_count == 2


async def test_visible_count_mismatch_with_minimized_anchors_still_refuses_before_creation(
    product,  # noqa: F811
):
    _, leaf, events, _, created = minimized_scene(product, all_minimized=False, incomplete=True)
    with pytest.raises(BridgeError) as error:
        await leaf.open("", on_created=created, principal="chatgpt")
    assert error.value.code == "session_window_inventory_pending"
    observed = error.value.provider_error["window_observation"]
    assert observed["cg_window_count"] == 0
    assert observed["visible_ax_window_count"] == 1
    assert observed["minimized_ax_window_count"] == 1
    assert events == []
    leaf.native.assert_not_awaited()
