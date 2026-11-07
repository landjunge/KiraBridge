"""Review regressions for child startup, daemon responsiveness and owned pipes."""

import asyncio
import importlib.util
import os
import sys
import threading
import time
from pathlib import Path

from kirabridge.agent_manager.full_access import bridge_server
from kirabridge.platform_adapters.windows.visible_console import run_owned_command


def test_full_access_mcp_spec_disables_generated_bytecode():
    server = bridge_server("explicit-policy.toml", "local")
    assert server["command"] == sys.executable
    assert server["args"][:3] == ["-B", "-m", "kirabridge.cli"]


def _parity_support():
    path = Path(__file__).with_name("test_windows_parity_20261106.py")
    spec = importlib.util.spec_from_file_location("parity_review_support", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_console_wait_keeps_daemon_loop_responsive(tmp_path, monkeypatch):
    import kirabridge.windows_console as console

    helpers = _parity_support()
    manager = helpers._manager(tmp_path, helpers.Spawner())
    started, released = threading.Event(), threading.Event()
    original = console.wait_result

    def blocked_wait(path, timeout):
        started.set()
        assert released.wait(2), "Daemon event loop could not release an outstanding console wait"
        return original(path, timeout)

    monkeypatch.setattr(console, "wait_result", blocked_wait)

    async def peer_request():
        while not started.is_set():
            await asyncio.sleep(0)
        released.set()

    async def running(_event):
        pass

    try:
        result, _ = await asyncio.wait_for(
            asyncio.gather(
                manager.execute(
                    {"principal": "local", "operation": "windows.console.handoff"},
                    helpers._handoff(),
                    running,
                ),
                peer_request(),
            ),
            3,
        )
    finally:
        released.set()
    assert result["state"] == "completed"


def test_inherited_descendant_pipes_obey_the_original_deadline(tmp_path):
    child = "import time;time.sleep(12)"
    parent = (
        "import subprocess,sys;"
        "child=subprocess.Popen([sys.executable,'-B','-c'," + repr(child) + "],"
        "stdout=sys.stdout,stderr=sys.stderr,close_fds=False);"
        "print(child.pid,flush=True)"
    )
    started = time.monotonic()
    result = run_owned_command(
        [sys.executable, "-B", "-c", parent],
        cwd=str(tmp_path),
        env=dict(os.environ),
        timeout=1,
        limit=65536,
    )
    elapsed = time.monotonic() - started
    assert result["state"] == "timeout", result
    assert result["exit_code"] is None
    assert elapsed < 3, elapsed
    pid = int(result["stdout"].strip())
    if sys.platform == "win32":
        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.WaitForSingleObject.restype = ctypes.c_uint32
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if handle:
            try:
                assert kernel.WaitForSingleObject(handle, 1000) == 0, "Owned descendant still runs"
            finally:
                kernel.CloseHandle(handle)
        else:
            assert ctypes.get_last_error() in (87, 1168)
        assert result["owned_job"]


async def test_cancelled_console_wait_preserves_unknown_and_reconciles_once(tmp_path, monkeypatch):
    import pytest

    import kirabridge.windows_console as console

    helpers = _parity_support()
    spawner = helpers.Spawner()
    manager = helpers._manager(tmp_path, spawner)
    started, released = threading.Event(), threading.Event()
    original = console.wait_result

    def blocked_wait(path, timeout):
        started.set()
        assert released.wait(2)
        return original(path, timeout)

    monkeypatch.setattr(console, "wait_result", blocked_wait)

    async def running(_event):
        pass

    task = asyncio.create_task(
        manager.execute(
            {"principal": "local", "operation": "windows.console.handoff"},
            helpers._handoff(),
            running,
        )
    )
    try:
        while not started.is_set():
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert manager._read("handoff01")["state"] == "unknown"
        assert spawner.calls == 1
    finally:
        released.set()
    status = await manager.execute(
        {"principal": "local", "operation": "windows.console.status"},
        console.WindowsConsoleStatusInput(handoff_id="handoff01"),
        running,
    )
    assert status["state"] == "completed" and status["record"]["reconciled"]
    assert spawner.calls == 1
