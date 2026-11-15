"""Full-screen menu/toolbar partitions never become terminal input targets."""

from copy import deepcopy

import pytest
from test_terminal_window_creation import product  # noqa: F401

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.platform_adapters.macos.terminal_window import TerminalWindowProof


def ancillary_scene(fixture, *, fault=None, changed=False):
    scene, leaf, events, receipt, created = fixture
    native = leaf.system_transport.request
    unknowns = [format(9001 + index, "032x") for index in range(3)]

    async def request(operation, arguments, **kwargs):
        after = scene.phase != "baseline"
        token = arguments.get("element_token")
        actual_tokens = list(unknowns)
        if fault == "ax_replaced" and after:
            actual_tokens[0] = format(9500, "032x")
        opaque = token in actual_tokens
        forwarded = dict(arguments)
        if opaque:
            forwarded["element_token"] = format(1, "032x")
        result = await native(operation, forwarded, **kwargs)
        if operation == "windows.list":
            original = deepcopy(result["windows"][0])
            menus = [
                {**original, "window_id": 9001 + index, "layer": 26, "title": "",
                 "bounds": {"X": 0, "Y": -24, "Width": 800, "Height": 24}}
                for index in range(3)
            ]
            toolbar = {**original, "window_id": 9004, "title": "",
                       "bounds": {"X": 0, "Y": -72, "Width": 800, "Height": 72}}
            if fault == "missing_cg":
                menus.pop()
            if fault == "named_cg":
                menus[0]["title"] = "A real named surface"
            if fault == "wrong_layer":
                menus[0]["layer"] = 25
            if fault == "cg_replaced" and after:
                menus[0]["window_id"] = 9500
            if fault == "toolbar_moved" and after:
                toolbar["bounds"]["X"] += 1
            if fault == "toolbar_removed" and after:
                toolbar = None
            if fault == "foreign_owner":
                toolbar["owner_pid"] += 1
            if fault == "unobserved_title":
                toolbar["title_available"] = False
            if fault == "offscreen":
                toolbar["on_screen"] = False
            result["windows"] += menus + ([toolbar] if toolbar else [])
            result["total"] = result["next_offset"] = len(result["windows"])
            result["accessibility_windows"] += [{"role": "AXWindow"} for _ in unknowns]
            if changed:
                # A working foreign CLI may change title between CG and AX reads.
                result["windows"][0]["title"] = "different spinner"
        elif operation == "accessibility.inspect":
            if token is None:
                result["children"] += [
                    {"role": "AXWindow", "element_token": token} for token in actual_tokens
                ]
                result["total_children"] = len(result["children"])
            elif opaque:
                result["element_token"] = token
                result["element"] = {
                    "role": "AXWindow", "subrole": "AXUnknown", "minimized": False,
                    "focused": False, "title": "", "title_truncated": False,
                    "identifier": "", "description": "", "actions": ["AXRaise"],
                    "position": [0, -24], "size": [800, 24],
                }
                result.update(children=[], total_children=0, next_offset=0, eof=True)
                if fault == "child":
                    result.update(children=[{"role": "AXButton"}], total_children=1)
                if fault == "title":
                    result["element"]["title"] = "Actual foreign window"
                if fault == "focused":
                    result["element"]["focused"] = True
                if fault == "bad_geometry":
                    result["element"]["size"][0] += 1
                if fault == "identifier":
                    result["element"]["identifier"] = "A real named AX surface"
                if fault == "actions":
                    result["element"]["actions"] = ["AXClose"]
                if fault == "nan_geometry":
                    result["element"]["size"][0] = float("nan")
        return result

    leaf.system_transport.request = request
    return scene, leaf, events, receipt, created


@pytest.mark.parametrize("standalone", [True, False])
async def test_complete_ancillary_partition_is_retained_but_never_own_or_host(
    product, standalone  # noqa: F811
):
    scene, leaf, events, _, created = ancillary_scene(product)
    scene.already_isolated = standalone
    opened = await leaf.open("cd -- /private/work", on_created=created, principal="chatgpt")
    assert opened["physical_window"]["cg_window_id"] not in range(9001, 9005)
    assert events == (["create", "receipt", "focus"] if standalone
                      else ["create", "receipt", "focus", "move"])
    await leaf.verify_opened(opened, principal="chatgpt")


