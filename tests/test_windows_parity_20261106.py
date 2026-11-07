"""Portable Windows parity contracts. No Win32 call and no execution-policy change."""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

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
    decode_console_bytes,
    legacy_code_pages,
    runtime_identity,
    valid_console_result,
    visible_environment,
)
from kirabridge.windows_apps import WindowsAppFocusInput, WindowsAppLaunchInput, WindowsAppManager
from kirabridge.windows_console import (
    WindowsConsoleHandoffInput,
    WindowsConsoleManager,
    WindowsConsoleStatusInput,
)
from kirabridge.windows_keyboard import WindowsKeyboardManager, WindowsTextInput
from kirabridge.windows_package import PackageError, install, rollback, status, uninstall
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


def _identity_argv(identity=None):
    identity = runtime_identity() if identity is None else identity
    return [identity["runtime_root"], identity["source_sha256"]]


def test_visible_environment_drops_credentials_and_forbidden_console_tokens():
    env = visible_environment({"PATH": r"C:\Windows", "API_TOKEN": "secret", "SECRET": "no"})
    assert env["PYTHONUTF8"] == "1"
    assert "API_TOKEN" not in env and "SECRET" not in env and "PYTHONPATH" not in env
    identity = runtime_identity()
    with pytest.raises(BridgeError) as error:
        console_plan(
            python=r"C:\Python314\python.exe",
            handoff_id="handoff01",
            result_path=r"C:\Temp\result.json",
            cwd=r"C:\Temp",
            argv=("powershell.exe", "-ExecutionPolicy", "Bypass"),
            hold_seconds=0,
            timeout_seconds=8,
            runtime_root=identity["runtime_root"],
            source_sha256=identity["source_sha256"],
            import_path=identity["import_path"],
        )
    assert error.value.code == "windows_console_forbidden"


