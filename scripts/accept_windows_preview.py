"""Guest-only smoke of the real Windows preview entry point; never sends keys."""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def process_snapshot(pid):
    """Fresh kernel handle, independent of Popen's retained process handle."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer, integer = ctypes.c_void_p, ctypes.c_uint32
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = (
        [integer, ctypes.c_int32, integer],
        pointer,
    )
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [pointer], ctypes.c_int32
    kernel.GetProcessTimes.argtypes = [pointer] * 5
    kernel.GetProcessTimes.restype = ctypes.c_int32
    kernel.WaitForSingleObject.argtypes, kernel.WaitForSingleObject.restype = (
        [pointer, integer],
        integer,
    )
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return None
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        values = [ctypes.c_uint64() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in values)):
            raise ctypes.WinError(ctypes.get_last_error())
        state = kernel.WaitForSingleObject(handle, 0)
        if state not in (0, 258):
            raise ctypes.WinError(ctypes.get_last_error())
        return {"pid": pid, "created_100ns": str(values[0].value), "running": state == 258}
    finally:
        kernel.CloseHandle(handle)


def starting_banner(log_path, endpoint):
    # The owned child prints this only after it has bound its exclusive listener.
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if (
            isinstance(value, dict)
            and value.get("status") == "starting"
            and value.get("endpoint") == endpoint
        ):
            return True
    return False


async def inspect_child(child, state, log_path, endpoint, report):
    import httpx

    import kirabridge
    from kirabridge.mcp_gateway.client import MCPClientPool, Peer
    from kirabridge.private_files import private_json

    credential_file = state / "preview-credentials.json"
    deadline = time.monotonic() + 30
    credentials = None
    async with httpx.AsyncClient(trust_env=False) as http:
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError("Owned preview exited before readiness; inspect its private log")
            if credential_file.exists() and starting_banner(log_path, endpoint):
                try:
                    credentials = private_json(credential_file)
                    status = (await http.get(endpoint, timeout=1)).status_code
                except (ValueError, FileNotFoundError, httpx.HTTPError):
                    await asyncio.sleep(0.05)
                    continue
                if status == 401:
                    report["unauthenticated_http_status"] = status
                    break
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError("Owned preview did not become ready within 30 seconds")
    if (
        not isinstance(credentials, dict)
        or set(credentials) != {"schema", "local"}
        or credentials.get("schema") != "kirabridge.windows-preview.credentials.v1"
        or not isinstance(credentials.get("local"), str)
        or len(credentials["local"]) < 32
    ):
        raise RuntimeError("Fresh private preview credentials have an unexpected schema")
    report["credential_schema_verified"] = True
    async with MCPClientPool(call_timeout=10) as clients:
        await clients.connect(Peer("preview", url=endpoint, token=credentials["local"]))

        async def read(tool, arguments):
            begin = time.monotonic_ns()
            result = await clients.call("preview", tool, arguments)
            data = result.structuredContent
            report["tool_samples"].append(
                {"tool": tool, "elapsed_ms": (time.monotonic_ns() - begin) / 1e6}
            )
            if result.isError or not isinstance(data, dict) or data.get("error"):
                raise RuntimeError(f"Preview read failed: {tool}")
            return data

        health = await read("bridge_health", {})
        if health.get("version") != kirabridge.__version__ or not health.get("dispatcher_active"):
            raise RuntimeError("Preview version or dispatcher readiness differs from source")
        report["expected_version"] = kirabridge.__version__
        report["runtime_version"] = health["version"]
        report["runtime_pid"] = health["runtime"]["pid"]
        if report["runtime_pid"] != child.pid:
            raise RuntimeError("Health reply came from a different process")
        operations = ["windows.keyboard.inspect", "windows.keyboard.sequence"]
        catalog = await read("operation_catalog", {"operations": operations})
        rows = catalog.get("operations", {})
        if set(rows) != set(operations):
            raise RuntimeError("Explicit Windows operations are missing from preview catalog")
        for name in operations:
            platform = rows[name].get("platform", {})
            if (
                platform.get("host_platform") != "win32"
                or not platform.get("available")
                or not platform.get("eligible_for_submission")
            ):
                raise RuntimeError("Windows operation was not available in the real guest")
        report["windows_operations_available"] = operations
        tasks = await read("task_list", {})
        if tasks.get("tasks") != []:
            report["preserve_child_for_unexpected_tasks"] = True
            raise RuntimeError(
                "Health-only preview unexpectedly contains tasks; preserve for review"
            )
        report["owned_state_has_zero_tasks_before_stop"] = True
    credentials = None


def private_smoke_paths(report, *, persist):
    from kirabridge.bridge_core.config import private_directory

    # Native private_directory must create the object with its own protected DACL.
    # Python's mkdtemp(mode700) can create a different Windows owner/ACL first.
    root = Path(tempfile.gettempdir()) / ("kirabridge-preview-smoke-" + secrets.token_hex(16))
    state, log_path = root / "state", root / "owned-preview.log"
    report.update(
        {
            "stage": "creating_private_smoke_directory",
            "state_dir": str(state),
            "private_log": str(log_path),
            "owned_process_started": False,
        }
    )
    persist()
    if os.path.lexists(root):
        raise FileExistsError("Fresh smoke path already exists; never reuse or overwrite it")
    private_directory(root)
    report.update({"stage": "private_smoke_directory_ready", "state_retained": True})
    persist()
    return state, log_path


def run(report, *, persist):
    state, log_path = private_smoke_paths(report, persist=persist)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    endpoint = f"http://127.0.0.1:{port}/mcp"
    environment = os.environ.copy()
    source_root = Path(__file__).resolve().parents[1]
    environment["PYTHONPATH"] = str(source_root / "src")
    command = [
        sys.executable,
        "-m",
        "kirabridge.windows_preview",
        "--transport",
        "http",
        "--state-dir",
        str(state),
        "--port",
        str(port),
    ]
    child, original = None, None
    began = time.monotonic_ns()
    try:
        with log_path.open("xb") as log:
            report.update({"stage": "launching_preview_child", "owned_process_started": None})
            persist()  # A creation failure is not evidence that no child ever started.
            child = subprocess.Popen(
                command,
                cwd=source_root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            report.update({"stage": "pinning_preview_child", "owned_process_started": True})
            persist()
            original = process_snapshot(child.pid)
            if original is None or not original["running"]:
                raise RuntimeError("Owned preview exited before process identity could be pinned")
            report["owned_process"] = original
            report["stage"] = "inspecting_preview_child"
            persist()
            asyncio.run(inspect_child(child, state, log_path, endpoint, report))
    finally:
        if child is not None:
            if child.poll() is None and not report.get("preserve_child_for_unexpected_tasks"):
                try:
                    child.send_signal(signal.CTRL_BREAK_EVENT)
                    report["stop_method"] = "CTRL_BREAK requested for exact owned process group"
                    child.wait(timeout=8)
                except (OSError, subprocess.TimeoutExpired):
                    # No task was submitted by this smoke; no other VM/host process is targeted.
                    child.terminate()
                    report["stop_method"] = "TerminateProcess on retained owned Popen handle"
                    child.wait(timeout=8)
            report["exit_code"] = child.returncode
            observed = process_snapshot(child.pid)
            original_absent = (
                observed is None
                or not observed["running"]
                or original is not None
                and observed["created_100ns"] != original["created_100ns"]
            )
            report["independent_original_process_absent"] = original_absent
            if not original_absent:
                raise RuntimeError(
                    "Original preview process remains alive; no repeated stop attempted"
                )
        report["total_ms"] = (time.monotonic_ns() - began) / 1e6


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("Run only inside the Windows guest")
    try:
        output = arguments.output.open("x+", encoding="utf-8")
    except FileExistsError:
        parser.error("Original receipt already exists; reconcile it instead of restarting")
    report = {
        "scope": "Owned Windows preview child, real local authenticated MCP reads only",
        "passed": False,
        "tool_samples": [],
        "keyboard_events_requested": 0,
        "production_credentials_used": False,
        "state_retained": True,
        "service_installed": False,
        "cloud_latency_measured": False,
        "stage": "starting",
        "owned_process_started": False,
    }
    with output:

        def persist():
            output.seek(0)
            output.write(json.dumps(report, indent=2) + "\n")
            output.truncate()
            output.flush()
            os.fsync(output.fileno())

        persist()
        try:
            run(report, persist=persist)
            report["passed"] = True
            report["stage"] = "completed"
        except Exception as error:
            # Exception strings can contain tokens; retain only their type.
            report["error_type"] = type(error).__name__
            code = getattr(error, "code", None)
            if isinstance(code, str) and re.fullmatch(r"[a-z0-9_]{1,80}", code):
                report["error_code"] = code
        finally:
            persist()
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
