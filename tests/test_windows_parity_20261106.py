"""Portable Windows parity contracts. No Win32 call and no execution-policy change."""

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
    visible_environment,
)
from kirabridge.windows_apps import WindowsAppFocusInput, WindowsAppLaunchInput, WindowsAppManager
from kirabridge.windows_console import (
    WindowsConsoleHandoffInput,
    WindowsConsoleManager,
    WindowsConsoleStatusInput,
)
from kirabridge.windows_keyboard import WindowsKeyboardManager, WindowsTextInput
from kirabridge.windows_package import PackageError, install, rollback, status
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
            json.dumps(
                {
                    "handoff_id": plan["handoff_id"],
                    "state": "completed",
                    "exit_code": 0,
                    "argv": list(plan["command"]),
                    "runtime_root": plan["runtime_root"],
                    "import_path": plan["import_path"],
                    "source_sha256": plan["source_sha256"],
                    "stdout": self.result_text,
                    "stderr": "",
                    "stdout_encoding": "utf-8",
                    "stderr_encoding": "utf-8",
                    "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                    "stderr_sha256": hashlib.sha256(b"").hexdigest(),
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
    result = {
        **record,
        "state": "completed",
        "exit_code": 0,
        "stdout": "spät",
        "stderr": "",
        "stdout_encoding": "utf-8",
        "stderr_encoding": "utf-8",
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "visible": True,
    }
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
    assert legacy_code_pages() == ()


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
    assert "old" not in body["import_path"]
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
    updated = install(
        install_root, second, version="0.8.0rc40", commit="aabbccddeeff", update=True
    )
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
