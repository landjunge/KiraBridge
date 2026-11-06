"""Portable Windows parity contracts. No Win32 call and no execution-policy change."""

import json
import sys

import pytest

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.desktop_input import DesktopInput
from kirabridge.platform_adapters.windows.apps import (
    CREATE_NEW_CONSOLE,
    CREATE_NO_WINDOW,
    launch_plan,
)
from kirabridge.platform_adapters.windows.keyboard import KeyStroke, WindowTarget
from kirabridge.platform_adapters.windows.text import text_batches, text_strokes
from kirabridge.platform_adapters.windows.visible_console import (
    console_main,
    console_plan,
    visible_environment,
)
from kirabridge.windows_apps import WindowsAppFocusInput, WindowsAppLaunchInput, WindowsAppManager
from kirabridge.windows_console import WindowsConsoleHandoffInput, WindowsConsoleManager
from kirabridge.windows_keyboard import WindowsKeyboardManager, WindowsTextInput
from kirabridge.windows_package import install, rollback, status
from kirabridge.windows_preview import CAPABILITIES

TARGET = WindowTarget(100, 400, 132000000000000003, 401, 0x04070407)


def test_unicode_text_is_packet_text_and_enter_not_a_layout_or_clipboard_plan():
    strokes = text_strokes("Größe €\n😀")
    assert [stroke.unicode for stroke in strokes[:-2]] == list("Größe €")
    assert strokes[-2] == KeyStroke(named="enter")
    assert strokes[-1].unicode == "😀"
    assert all(stroke.modifiers == () for stroke in strokes)
    assert text_strokes("a" * 33)[32].unicode == "a"
    assert len(text_batches("a" * 33)) == 2
    with pytest.raises(ValueError):
        text_strokes("hidden\x1b")


def test_preview_capabilities_stay_closed():
    assert "windows.keyboard.text" not in CAPABILITIES
    assert "windows.app.launch" not in CAPABILITIES
    assert "windows.console.handoff" not in CAPABILITIES


async def test_text_manager_sends_batches_without_replay_after_a_partial_batch():
    sent = []

    class Backend:
        def inspect_foreground(self):
            return TARGET

        def send(self, target, strokes, before_send):
            before_send()
            sent.append(tuple(strokes))
            if len(sent) == 2:
                raise UncertainExecution("windows_keyboard_partial", "No replay")
            return {
                "completed_keys": len(strokes),
                "inserted_events": len(strokes) * 2,
                "native_calls": 1,
                "physical_key_events": False,
                "target": target.to_wire(),
            }

    manager = WindowsKeyboardManager(
        lambda *_args: None,
        DesktopInput(__import__("asyncio").Lock()),
        backend_factory=lambda: Backend(),
        host="win32",
    )
    args = WindowsTextInput.model_validate({"target": TARGET.to_wire(), "text": "ä" * 33})

    async def running(_event):
        return None

    with pytest.raises(UncertainExecution):
        await manager.execute(
            {"principal": "local", "operation": "windows.keyboard.text"}, args, running
        )
    assert len(sent) == 2
    assert all(stroke.unicode == "ä" for batch in sent for stroke in batch)


class WindowsBackend:
    def __init__(self):
        self.actions = []

    def list(self, limit):
        return {
            "windows": [
                {
                    "target": {
                        "hwnd": "10",
                        "pid": "400",
                        "process_created_100ns": "132000000000000003",
                        "thread_id": "401",
                    }
                }
            ],
            "truncated": False,
            "limit": limit,
        }

    def control(self, target, action, before_effect=None):
        before_effect()
        self.actions.append((target.pid, action))
        return {"action": action, "observed": True, "effect_attempted": True}


class Launcher:
    def __init__(self):
        self.plans = []

    def launch(self, plan):
        self.plans.append(plan)
        return {
            "pid": "4242",
            "process_created_100ns": "132000000000000009",
            "image": plan["image"],
            "visible_requested": True,
            "creation_flags": plan["creation_flags"],
            "application_processing_confirmed": False,
            "automatic_retry": False,
        }


