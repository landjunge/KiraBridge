"""Persistent dispatch and authorization, without pretending mocks are native input."""

import asyncio

import pytest
from pydantic import ValidationError

import kirabridge.windows_keyboard as manager_module
from kirabridge.bridge_core.models import BridgeError, TaskRequest, UncertainExecution
from kirabridge.desktop_input import DesktopInput
from kirabridge.platform_adapters.windows.keyboard import WindowTarget
from kirabridge.windows_keyboard import (
    WindowsKeyboardManager,
    WindowsSequenceInput,
    WindowsShortcutInput,
    WindowsTargetInput,
)

TARGET = WindowTarget(100, 400, 132000000000000003, 401, 0x04090409)


class Backend:
    def __init__(self):
        self.sent = []
        self.partial = False

    def inspect_foreground(self):
        return TARGET

    def send(self, target, strokes, before_send):
        assert target == TARGET
        before_send()
        self.sent.append(strokes)
        if self.partial:
            raise UncertainExecution("windows_input_unknown", "No replay")
        return {"target": target.to_wire(), "completed_keys": len(strokes)}


def sequence_request(task_id="win-sequence-1"):
    return TaskRequest(
        task_id=task_id,
        idempotency_key=task_id,
        operation="windows.keyboard.sequence",
        arguments={"target": TARGET.to_wire(), "steps": [{"character": "a"}]},
    )


@pytest.mark.parametrize("bad", [132000000000000003, "01", "0", str(2**64), "１"])
def test_opaque_windows_target_rejects_precision_loss_or_ambiguous_identity(bad):
    with pytest.raises(ValidationError):
        WindowsTargetInput.model_validate({**TARGET.to_wire(), "process_created_100ns": bad})


@pytest.mark.parametrize(
    "steps",
    [
        [{"character": "a", "named": "enter"}],
        [{"scan_code": True}],
        [{"named": "not-a-windows-key"}],
        [{"character": "a", "modifiers": ["command"]}],
        [{"character": "a", "repeat": 20}, {"character": "a", "repeat": 20}],
        [{"unicode": "€", "modifiers": ["control"]}],
    ],
)
def test_invalid_sequence_rejected_before_native_backend(steps):
    with pytest.raises(ValidationError):
        WindowsSequenceInput.model_validate({"target": TARGET.to_wire(), "steps": steps})


async def test_inspection_roundtrips_exact_identity_without_marking_effect():
    backend, seen = Backend(), []
    manager = WindowsKeyboardManager(
        lambda *args: None,
        DesktopInput(asyncio.Lock()),
        backend_factory=lambda: backend,
        host="win32",
    )

    async def running(event):
        seen.append(event)

    result = await manager.execute(
        {"principal": "local", "operation": "windows.keyboard.inspect"}, None, running
    )
    assert result["target"]["process_created_100ns"] == "132000000000000003"
    assert not result["effect_attempted"] and not backend.sent
    assert seen and not seen[0]["automatic_retry"]


def test_mac_rejects_windows_submission_before_any_persistent_task(bridge):
    bridge.windows_keyboard.host = "darwin"
    with pytest.raises(BridgeError) as error:
        bridge.prepare("local", sequence_request())
    assert error.value.code == "unsupported_platform"
    assert bridge.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_sequence_requires_separate_inspect_capability(bridge):
    bridge.windows_keyboard.host = "win32"
    bridge.config.principals["local"].capabilities.remove("windows.keyboard.inspect")
    with pytest.raises(BridgeError) as error:
        bridge.submit("local", sequence_request())
    assert error.value.code == "forbidden"
    assert bridge.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


async def test_windows_platform_status_reports_only_real_preview_operations(bridge):
    bridge.windows_keyboard.host = "win32"
    result = await bridge.platform_status("local")
    assert result["platform"] == "win32"
    assert {row["operation"] for row in result["operations"]} == {
        "windows.keyboard.inspect",
        "windows.keyboard.sequence",
        "windows.keyboard.shortcut",
        "windows.keyboard.text",
    }
    assert not result["interactive_desktop_observed"]
    assert "managed process execution" in result["unsupported_features"]


