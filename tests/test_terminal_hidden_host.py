"""A hidden singleton has no pre-open radios; retain its AX anchor after detach."""

import pytest
from test_terminal_window_creation import TITLE, product  # noqa: F401

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.platform_adapters.macos.terminal_window import TerminalWindowProof


async def hidden_scene(fixture):
    scene, leaf, events, receipt, created = fixture
    scene.rows = scene.rows[:1]
    scene.no_own_group = False

    def groups():
        if scene.phase == "baseline":
            return [(231, "original", None)]
        if scene.phase == "detached":
            return [(231, "original", None), (777, TITLE, 1)]
        return [(777, TITLE, 2)]

    scene.groups = groups
    request = leaf.system_transport.request
    wrapper = "f" * 32

    async def native(operation, arguments, **kwargs):
        forwarded = dict(arguments)
        if forwarded.get("element_token") == wrapper:
            forwarded["element_token"] = f"{1:032x}"
        result = await request(operation, forwarded, **kwargs)
        if operation == "accessibility.inspect":
            if scene.phase == "tagged":
                if not arguments.get("element_token"):
                    result["children"][0]["element_token"] = wrapper
                elif arguments["element_token"] == wrapper:
                    result["element_token"] = wrapper
            if scene.phase == "detached" and result["element"]["role"] == "AXTabGroup":
                result["children"][0]["element_token"] = f"{1001:032x}"
                result["children"][0]["value"] = True
        return result

    leaf.system_transport.request = native
    return scene, leaf, events, receipt, created


async def test_hidden_singleton_binds_complete_partition_then_restores_old_ax_anchor(product):  # noqa: F811
    scene, leaf, events, _, created = await hidden_scene(product)
    result = await leaf.open("cd -- /private/work", on_created=created, principal="chatgpt")
    assert result["physical_window"]["host_identity_basis"] == "hidden_singleton_partition"
    assert result["physical_window"]["move_confirmed"]
    assert events == ["create", "receipt", "focus", "move"]
    await leaf.verify_opened(result, principal="chatgpt")


@pytest.mark.parametrize("change", ["anchor", "position", "width", "radios"])
async def test_hidden_host_detach_requires_original_anchor_and_coherent_layout(product, change):  # noqa: F811
    scene, leaf, events, receipt, created = await hidden_scene(product)
    request = leaf.system_transport.request

    async def changed(operation, arguments, **kwargs):
        if (
            scene.phase == "detached"
            and operation == "accessibility.inspect"
            and arguments.get("element_token") == f"{100:032x}"
            and change == "radios"
        ):
            result = await request(
                operation, {**arguments, "element_token": f"{101:032x}"}, **kwargs
            )
            result["element_token"] = f"{100:032x}"
            result["children"][0]["element_token"] = "d" * 32
            return result
        result = await request(operation, arguments, **kwargs)
        if scene.phase == "detached" and operation == "accessibility.inspect":
            if not arguments.get("element_token") and change == "anchor":
                result["children"][0]["element_token"] = "e" * 32
            elif arguments.get("element_token") == f"{1:032x}":
                if change == "position":
                    result["element"]["position"] = [1, 0]
                if change == "width":
                    result["element"]["size"] = [801, 600]
                if change == "radios":
                    result["children"].append(
                        {"role": "AXTabGroup", "element_token": f"{100:032x}"}
                    )
        return result

    leaf.system_transport.request = changed
    with pytest.raises(UncertainExecution) as error:
        await leaf.open("cd -- /private/work", on_created=created, principal="chatgpt")
    assert error.value.provider_error["creation_receipt"] == receipt
    assert events == ["create", "receipt", "focus", "move"]