async def test_launch_is_shown_and_focus_reuses_one_window():
    windows, launcher = WindowsBackend(), Launcher()
    manager = WindowsAppManager(
        lambda *_args: None,
        DesktopInput(__import__("asyncio").Lock()),
        windows_factory=lambda: windows,
        host="win32",
    )
    manager.launcher = launcher

    async def running(_event):
        return None

    launched = await manager.execute(
        {"principal": "local", "operation": "windows.app.launch"},
        WindowsAppLaunchInput.model_validate(
            {"image": r"C:\Program Files\KiraBridge\KiraBridge.exe", "console": True}
        ),
        running,
    )
    plan = launcher.plans[0]
    assert launched["visible_requested"] is True
    assert plan["creation_flags"] & CREATE_NEW_CONSOLE
    assert not plan["creation_flags"] & CREATE_NO_WINDOW
    assert plan["show"] == 1
    focused = await manager.execute(
        {"principal": "local", "operation": "windows.app.focus"},
        WindowsAppFocusInput.model_validate(
            {"pid": "400", "process_created_100ns": "132000000000000003"}
        ),
        running,
    )
    assert focused["observed"] is True
    assert windows.actions == [(400, "activate")]
    hidden = launch_plan(r"C:\Tools\KiraBridge.exe")
    assert not hidden["creation_flags"] & CREATE_NO_WINDOW


def test_visible_environment_drops_credentials_and_forbidden_console_tokens():
    env = visible_environment({"PATH": r"C:\Windows", "API_TOKEN": "secret", "SECRET": "no"})
    assert env["PYTHONUTF8"] == "1"
    assert "API_TOKEN" not in env and "SECRET" not in env
    with pytest.raises(BridgeError) as error:
        console_plan(
            python=r"C:\Python314\python.exe",
            handoff_id="handoff01",
            result_path=r"C:\Temp\result.json",
            cwd=r"C:\Temp",
            argv=("powershell.exe", "-ExecutionPolicy", "Bypass"),
            hold_seconds=0,
            timeout_seconds=8,
        )
    assert error.value.code == "windows_console_forbidden"


def test_console_main_returns_unicode_from_the_same_session(tmp_path):
    result = tmp_path / "result.json"
    code = console_main(
        [
            "--",
            "handoff01",
            str(result),
            "0",
            "8",
            str(tmp_path),
            sys.executable,
            "-c",
            "print('Größe €')",
        ]
    )
    assert code == 0
    body = json.loads(result.read_text(encoding="utf-8"))
    assert body["state"] == "completed"
    assert "Größe €" in body["stdout"]
    assert body["visible"] is True


class Spawner:
    python = r"C:\Python314\python.exe"

    def __init__(self, result_text="Größe"):
        self.calls = 0
        self.result_text = result_text

    def start(self, plan):
        self.calls += 1
        assert plan["redirect_stdio"] is False
        assert plan["creation_flags"] & CREATE_NEW_CONSOLE
        assert not plan["creation_flags"] & CREATE_NO_WINDOW
        marker = plan["argv"].index("--")
        result = __import__("pathlib").Path(plan["argv"][marker + 2])
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text(
            json.dumps(
                {
                    "handoff_id": plan["argv"][marker + 1],
                    "state": "completed",
                    "exit_code": 0,
                    "stdout": self.result_text,
                    "stderr": "",
                    "visible": True,
                }
            ),
            encoding="utf-8",
        )
        return {"pid": 77}


async def test_completed_console_handoff_is_not_started_again(tmp_path):
    spawner = Spawner()
    manager = WindowsConsoleManager(
        lambda *_args: None,
        DesktopInput(__import__("asyncio").Lock()),
        tmp_path,
        spawner=spawner,
        host="win32",
    )
    args = WindowsConsoleHandoffInput.model_validate(
        {
            "handoff_id": "handoff01",
            "argv": [r"C:\Python314\python.exe", "-c", "print(1)"],
            "cwd": r"C:\Temp",
        }
    )

    async def running(_event):
        return None

    task = {"principal": "local", "operation": "windows.console.handoff"}
    first = await manager.execute(task, args, running)
    second = await manager.execute(task, args, running)
    assert first["spawned"] is True and first["deduplicated"] is False
    assert first["stdout"] == "Größe"
    assert second["deduplicated"] is True and second["spawned"] is False
    assert spawner.calls == 1
    assert first["credential_environment_copied"] is False


def test_package_update_and_rollback_keep_data_and_do_not_change_policy(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    root = tmp_path / "root"
    first.mkdir()
    second.mkdir()
    (first / "app.py").write_text("print('one')\n", encoding="utf-8")
    (second / "app.py").write_text("print('two')\n", encoding="utf-8")
    installed = install(root, first, version="0.8.0rc40", commit="d12838ae97c7")
    (root / "data" / "keep.txt").write_text("behalten", encoding="utf-8")
    updated = install(root, second, version="0.8.0rc40", commit="aabbccddeeff", update=True)
    restored = rollback(root)
    assert installed["execution_policy_changed"] is False
    assert updated["previous"].endswith("d12838ae97c7")
    assert restored["release"].endswith("d12838ae97c7")
    assert (root / "data" / "keep.txt").read_text(encoding="utf-8") == "behalten"
    assert (root / "releases" / updated["release"]).is_dir()
    assert status(root)["execution_policy_changed"] is False