async def test_known_stale_foreground_fails_before_marking_running_or_input():
    backend, transitions = Backend(), []
    manager = WindowsKeyboardManager(
        lambda *args: None,
        DesktopInput(asyncio.Lock()),
        backend_factory=lambda: backend,
        host="win32",
    )
    arguments = sequence_request().arguments
    arguments["target"]["hwnd"] = "101"

    async def running(event):
        transitions.append(event)

    with pytest.raises(BridgeError) as error:
        await manager.execute(
            {"principal": "local", "operation": "windows.keyboard.sequence"},
            WindowsSequenceInput.model_validate(arguments),
            running,
        )
    assert error.value.code == "windows_target_changed"
    assert not transitions and not backend.sent


@pytest.mark.parametrize(
    "key,modifiers", [("Ctrl+A", ["control"]), ("a", []), ("a", ["alt", "alt"])]
)
def test_shortcut_contract_rejects_ambiguous_chords(key, modifiers):
    with pytest.raises(ValidationError):
        WindowsShortcutInput(target=TARGET.to_wire(), key=key, modifiers=modifiers)


async def test_shortcut_is_one_explicit_key_pair_with_modifiers():
    backend = Backend()
    manager = WindowsKeyboardManager(
        lambda *args: None,
        DesktopInput(asyncio.Lock()),
        backend_factory=lambda: backend,
        host="win32",
    )

    async def running(event):
        pass

    result = await manager.execute(
        {"principal": "local", "operation": "windows.keyboard.shortcut"},
        WindowsShortcutInput(target=TARGET.to_wire(), key="a", modifiers=["control"]),
        running,
    )
    assert result["completed_keys"] == 1 and len(backend.sent) == 1
    assert backend.sent[0][0].character == "a"
    assert backend.sent[0][0].modifiers == ("control",)


@pytest.mark.parametrize("expire_before_input", [True, False])
async def test_native_stall_cannot_post_after_deadline_or_report_late_success(
    monkeypatch, expire_before_input
):
    now, sent = [0.0], []
    monkeypatch.setattr(manager_module.time, "monotonic", lambda: now[0])

    class StalledBackend(Backend):
        def send(self, target, strokes, before_send):
            if expire_before_input:
                now[0] = 0.02
            before_send()
            sent.append(True)
            now[0] = 0.02
            return {"completed_keys": 1}

    manager = WindowsKeyboardManager(
        lambda *args: None,
        DesktopInput(asyncio.Lock(), timeout=0.01),
        backend_factory=StalledBackend,
        host="win32",
    )

    async def running(event):
        pass

    with pytest.raises(BridgeError) as caught:
        await manager.execute(
            {"principal": "local", "operation": "windows.keyboard.sequence"},
            WindowsSequenceInput.model_validate(sequence_request().arguments),
            running,
        )
    if expire_before_input:
        assert caught.value.code == "windows_input_deadline_expired" and not sent
    else:
        assert isinstance(caught.value, UncertainExecution) and len(sent) == 1


@pytest.mark.parametrize("partial,expected", [(False, "completed"), (True, "unknown")])
async def test_completed_and_uncertain_windows_tasks_never_replay(bridge, partial, expected):
    backend = Backend()
    backend.partial = partial
    bridge.windows_keyboard = WindowsKeyboardManager(
        bridge.security.authorize,
        bridge.desktop_input,
        backend_factory=lambda: backend,
        host="win32",
    )
    request = sequence_request()
    approval = bridge.security.grant("local", request)
    async with bridge:
        bridge.submit("local", request, approval)
        async with asyncio.timeout(5):
            while bridge.task("local", request.task_id)["state"] not in {"completed", "unknown"}:
                await asyncio.sleep(0.01)
        assert bridge.task("local", request.task_id)["state"] == expected
        result = bridge.submit("local", request, approval)
        assert result["id"] == request.task_id
        await asyncio.sleep(0.03)
        assert len(backend.sent) == 1
