"""A visible Terminal dialog remains separate from every owned TTY."""

import pytest
from test_terminal_window_creation import TITLE, product  # noqa: F401

from kirabridge.bridge_core.models import BridgeError, UncertainExecution


def with_dialog(fixture, *, other_space=False, change=None):
    scene, transport, events, receipt, created = fixture
    if other_space:
        scene.already_isolated = True
        groups = scene.groups
        scene.groups = lambda: [group for group in groups() if group[0] != 231]
    original_request = transport.system_transport.request
    dialog_token = "e" * 32

    async def request(operation, arguments, **kwargs):
        token = "f" * 32 if change == "anchor" and scene.phase != "baseline" else dialog_token
        if operation == "accessibility.inspect" and arguments.get("element_token") == token:
            value = await original_request(
                operation, {k: v for k, v in arguments.items() if k != "element_token"}, **kwargs
            )
            value.update(element_token=token, children=[], total_children=0)
            value["element"].update(
                role="AXWindow",
                subrole="AXDialog",
                title="Profile",
                position=[400 if change == "geometry" else 200, 100],
                size=[500, 300],
            )
            return value
        value = await original_request(operation, arguments, **kwargs)
        if operation == "windows.list":
            value["windows"].append(
                {
                    "window_id": 912,
                    "owner_pid": scene.app["pid"],
                    "application_start": f"{scene.app['started_at']:.6f}",
                    "layer": 0,
                    "on_screen": True,
                    "title_available": True,
                    "title": "Profile",
                    "bounds": {"X": 200, "Y": 100, "Width": 500, "Height": 300},
                }
            )
            value["total"] = value["next_offset"] = len(value["windows"])
            value["accessibility_windows"].append({"role": "AXWindow"})
        elif operation == "accessibility.inspect" and "element_token" not in arguments:
            value["children"].append({"role": "AXWindow", "element_token": token})
            value["total_children"] += 1
        return value

    transport.system_transport.request = request
    return scene, transport, events, receipt, created


@pytest.mark.parametrize("other_space", [True, False])
async def test_open_preserves_dialog_and_separate_owned_tty(product, other_space):  # noqa: F811
    _, transport, events, _, created = with_dialog(product, other_space=other_space)
    result = await transport.open("cd -- /private/work", on_created=created, principal="chatgpt")
    assert result["separate_window"]
    assert result["physical_window"]["cg_window_id"] != 912
    assert events == ["create", "receipt", "focus", "tag"] + ([] if other_space else ["move"])
    await transport.verify_opened(result, principal="chatgpt")


async def test_changed_dialog_anchor_refuses_to_detach(product):  # noqa: F811
    _, transport, events, _, created = with_dialog(product, change="anchor")
    with pytest.raises(UncertainExecution) as error:
        await transport.open("cd -- /private/work", on_created=created, principal="chatgpt")
    assert error.value.provider_error["cause_message"] == "Original native AX group was replaced"
    assert events == ["create", "receipt", "focus", "tag"]


async def test_unbound_dialog_refuses_before_creation(product):  # noqa: F811
    _, transport, events, _, created = with_dialog(product, change="geometry")
    with pytest.raises(BridgeError, match="Native dialog surface is not uniquely bound"):
        await transport.open("cd -- /private/work", on_created=created, principal="chatgpt")
    assert events == []


def test_dialog_cannot_be_adopted_by_title_or_existing_binding():
    from kirabridge.platform_adapters.macos.terminal_window import TerminalWindowProof

    snapshot = {
        "cg": [{"window_id": 912, "title": TITLE}],
        "ax": [{"token": "dialog", "title": TITLE, "dialog_cg_id": 912}],
    }
    with pytest.raises(BridgeError, match="missing or ambiguous"):
        TerminalWindowProof.own(snapshot, nonce=TITLE)
    binding = {"cg_window_id": 912, "ax_window_token": "dialog"}
    with pytest.raises(BridgeError, match="missing or ambiguous"):
        TerminalWindowProof.own(snapshot, binding=binding)
