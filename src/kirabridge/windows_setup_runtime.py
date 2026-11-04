"""Owned Windows setup processes; no port takeover, signalling or global environment edits."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from kirabridge.bridge_core.config import private_directory
from kirabridge.bridge_core.models import BridgeError
from kirabridge.private_files import private_json, write_private


def process_identity(pid: int) -> dict | None:
    """Open a fresh kernel handle. PID reuse never identifies an old setup child."""
    if sys.platform != "win32":
        raise BridgeError("unsupported_platform", "Windows required")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer, integer = ctypes.c_void_p, ctypes.c_uint32
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = (
        [integer, ctypes.c_int, integer],
        pointer,
    )
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [pointer], ctypes.c_int
    kernel.GetProcessTimes.argtypes = [pointer] * 5
    kernel.GetProcessTimes.restype = ctypes.c_int
    kernel.WaitForSingleObject.argtypes, kernel.WaitForSingleObject.restype = (
        [pointer, integer],
        integer,
    )
    kernel.QueryFullProcessImageNameW.argtypes = [pointer, integer, ctypes.c_wchar_p, pointer]
    kernel.QueryFullProcessImageNameW.restype = ctypes.c_int
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return None
        raise BridgeError("setup_process_unavailable", "Cannot inspect the setup process")
    try:
        values = [ctypes.c_uint64() for _ in range(4)]
        name, length = ctypes.create_unicode_buffer(32768), integer(32768)
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(v) for v in values)) or not (
            kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(length))
        ):
            raise BridgeError("setup_process_unavailable", "Cannot inspect the setup process")
        state = kernel.WaitForSingleObject(handle, 0)
        if state not in (0, 258):
            raise BridgeError("setup_process_unavailable", "Cannot inspect the setup process")
        return {
            "pid": pid,
            "created_100ns": str(values[0].value),
            "image": name.value,
            "running": state == 258,
        }
    finally:
        kernel.CloseHandle(handle)


def listeners(port: int) -> list[dict]:
    """Fresh IPv4 listener ownership, including conflicting wildcard listeners."""
    import socket
    import struct

    api = ctypes.WinDLL("iphlpapi", use_last_error=True)
    api.GetExtendedTcpTable.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    api.GetExtendedTcpTable.restype = ctypes.c_uint32
    size = ctypes.c_uint32()
    result = api.GetExtendedTcpTable(None, ctypes.byref(size), False, 2, 3, 0)
    if result not in (0, 122) or size.value > 16 * 1024 * 1024:
        raise BridgeError("setup_listener_unavailable", "Cannot inspect the local listener")
    for _ in range(3):
        buffer = ctypes.create_string_buffer(max(size.value, 4))
        result = api.GetExtendedTcpTable(buffer, ctypes.byref(size), False, 2, 3, 0)
        if result != 122:
            break
        if size.value > 16 * 1024 * 1024:
            raise BridgeError("setup_listener_unavailable", "Local listener table exceeds limit")
    if result or size.value > len(buffer):
        raise BridgeError("setup_listener_unavailable", "Cannot inspect the local listener")
    count = struct.unpack_from("<I", buffer)[0]
    if count > (len(buffer) - 4) // 24:
        raise BridgeError("setup_listener_unavailable", "Invalid local listener table")
    rows = []
    for index in range(count):
        state, address, local_port, _, _, pid = struct.unpack_from("<6I", buffer, 4 + index * 24)
        if state == 2 and socket.ntohs(local_port & 0xFFFF) == port:
            rows.append({"pid": pid, "host": socket.inet_ntoa(struct.pack("<I", address))})
    return rows


def same_process(record: dict) -> bool:
    current = process_identity(record["pid"])
    return bool(
        current
        and current["running"]
        and all(current.get(key) == record.get(key) for key in ("pid", "created_100ns", "image"))
    )


def saved_server(state_dir: Path) -> dict | None:
    folder = state_dir / "servers"
    if not folder.exists():
        return None
    private_directory(folder)
    entries = list(folder.iterdir())
    if len(entries) > 128:
        raise BridgeError("setup_history_full", "Setup history needs local inspection")
    live = []
    for path in entries:
        if len(path.name) != 32 or any(c not in "0123456789abcdef" for c in path.name):
            raise BridgeError("setup_state_invalid", "Existing setup history preserved")
        private_directory(path)
        private_json(path / "attempt.json")
        try:
            record = private_json(path / "process.json")
        except FileNotFoundError:
            raise BridgeError(
                "setup_start_unknown", "Previous start needs local inspection"
            ) from None
        if type(record.get("pid")) is not int or record["pid"] <= 0:
            raise BridgeError("setup_state_invalid", "Existing setup process record preserved")
        if same_process(record):
            live.append(record)
    if len(live) > 1:
        raise BridgeError("setup_start_unknown", "Multiple setup processes need local inspection")
    return live[0] if live else None


def launch_server(state_dir: Path, port: int) -> dict:
    if listeners(port):
        raise BridgeError("setup_port_busy", "Existing listener preserved")
    private_directory(state_dir / "servers")
    folder = state_dir / "servers" / uuid.uuid4().hex
    private_directory(folder)
    write_private(folder / "attempt.json", json.dumps({"attempted_at": time.time(), "port": port}))
    # Windows venv's redirector may create a second PID. Launch its base PE with
    # CPython's child-only venv binding and verify the prefix before server startup.
    env = dict(os.environ)
    env["__PYVENV_LAUNCHER__"] = str(Path(sys.executable).with_name("python.exe"))
    env["KIRA_SETUP_EXPECTED_PREFIX"] = str(Path(sys.prefix).absolute())
    program = str(Path(getattr(sys, "_base_executable", sys.executable)).with_name("python.exe"))
    code = (
        "import os,pathlib,runpy,sys;"
        "assert pathlib.Path(sys.prefix).absolute()=="
        "pathlib.Path(os.environ.pop('KIRA_SETUP_EXPECTED_PREFIX')).absolute();"
        "sys.argv=['kirabridge.windows_preview']+sys.argv[1:];"
        "runpy.run_module('kirabridge.windows_preview',run_name='__main__')"
    )
    child = subprocess.Popen(
        [
            program,
            "-I",
            "-B",
            "-c",
            code,
            "--transport",
            "http",
            "--port",
            str(port),
            "--state-dir",
            str(state_dir),
            "--setup-verification",
        ],
        env=env,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        close_fds=True,
    )
    record = process_identity(child.pid)
    if child.poll() is not None or not record or not record["running"]:
        raise BridgeError("setup_start_unknown", "Setup child exited before identity capture")
    record["port"] = port
    write_private(folder / "process.json", json.dumps(record))
    return record


class SetupLease:
    """One assistant at a time. Closing the assistant never stops its server."""

    def __init__(self, state_dir: Path):
        from kirabridge.platform_adapters.windows.filesystem_security import WindowsFiles

        private_directory(state_dir)
        self.api = WindowsFiles()
        try:
            self.handle = self.api.open(
                state_dir / "assistant.lock", create=True, write=True, exclusive=True
            )
        except OSError:
            raise BridgeError("setup_already_open", "Another setup assistant is open") from None

    def close(self):
        if self.handle is not None:
            self.api.close(self.handle)
            self.handle = None