async def test_hidden_candidate_never_substitutes_changed_visible_radio_partition(product):  # noqa: F811
    scene, leaf, events, receipt, created = await hidden_scene(product)
    groups = scene.groups
    scene.groups = lambda: [(231, "original", 1)] if scene.phase == "baseline" else groups()
    request = leaf.system_transport.request

    async def replaced_radio(operation, arguments, **kwargs):
        result = await request(operation, arguments, **kwargs)
        if (
            scene.phase == "tagged"
            and operation == "accessibility.inspect"
            and result["element"]["role"] == "AXTabGroup"
        ):
            result["children"][0]["element_token"] = "d" * 32
        return result

    leaf.system_transport.request = replaced_radio
    with pytest.raises(UncertainExecution) as error:
        await leaf.open("cd -- /private/work", on_created=created, principal="chatgpt")
    assert error.value.provider_error["cause_message"] == (
        "Shared host is not positively bound to the pre-open radio partition"
    )
    assert events == ["create", "receipt", "focus"]


@pytest.mark.parametrize("operation", ["windows.list", "accessibility.inspect"])
async def test_native_tree_transition_repeats_only_same_read_bounded(operation):
    calls = []

    class Native:
        async def request(self, op, arguments, *, principal):
            calls.append((op, arguments, principal))
            raise BridgeError("macos_tree_changed", "transition")

    proof = TerminalWindowProof(None, Native(), "chatgpt")
    with pytest.raises(BridgeError, match="transition"):
        await proof.read(operation, {"limit": 100})
    assert calls == [(operation, {"limit": 100}, "chatgpt")] * 3


@pytest.mark.parametrize("change", [None, "unrelated_cg", "unrelated_radios", "ambiguous_hidden"])
def test_hidden_host_requires_complete_unchanged_unrelated_partition(change):
    from copy import deepcopy

    def group(token, position, radios):
        return {"token": token, "position": position, "size": [800, 600], "radios": radios}

    def window(number, x):
        return {"window_id": number, "bounds": {"X": x, "Y": 0, "Width": 800, "Height": 600}}

    unrelated = group("other", [900, 0], [{"token": "old-other", "selected": True}])
    proof = TerminalWindowProof(None, object(), "chatgpt")
    proof.worker = (1, "generation", "source")
    proof.before = {
        "ax": [group("hidden", [0, 0], None), deepcopy(unrelated)],
        "cg": [window(101, 0), window(202, 900)],
    }
    own = group(
        "new",
        [0, 0],
        [
            {"token": "old-hidden", "selected": False},
            {"token": "new-tab", "selected": True},
        ],
    )
    own_cg = window(303, 0)
    current = {"ax": [own, unrelated], "cg": [own_cg, window(202, 900)]}
    if change == "unrelated_cg":
        current["cg"][1]["bounds"]["Width"] += 1
    if change == "unrelated_radios":
        unrelated["radios"][0]["token"] = "replacement"
    if change == "ambiguous_hidden":
        proof.before["ax"][1]["radios"] = None
        unrelated["token"] = "replacement"
    if change is None:
        assert proof.bind_shared_host(current, own_cg, own, ["old-hidden"]) == (
            "hidden_singleton_partition"
        )
    else:
        with pytest.raises(BridgeError):
            proof.bind_shared_host(current, own_cg, own, ["old-hidden"])


async def test_hidden_host_accepts_coherent_height_reflow_only(product):  # noqa: F811
    scene, leaf, _, _, created = await hidden_scene(product)
    request = leaf.system_transport.request

    async def reflow(operation, arguments, **kwargs):
        result = await request(operation, arguments, **kwargs)
        if scene.phase == "detached":
            if operation == "windows.list":
                result["windows"][0]["bounds"]["Height"] = 580
            if (
                operation == "accessibility.inspect"
                and arguments.get("element_token") == f"{1:032x}"
            ):
                result["element"]["size"] = [800, 580]
        return result

    leaf.system_transport.request = reflow
    result = await leaf.open("cd -- /private/work", on_created=created, principal="chatgpt")
    assert result["physical_window"]["host_identity_basis"] == "hidden_singleton_partition"
    await leaf.verify_opened(result, principal="chatgpt")