async def test_foreign_spinner_title_change_is_not_session_selection_authority(product):  # noqa:F811
    _, leaf, events, _, _ = ancillary_scene(product, changed=True)
    proof = TerminalWindowProof(leaf, leaf.system_transport, "chatgpt")
    await proof.prepare()
    assert len(proof.before["cg"]) == len(proof.before["ax"]) == 1
    assert len(proof.before["ancillary"]["cg"]) == 4
    assert len(proof.before["ancillary"]["ax"]) == 3
    assert not events


@pytest.mark.parametrize("fault", [
    "missing_cg", "named_cg", "wrong_layer", "child", "title", "focused", "bad_geometry",
    "foreign_owner", "unobserved_title", "offscreen", "identifier", "actions", "nan_geometry",
])
async def test_unmatched_or_interactive_unknown_ax_still_refuses_before_creation(
    product, fault  # noqa: F811
):
    _, leaf, events, _, created = ancillary_scene(product, fault=fault)
    with pytest.raises(BridgeError):
        await leaf.open("cd -- /private/work", on_created=created, principal="chatgpt")
    assert not events
    leaf.native.assert_not_awaited()


@pytest.mark.parametrize("fault", [
    "ax_replaced", "cg_replaced", "toolbar_moved", "toolbar_removed",
])
async def test_changed_foreign_ancillary_partition_stops_before_detach_and_input(
    product, fault  # noqa: F811
):
    _, leaf, events, _, created = ancillary_scene(product, fault=fault)
    with pytest.raises(UncertainExecution):
        await leaf.open("cd -- /private/work", on_created=created, principal="chatgpt")
    assert events == ["create", "receipt", "focus"]


async def test_bound_verify_rejects_new_passive_surface_even_without_title_change(product):  # noqa:F811
    scene, leaf, _, _, created = ancillary_scene(product)
    opened = await leaf.open("cd -- /private/work", on_created=created, principal="chatgpt")
    request = leaf.system_transport.request

    async def extra(operation, arguments, **kwargs):
        result = await request(operation, arguments, **kwargs)
        if operation == "windows.list":
            row = deepcopy(result["windows"][-1])
            row["window_id"] = 9999
            result["windows"].append(row)
            result["total"] = result["next_offset"] = len(result["windows"])
        return result

    leaf.system_transport.request = extra
    with pytest.raises(BridgeError, match="physical partition changed"):
        await leaf.verify_opened(opened, principal="chatgpt")


@pytest.mark.parametrize("reuse", ["cg", "ax"])
async def test_a_previously_ancillary_identity_cannot_become_own_even_with_exact_nonce(
    product, reuse  # noqa: F811
):
    scene, leaf, _, receipt, _ = product
    scene.already_isolated = True
    proof = TerminalWindowProof(leaf, leaf.system_transport, "chatgpt")
    await proof.prepare()
    proof.before["ancillary"] = {
        "cg": [{"window_id": 777}] if reuse == "cg" else [],
        "ax": [{"token": format(2, "032x")}] if reuse == "ax" else [],
    }
    scene.created()
    scene.phase = "tagged"
    with pytest.raises(BridgeError, match="original ancillary surface"):
        await proof.isolate(receipt)
    leaf.native.assert_not_awaited()


async def test_duplicate_standard_cg_match_is_not_hidden_as_passive_inventory(product):  # noqa:F811
    _, leaf, events, _, created = ancillary_scene(product)
    request = leaf.system_transport.request

    async def ambiguous(operation, arguments, **kwargs):
        result = await request(operation, arguments, **kwargs)
        if operation == "windows.list":
            duplicate = deepcopy(result["windows"][0])
            duplicate["window_id"] = 9998
            result["windows"].append(duplicate)
            result["total"] = result["next_offset"] = len(result["windows"])
        return result

    leaf.system_transport.request = ambiguous
    with pytest.raises(BridgeError):
        await leaf.open("cd -- /private/work", on_created=created, principal="chatgpt")
    assert not events