def test_console_main_returns_unicode_from_the_same_session(tmp_path):
    result = tmp_path / "result.json"
    code = console_main(
        [
            "--",
            *_identity_argv(),
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
    assert body["stdout_encoding"] == "utf-8"
    assert body["import_path"] == runtime_identity()["import_path"]
    assert body["source_sha256"] == runtime_identity()["source_sha256"]
    assert body["visible"] is True


def _completed_streams(source, text, stdout, *, encoding="utf-8"):
    command = source["command"] if "command" in source else source["argv"]
    return {
        "handoff_id": source["handoff_id"],
        "state": "completed",
        "visible": True,
        "exit_code": 0,
        "argv": list(command),
        "runtime_root": source["runtime_root"],
        "import_path": source["import_path"],
        "source_sha256": source["source_sha256"],
        "stdout": text,
        "stderr": "",
        "stdout_encoding": encoding,
        "stderr_encoding": "utf-8",
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "stdout_byte_length": len(stdout),
        "stderr_byte_length": 0,
        "stdout_decoded_strict": True,
        "stderr_decoded_strict": True,
        "stdout_ambiguous": False,
        "stderr_ambiguous": False,
    }


class Spawner:
    python = r"C:\Python314\python.exe"

    def __init__(self, result_text="Größe"):
        self.calls = 0
        self.result_text = result_text
        self.plans = []

    def start(self, plan):
        self.calls += 1
        self.plans.append(plan)
        assert plan["redirect_stdio"] is False
        assert "-P" in plan["argv"]
        assert plan["creation_flags"] & CREATE_NEW_CONSOLE
        assert not plan["creation_flags"] & CREATE_NO_WINDOW
        assert "PYTHONPATH" not in plan["environment_keys"]
        stdout = self.result_text.encode()
        result = Path(plan["result_path"])
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text(
            json.dumps(_completed_streams(plan, self.result_text, stdout)),
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


def test_package_uninstall_keeps_data_and_removes_releases(tmp_path):
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "app.py").write_text("print('one')\n", encoding="utf-8")
    root = tmp_path / "root"
    installed = install(root, payload, version="0.8.0rc40", commit="d12838ae97c7")
    (root / "data" / "keep.txt").write_text("behalten", encoding="utf-8")
    removed = uninstall(root)
    assert removed["action"] == "uninstall"
    assert removed["data_preserved"] is True
    assert removed["execution_policy_changed"] is False
    assert removed["removed"] == [installed["release"]]
    assert (root / "data" / "keep.txt").read_text(encoding="utf-8") == "behalten"
    assert not (root / "current.json").exists()
    assert not (root / "releases" / installed["release"]).exists()
    assert status(root)["installed"] is False
    with pytest.raises(PackageError, match="existing installation"):
        uninstall(root)


def _manager(tmp_path, spawner):
    return WindowsConsoleManager(
        lambda *_args: None,
        DesktopInput(__import__("asyncio").Lock()),
        tmp_path,
        spawner=spawner,
        host="win32",
    )


def _handoff(handoff_id="handoff01", command=None):
    return WindowsConsoleHandoffInput.model_validate(
        {
            "handoff_id": handoff_id,
            "argv": command or [r"C:\Python314\python.exe", "-c", "print(1)"],
            "cwd": r"C:\Temp",
        }
    )


async def test_two_waiters_reserve_one_console_under_the_desktop_lock(tmp_path):
    asyncio = __import__("asyncio")
    lock = asyncio.Lock()
    await lock.acquire()
    spawner = Spawner()
    manager = WindowsConsoleManager(
        lambda *_args: None, DesktopInput(lock), tmp_path, spawner=spawner, host="win32"
    )
    args = _handoff()

    async def running(_event):
        return None

    task = {"principal": "local", "operation": "windows.console.handoff"}
    first = asyncio.create_task(manager.execute(task, args, running))
    second = asyncio.create_task(manager.execute(task, args, running))
    await asyncio.sleep(0.05)
    assert spawner.calls == 0
    lock.release()
    results = await asyncio.gather(first, second)
    assert spawner.calls == 1
    assert sorted(item["deduplicated"] for item in results) == [False, True]
    assert sorted(item["spawned"] for item in results) == [False, True]


async def test_late_result_reconciles_once_without_a_new_start(tmp_path):
    spawner = Spawner()
    manager = _manager(tmp_path, spawner)
    identity = runtime_identity()
    argv = [r"C:\Python314\python.exe", "-c", "print(1)"]
    record = {
        "handoff_id": "handoff01",
        "state": "unknown",
        "argv": argv,
        "runtime_root": identity["runtime_root"],
        "import_path": identity["import_path"],
        "source_sha256": identity["source_sha256"],
        "creation_flags": 1,
        "show": 1,
        "environment_keys": [],
    }
    (tmp_path / "windows-console").mkdir()
    (tmp_path / "windows-console" / "handoff01.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    stdout = "spät".encode()
    result = _completed_streams(record, "spät", stdout)
    (tmp_path / "windows-console" / "handoff01.result.json").write_text(
        json.dumps(result), encoding="utf-8"
    )

    async def running(_event):
        return None

    task = {"principal": "local", "operation": "windows.console.handoff"}
    reconciled = await manager.execute(task, _handoff(command=argv), running)
    status = await manager.execute(
        {"principal": "local", "operation": "windows.console.status"},
        WindowsConsoleStatusInput.model_validate({"handoff_id": "handoff01"}),
        running,
    )
    assert spawner.calls == 0
    assert reconciled["reconciled"] is True and reconciled["spawned"] is False
    assert reconciled["stdout"] == "spät"
    assert status["state"] == "completed" and status["deduplicated"] is True
    assert status["record"]["stdout"] == reconciled["stdout"]
    wrong = {
        **result,
        "handoff_id": "handoff02",
        "argv": [r"C:\Python314\python.exe", "-c", "print(2)"],
    }
    (tmp_path / "windows-console" / "handoff02.result.json").write_text(
        json.dumps(wrong), encoding="utf-8"
    )
    (tmp_path / "windows-console" / "handoff02.json").write_text(
        json.dumps({**record, "handoff_id": "handoff02", "state": "unknown"}), encoding="utf-8"
    )
    with pytest.raises(UncertainExecution):
        await manager.execute(task, _handoff("handoff02", command=argv), running)
    assert spawner.calls == 0


async def test_inconsistent_receipt_stays_open_without_a_new_start(tmp_path):
    spawner = Spawner()
    manager = _manager(tmp_path, spawner)
    identity = runtime_identity()
    argv = [r"C:\Python314\python.exe", "-c", "print(1)"]
    record = {
        "handoff_id": "goodrec1",
        "state": "unknown",
        "argv": argv,
        "runtime_root": identity["runtime_root"],
        "import_path": identity["import_path"],
        "source_sha256": identity["source_sha256"],
    }
    valid = _completed_streams(record, "Größe", "Größe".encode())
    assert valid_console_result(record, valid) is True
    altered = {
        **valid,
        "stdout": "altered",
        "stdout_sha256": "0" * 64,
        "stderr_sha256": "0" * 64,
    }
    del altered["exit_code"]
    assert valid_console_result(record, altered) is False
    mutations = {
        "badrec00": altered,
        "badrec01": {**valid, "exit_code": True},
        "badrec02": {**valid, "stdout_sha256": "0" * 64},
        "badrec03": {**valid, "stdout_byte_length": valid["stdout_byte_length"] + 1},
        "badrec04": {**valid, "stdout_encoding": "not-a-codec"},
        "badrec05": {key: value for key, value in valid.items() if key != "stdout_sha256"},
        "badrec06": {key: value for key, value in valid.items() if key != "stdout_encoding"},
        "badrec07": {**valid, "stdout_decoded_strict": False},
        "badrec08": {**valid, "exit_code": False},
    }
    directory = tmp_path / "windows-console"
    directory.mkdir()
    (directory / "goodrec1.json").write_text(
        json.dumps({**record, "state": "unknown"}), encoding="utf-8"
    )
    (directory / "goodrec1.result.json").write_text(json.dumps(valid), encoding="utf-8")

    async def running(_event):
        return None

    task = {"principal": "local", "operation": "windows.console.handoff"}
    reconciled = await manager.execute(task, _handoff("goodrec1", command=argv), running)
    assert reconciled["reconciled"] is True and reconciled["spawned"] is False
    assert reconciled["stdout"] == "Größe"
    assert type(reconciled["exit_code"]) is int and reconciled["exit_code"] == 0
    for handoff, result in mutations.items():
        row = {**record, "handoff_id": handoff, "state": "unknown"}
        body = {**result, "handoff_id": handoff}
        assert valid_console_result(row, body) is False
        (directory / f"{handoff}.json").write_text(json.dumps(row), encoding="utf-8")
        (directory / f"{handoff}.result.json").write_text(json.dumps(body), encoding="utf-8")
        with pytest.raises(UncertainExecution):
            await manager.execute(task, _handoff(handoff, command=argv), running)
    assert spawner.calls == 0


def test_oem_bytes_round_trip_and_do_not_become_unknown(tmp_path, monkeypatch):
    payload = "Größe".encode("cp850")
    monkeypatch.setattr(
        "kirabridge.platform_adapters.windows.visible_console.legacy_code_pages",
        lambda: ("cp850",),
    )
    decoded = decode_console_bytes(payload)
    assert decoded["encoding"] == "cp850"
    assert decoded["text"] == "Größe"
    assert decoded["text"].encode("cp850") == payload
    result = tmp_path / "oem.json"
    code = console_main(
        [
            "--",
            *_identity_argv(),
            "handoff01",
            str(result),
            "0",
            "8",
            str(tmp_path),
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(" + repr(payload) + ")",
        ]
    )
    body = json.loads(result.read_text(encoding="utf-8"))
    assert code == 0
    assert body["state"] == "completed"
    assert body["stdout"] == "Größe"
    assert body["stdout_encoding"] == "cp850"
    assert body["stdout_sha256"] == hashlib.sha256(payload).hexdigest()
    assert body["stdout_decoded_strict"] is True
    assert body["stdout_ambiguous"] is False
    assert body["exit_code"] == 0 and type(body["exit_code"]) is int
    assert legacy_code_pages() == ()


def test_cp1252_and_cp850_need_an_explicit_output_encoding():
    ansi = "Größe".encode("cp1252")
    oem = "Größe".encode("cp850")
    guessed = decode_console_bytes(ansi, legacy=("cp850", "cp1252"))
    assert guessed["text"] == ""
    assert guessed["encoding"] is None
    assert guessed["decoded_strict"] is False
    assert guessed["ambiguous"] is True
    assert guessed["text_status"] == "ambiguous"
    assert guessed["candidate_encodings"] == ["cp850", "cp1252"]
    assert base64.b64decode(guessed["raw_base64"]) == ansi
    assert guessed["sha256"] == hashlib.sha256(ansi).hexdigest()
    assert guessed["byte_length"] == len(ansi)
    assert "Gr÷▀e" not in guessed["text"]

    selected_ansi = decode_console_bytes(ansi, legacy=("cp850", "cp1252"), encoding="cp1252")
    assert selected_ansi["text"] == "Größe"
    assert selected_ansi["encoding"] == "cp1252"
    assert selected_ansi["decoded_strict"] is True
    assert selected_ansi["ambiguous"] is False
    assert selected_ansi["requested_encoding"] == "cp1252"
    assert selected_ansi["text"].encode("cp1252") == ansi

    selected_oem = decode_console_bytes(oem, encoding="cp850")
    assert selected_oem["text"] == "Größe"
    assert selected_oem["encoding"] == "cp850"
    assert selected_oem["decoded_strict"] is True
    assert selected_oem["ambiguous"] is False
    assert selected_oem["text"].encode("cp850") == oem

    failed = decode_console_bytes(ansi, encoding="utf-8")
    assert failed["decoded_strict"] is False
    assert failed["ambiguous"] is False
    assert failed["text"] == ""
    assert failed["text_status"] == "decode-failed"
    assert base64.b64decode(failed["raw_base64"]) == ansi


def test_selected_encoding_and_ambiguous_pages_reach_the_visible_result(tmp_path, monkeypatch):
    ansi = "Größe".encode("cp1252")
    oem = "Größe".encode("cp850")
    ansi_result = tmp_path / "ansi.json"
    code = console_main(
        [
            "--",
            *_identity_argv(),
            "handoff01",
            str(ansi_result),
            "0",
            "8",
            str(tmp_path),
            "--encoding",
            "cp1252",
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(" + repr(ansi) + ")",
        ]
    )
    ansi_body = json.loads(ansi_result.read_text(encoding="utf-8"))
    assert code == 0
    assert ansi_body["state"] == "completed"
    assert ansi_body["stdout"] == "Größe"
    assert ansi_body["stdout_encoding"] == "cp1252"
    assert ansi_body["stdout_decoded_strict"] is True
    assert ansi_body["stdout_requested_encoding"] == "cp1252"
    assert type(ansi_body["exit_code"]) is int and ansi_body["exit_code"] == 0

    oem_result = tmp_path / "oem.json"
    code = console_main(
        [
            "--",
            *_identity_argv(),
            "handoff02",
            str(oem_result),
            "0",
            "8",
            str(tmp_path),
            "--encoding",
            "cp850",
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(" + repr(oem) + ")",
        ]
    )
    oem_body = json.loads(oem_result.read_text(encoding="utf-8"))
    assert code == 0
    assert oem_body["stdout"] == "Größe"
    assert oem_body["stdout_encoding"] == "cp850"
    assert oem_body["stdout_decoded_strict"] is True

    monkeypatch.setattr(
        "kirabridge.platform_adapters.windows.visible_console.legacy_code_pages",
        lambda: ("cp850", "cp1252"),
    )
    open_result = tmp_path / "open.json"
    code = console_main(
        [
            "--",
            *_identity_argv(),
            "handoff03",
            str(open_result),
            "0",
            "8",
            str(tmp_path),
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(" + repr(ansi) + ")",
        ]
    )
    open_body = json.loads(open_result.read_text(encoding="utf-8"))
    assert code == 1
    assert open_body["state"] == "open"
    assert open_body["stdout"] == ""
    assert open_body["stdout_decoded_strict"] is False
    assert open_body["stdout_ambiguous"] is True
    assert open_body["stdout_candidate_encodings"] == ["cp850", "cp1252"]
    assert base64.b64decode(open_body["stdout_raw_base64"]) == ansi
    assert open_body["stdout_sha256"] == hashlib.sha256(ansi).hexdigest()


def test_handoff_plan_passes_output_encoding_to_the_visible_console():
    args = WindowsConsoleHandoffInput.model_validate(
        {
            "handoff_id": "handoff01",
            "argv": ["powershell.exe", "-NoProfile", "-Command", "[Console]::Write('Größe')"],
            "cwd": r"C:\Temp",
            "output_encoding": "cp1252",
        }
    )
    identity = runtime_identity()
    plan = console_plan(
        python=r"C:\Python314\python.exe",
        handoff_id=args.handoff_id,
        result_path=r"C:\Temp\result.json",
        cwd=args.cwd,
        argv=tuple(args.argv),
        hold_seconds=args.hold_seconds,
        timeout_seconds=args.timeout_seconds,
        runtime_root=identity["runtime_root"],
        source_sha256=identity["source_sha256"],
        import_path=identity["import_path"],
        output_encoding=args.output_encoding,
    )
    selected = plan["argv"].index("--encoding")
    assert plan["output_encoding"] == "cp1252"
    assert plan["argv"][selected + 1] == "cp1252"
    assert plan["argv"][selected + 2] == "powershell.exe"


def test_invalid_utf8_keeps_byte_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "kirabridge.platform_adapters.windows.visible_console.legacy_code_pages",
        lambda: (),
    )
    raw = bytes([0x84])
    result = tmp_path / "raw.json"
    code = console_main(
        [
            "--",
            *_identity_argv(),
            "handoff01",
            str(result),
            "0",
            "8",
            str(tmp_path),
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(" + repr(raw) + ")",
        ]
    )
    body = json.loads(result.read_text(encoding="utf-8"))
    assert code == 0
    assert body["state"] == "completed"
    assert body["stdout_encoding"] == "latin-1"
    assert body["stdout_decoded_strict"] is False
    assert body["stdout_sha256"] == hashlib.sha256(raw).hexdigest()
    assert body["stdout"].encode("latin-1") == raw


def test_owned_child_stops_at_the_output_limit_and_on_timeout(tmp_path):
    limited = tmp_path / "limited.json"
    code = console_main(
        [
            "--",
            *_identity_argv(),
            "handoff01",
            str(limited),
            "0",
            "8",
            str(tmp_path),
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'X'*200000)",
        ]
    )
    body = json.loads(limited.read_text(encoding="utf-8"))
    assert code == 1
    assert body["state"] == "truncated"
    assert body["stdout_byte_length"] == 65536
    assert len(body["stdout"]) == 65536
    with pytest.raises(ProcessLookupError):
        os.kill(body["child_pid"], 0)
    timed = tmp_path / "timed.json"
    started = time.monotonic()
    code = console_main(
        [
            "--",
            *_identity_argv(),
            "handoff02",
            str(timed),
            "0",
            "1",
            str(tmp_path),
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
        ]
    )
    assert time.monotonic() - started < 8
    saved = json.loads(timed.read_text(encoding="utf-8"))
    assert code == 1 and saved["state"] == "timeout"
    with pytest.raises(ProcessLookupError):
        os.kill(saved["child_pid"], 0)


def test_child_imports_the_pinned_runtime_not_an_older_package(tmp_path):
    identity_root = Path(runtime_identity()["runtime_root"])
    copy_root = tmp_path / "new"
    shutil.copytree(
        identity_root / "kirabridge",
        copy_root / "kirabridge",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    source = copy_root / "kirabridge" / "platform_adapters" / "windows" / "visible_console.py"
    source.write_bytes(source.read_bytes() + b"\n")
    pinned = {
        "runtime_root": str(copy_root.resolve()),
        "import_path": str(source.resolve()),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    old = tmp_path / "old"
    package = old / "kirabridge" / "platform_adapters" / "windows"
    package.mkdir(parents=True)
    (old / "kirabridge" / "__init__.py").write_text("__version__ = 'old'\n", encoding="utf-8")
    (old / "kirabridge" / "platform_adapters" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "visible_console.py").write_text(
        "raise RuntimeError('old runtime')\n", encoding="utf-8"
    )
    result = tmp_path / "result.json"
    plan = console_plan(
        python=sys.executable,
        handoff_id="handoff01",
        result_path=str(result),
        cwd=str(old),
        argv=(sys.executable, "-c", "print('pinned')"),
        hold_seconds=0,
        timeout_seconds=8,
        runtime_root=pinned["runtime_root"],
        source_sha256=pinned["source_sha256"],
        import_path=pinned["import_path"],
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(old)
    completed = subprocess.run(
        plan["argv"], cwd=old, env=env, check=True, capture_output=True, text=True, timeout=20
    )
    body = json.loads(result.read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert body["import_path"] == pinned["import_path"]
    assert body["source_sha256"] == pinned["source_sha256"]
    assert not Path(body["import_path"]).resolve().is_relative_to(old.resolve())
    assert body["stdout"].strip() == "pinned"


def test_package_rejects_links_tampering_and_foreign_rollback(tmp_path):
    payload = tmp_path / "payload"
    outside = tmp_path / "outside"
    payload.mkdir()
    outside.mkdir()
    (payload / "app.py").write_text("print('one')\n", encoding="utf-8")
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (payload / "linked").symlink_to(outside, target_is_directory=True)
    root = tmp_path / "root"
    with pytest.raises(PackageError):
        install(root, payload, version="0.8.0rc40", commit="d12838ae97c7")
    assert "secret" not in " ".join(
        path.read_text(encoding="utf-8") for path in root.rglob("*") if path.is_file()
    )
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "app.py").write_text("print('one')\n", encoding="utf-8")
    os.link(plain / "app.py", plain / "alias.py")
    with pytest.raises(PackageError):
        install(tmp_path / "hard", plain, version="0.8.0rc40", commit="d12838ae97c7")
    first, second = tmp_path / "first", tmp_path / "second"
    install_root = tmp_path / "install"
    first.mkdir()
    second.mkdir()
    (first / "app.py").write_text("print('one')\n", encoding="utf-8")
    (second / "app.py").write_text("print('two')\n", encoding="utf-8")
    installed = install(install_root, first, version="0.8.0rc40", commit="d12838ae97c7")
    (install_root / "data" / "keep.txt").write_text("behalten", encoding="utf-8")
    updated = install(install_root, second, version="0.8.0rc40", commit="aabbccddeeff", update=True)
    release = install_root / "releases" / installed["release"]
    (release / "app.py").write_text("tampered\n", encoding="utf-8")
    before = (install_root / "current.json").read_bytes()
    with pytest.raises(PackageError):
        rollback(install_root)
    assert (install_root / "current.json").read_bytes() == before
    assert (install_root / "data" / "keep.txt").read_text(encoding="utf-8") == "behalten"
    with pytest.raises(PackageError):
        install(install_root, first, version="0.8.0rc40", commit="d12838ae97c7", update=True)
    assert status(install_root)["current"]["release"] == updated["release"]
    current = json.loads(before)
    current["previous"] = "../outside"
    (install_root / "current.json").write_text(json.dumps(current), encoding="utf-8")
    poisoned = (install_root / "current.json").read_bytes()
    with pytest.raises(PackageError):
        rollback(install_root)
    assert (install_root / "current.json").read_bytes() == poisoned
    assert (install_root / "data" / "keep.txt").read_text(encoding="utf-8") == "behalten"


def test_parallel_install_waits_and_keeps_data(tmp_path):
    root = tmp_path / "root"
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "app.py").write_text("print('one')\n", encoding="utf-8")
    (second / "app.py").write_text("print('two')\n", encoding="utf-8")
    installed = install(root, first, version="0.8.0rc40", commit="d12838ae97c7")
    (root / "data" / "keep.txt").write_text("behalten", encoding="utf-8")
    ready, release = tmp_path / "ready", tmp_path / "release"
    src = str(Path(__file__).resolve().parents[1] / "src")
    code = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from kirabridge.windows_package import package_lock\n"
        "root, ready, release = map(Path, sys.argv[2:])\n"
        "with package_lock(root):\n"
        "    ready.write_text('held', encoding='utf-8')\n"
        "    deadline = time.monotonic() + 30\n"
        "    while not release.exists():\n"
        "        if time.monotonic() > deadline:\n"
        "            break\n"
        "        time.sleep(0.05)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-P", "-c", code, src, str(root), str(ready), str(release)]
    )
    try:
        for _ in range(50):
            if ready.exists():
                break
            time.sleep(0.05)
        assert ready.read_text(encoding="utf-8") == "held"
        done = threading.Event()

        def update():
            install(root, second, version="0.8.0rc40", commit="aabbccddeeff", update=True)
            done.set()

        thread = threading.Thread(target=update)
        thread.start()
        time.sleep(0.4)
        assert not done.is_set()
        assert status(root)["current"]["release"] == installed["release"]
        assert (root / "data" / "keep.txt").read_text(encoding="utf-8") == "behalten"
        release.write_text("go", encoding="utf-8")
        thread.join(10)
        assert done.is_set()
    finally:
        release.write_text("go", encoding="utf-8")
        process.wait(timeout=10)
    assert (root / "data" / "keep.txt").read_text(encoding="utf-8") == "behalten"
    assert status(root)["current"]["release"].endswith("aabbccddeeff")


def test_zip_install_imports_the_activated_runtime_and_rejects_a_foreign_commit(tmp_path):
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "windows_parity_package.py"
    spec = importlib.util.spec_from_file_location("windows_parity_package", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / "parity.zip"
    built = module.build(output)
    with output.open("rb") as handle:
        archive_names = set(__import__("zipfile").ZipFile(handle).namelist())
    assert "LICENSE" in archive_names
    assert "provenance.json" in archive_names
    assert "scripts/accept_windows_keyboard.py" in archive_names
    assert "scripts/accept_windows_windows.py" in archive_names
    assert built["standalone_executable"] is False
    assert built["commit_source"] == "git-rev-parse-HEAD"
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    __import__("zipfile").ZipFile(output).extractall(extracted)
    root = tmp_path / "root"
    with pytest.raises(PackageError):
        install(root, extracted, version="0.8.0rc40", commit="aaaaaaaaaaaa")
    installed = install(root, extracted, version="0.8.0rc40", commit=built["commit"])
    assert installed["provenance_verified"] is True
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import kirabridge\n"
        "print(Path(kirabridge.__file__).resolve())\n"
        "print(kirabridge.__version__)\n"
    )
    runtime = root / "releases" / installed["release"] / "src"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, "-P", "-B", "-c", code, str(runtime)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    location, version = completed.stdout.splitlines()
    assert location.endswith(str(Path("src") / "kirabridge" / "__init__.py"))
    assert installed["release"] in location
    assert version == "0.8.0rc40"
    with pytest.raises(SystemExit):
        module.main(
            [
                "install",
                "--root",
                str(tmp_path / "other"),
                "--payload",
                str(extracted),
                "--commit",
                "bbbbbbbbbbbb",
            ]
        )


def test_extracted_payload_roundtrip_does_not_call_git(tmp_path):
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "accept_windows_parity.py"
    spec = importlib.util.spec_from_file_location("accept_windows_parity_guest", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = tmp_path / "payload"
    package = payload / "src" / "kirabridge"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "0.8.0rc40"\n', encoding="utf-8")
    (payload / "LICENSE").write_text("license\n", encoding="utf-8")
    inventory = {
        path.relative_to(payload).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in payload.rglob("*")
        if path.is_file()
    }
    commit = "37ea23911d20133b3ca80e6ecb65442f2d49dad5"
    (payload / "provenance.json").write_text(
        json.dumps(
            {
                "commit": commit,
                "commit_source": "test-fixture",
                "version": "0.8.0rc40",
                "files": inventory,
                "standalone_executable": False,
            }
        ),
        encoding="utf-8",
    )
    report = module.activate_roundtrip(tmp_path / "work", payload, commit)
    assert report["provenance_verified"] is True
    assert report["first_import"]["marker"] == "absent"
    assert report["second_import"]["marker"] == "two"
    assert report["rollback_import"]["marker"] == "absent"
    assert report["data"] == "behalten"
    assert commit[:12] in report["first_import"]["import_path"]
    assert report["first_import"]["import_path"] != report["second_import"]["import_path"]


def _parity_package_module():
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "windows_parity_package.py"
    spec = importlib.util.spec_from_file_location("windows_parity_package_export", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _export_document(module):
    members = {
        path.relative_to(module.ROOT).as_posix(): path.read_bytes()
        for path in module.payload_files()
    }
    document = {
        "commit": "3f8ab70abc1234567890abcdef1234567890abcd",
        "commit_source": "git-rev-parse-HEAD",
        "dirty": False,
        "version": "0.8.0rc40",
        "standalone_executable": False,
        "kind": "existing-python-plus-zip",
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in members.items()},
    }
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return document, raw


def test_validated_export_rebuilds_without_git_and_refuses_changes(tmp_path, monkeypatch):
    import zipfile

    module = _parity_package_module()

    def git_missing(*_args, **_kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(module.subprocess, "check_output", git_missing)
    document, raw = _export_document(module)
    export = tmp_path / "provenance.json"
    export.write_bytes(raw)
    first = module.build(tmp_path / "one.zip", provenance_export=export)
    second = module.build(tmp_path / "two.zip", provenance_export=export)
    assert first["sha256"] == second["sha256"]
    assert first["dirty"] is False
    assert first["commit_source"] == "git-rev-parse-HEAD"
    assert first["commit"] == document["commit"]
    with zipfile.ZipFile(tmp_path / "one.zip") as archive:
        assert archive.read("provenance.json") == raw
        info = archive.getinfo("src/kirabridge/__init__.py")
        assert info.compress_type == zipfile.ZIP_STORED
        assert info.create_system == 3
    changed = json.loads(raw)
    changed["files"]["pyproject.toml"] = "0" * 64
    changed_path = tmp_path / "changed.json"
    changed_path.write_bytes(json.dumps(changed, sort_keys=True, separators=(",", ":")).encode())
    with pytest.raises(SystemExit, match="changed export bytes"):
        module.build(tmp_path / "changed.zip", provenance_export=changed_path)
    dirty = json.loads(raw)
    dirty["dirty"] = True
    dirty_path = tmp_path / "dirty.json"
    dirty_path.write_bytes(json.dumps(dirty, sort_keys=True, separators=(",", ":")).encode())
    with pytest.raises(SystemExit, match="dirty provenance export"):
        module.build(tmp_path / "dirty.zip", provenance_export=dirty_path)
    invented = json.loads(raw)
    invented["commit_source"] = "guest-without-git"
    invented_path = tmp_path / "invented.json"
    invented_path.write_bytes(json.dumps(invented, sort_keys=True, separators=(",", ":")).encode())
    with pytest.raises(SystemExit, match="git rev-parse HEAD"):
        module.build(tmp_path / "invented.zip", provenance_export=invented_path)


def test_repository_provenance_still_uses_git_rev_parse():
    module = _parity_package_module()
    observed = module.git_provenance()
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=module.ROOT, text=True
    ).strip()
    assert observed["commit"] == commit
    assert observed["commit_source"] == "git-rev-parse-HEAD"
    assert type(observed["dirty"]) is bool
