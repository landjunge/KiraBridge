"""Guest-only window acceptance: owned HWNDs, authenticated MCP, independent Win32 reads.

Every effect has one durable task ID and is submitted once. Asynchronous native
requests are observed, never resubmitted. The auxiliary owned top-level window
exists only to exercise an actual foreground transition and a stale identity.
No keys, clipboard, foreign window control, production state or focus-lock bypass.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import importlib.util
import json
import os
import secrets
import socket
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

IDENTITY = ("hwnd", "pid", "process_created_100ns", "thread_id")
TERMINAL = {"completed", "failed", "unknown", "cancelled", "blocked", "withdrawn"}


def aggregate_attempts(report):
    values = [item["effect_attempted"] for item in report["window_effect_attempts"]]
    report["effect_attempted"] = True if True in values else None if None in values else False


def instrument_windows(backend, report, persist):
    """Conservative test observations; a hook is not a receiver acknowledgement."""
    from kirabridge.bridge_core.models import BridgeError, UncertainExecution

    original = backend.control

    def observed(target, action, *, bounds=None, before_effect=None):
        item = report["window_effect_attempts"][-1]
        item["control_backend_entered"] = True
        item["state"] = "backend_entered"
        persist()

        def hook():
            item["before_effect_hooks"] += 1
            item["effect_attempted"] = True
            item["state"] = "before_native_request"
            aggregate_attempts(report)
            persist()
            if before_effect is not None:
                before_effect()

        try:
            result = original(target, action, bounds=bounds, before_effect=hook)
            item["native_request_accepted"] = result.get("request_accepted")
            item["state"] = "native_returned"
            return result
        except BridgeError as error:
            if not item["before_effect_hooks"] and not isinstance(error, UncertainExecution):
                item["effect_attempted"] = False
            item["state"] = (
                "refused_before_effect" if item["effect_attempted"] is False else "unknown_no_retry"
            )
            raise
        finally:
            aggregate_attempts(report)
            persist()

    backend.control = observed


def reconcile_stale_precontrol(item, task, *, window_unchanged):
    """A terminal manager inspect refusal may precede backend.control entirely."""
    if (
        item["effect_attempted"] is None
        and item["control_backend_entered"] is False
        and item["before_effect_hooks"] == 0
        and task.get("state") == "failed"
        and (task.get("error") or {}).get("code") == "windows_target_changed"
        and window_unchanged
    ):
        item["effect_attempted"] = False
        item["state"] = "manager_inspect_refused_before_control"
        return True
    return False


def cleanup_can_close(report):
    return not any(
        item["effect_attempted"] is not False and item["state"] != "independently_observed"
        for item in report["window_effect_attempts"]
    )


class NativeReadback:
    """Independent OS reader. Does not call the backend or any mutation API."""

    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("Native window acceptance requires the interactive Windows guest")
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        P, U, INT = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32

        class POINT(ctypes.Structure):
            _fields_ = [("x", INT), ("y", INT)]

        class RECT(ctypes.Structure):
            _fields_ = [(key, INT) for key in ("left", "top", "right", "bottom")]

        class PLACEMENT(ctypes.Structure):
            _fields_ = [
                ("length", U),
                ("flags", U),
                ("showCmd", U),
                ("ptMinPosition", POINT),
                ("ptMaxPosition", POINT),
                ("rcNormalPosition", RECT),
            ]

        self.RECT, self.PLACEMENT = RECT, PLACEMENT
        signatures = {
            "IsWindow": ([P], INT),
            "IsWindowVisible": ([P], INT),
            "IsIconic": ([P], INT),
            "IsZoomed": ([P], INT),
            "GetForegroundWindow": ([], P),
            "GetWindowThreadProcessId": ([P, ctypes.POINTER(U)], U),
            "GetWindowRect": ([P, ctypes.POINTER(RECT)], INT),
            "GetWindowPlacement": ([P, ctypes.POINTER(PLACEMENT)], INT),
            "SetThreadDpiAwarenessContext": ([P], P),
            "SystemParametersInfoW": ([U, U, P, U], INT),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.user, name)
            function.argtypes, function.restype = arguments, result
        self.kernel.OpenProcess.argtypes, self.kernel.OpenProcess.restype = [U, INT, U], P
        self.kernel.GetProcessTimes.argtypes = [P] + [ctypes.POINTER(ctypes.c_uint64)] * 4
        self.kernel.GetProcessTimes.restype = INT
        self.kernel.CloseHandle.argtypes, self.kernel.CloseHandle.restype = [P], INT

    @contextmanager
    def physical(self):
        previous = self.user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4).value)
        if not previous:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            if not self.user.SetThreadDpiAwarenessContext(previous):
                raise ctypes.WinError(ctypes.get_last_error())

    def created(self, pid):
        handle = self.kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            times = [ctypes.c_uint64() for _ in range(4)]
            if not self.kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
                raise ctypes.WinError(ctypes.get_last_error())
            return str(times[0].value)
        finally:
            self.kernel.CloseHandle(handle)

    @staticmethod
    def rectangle(rect):
        return {
            "x": rect.left,
            "y": rect.top,
            "width": rect.right - rect.left,
            "height": rect.bottom - rect.top,
        }

    def snapshot(self, hwnd):
        if not self.user.IsWindow(hwnd):
            return {"exists": False, "hwnd": str(hwnd)}
        pid = ctypes.c_uint32()
        thread = self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        created = self.created(pid.value)
        rect, placement = self.RECT(), self.PLACEMENT()
        placement.length = ctypes.sizeof(placement)
        with self.physical():
            if not self.user.GetWindowRect(hwnd, ctypes.byref(rect)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not self.user.GetWindowPlacement(hwnd, ctypes.byref(placement)):
                raise ctypes.WinError(ctypes.get_last_error())
        # A read racing destruction/reuse is an observation failure, not absence.
        again = ctypes.c_uint32()
        if (
            not self.user.IsWindow(hwnd)
            or self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(again)) != thread
            or again.value != pid.value
            or self.created(again.value) != created
        ):
            raise RuntimeError("Owned window identity changed during independent readback")
        return {
            "exists": True,
            "target": {
                "hwnd": str(hwnd),
                "pid": str(pid.value),
                "process_created_100ns": created,
                "thread_id": str(thread),
            },
            "rect": self.rectangle(rect),
            "visible": bool(self.user.IsWindowVisible(hwnd)),
            "minimized": bool(self.user.IsIconic(hwnd)),
            "maximized": bool(self.user.IsZoomed(hwnd)),
            "foreground": self.user.GetForegroundWindow() == hwnd,
            "placement_show_command": int(placement.showCmd),
            "coordinate_space": "physical_screen_pixels",
        }

    def bounds(self):
        rect = self.RECT()
        with self.physical():
            if not self.user.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0):
                raise ctypes.WinError(ctypes.get_last_error())
        if rect.right - rect.left < 300 or rect.bottom - rect.top < 220:
            raise RuntimeError("Owned window test needs a visible desktop work area")
        return {
            "x": rect.left + 40,
            "y": rect.top + 40,
            "width": min(640, rect.right - rect.left - 80),
            "height": min(320, rect.bottom - rect.top - 80),
        }


def receiver_class():
    source = Path(__file__).with_name("accept_windows_keyboard.py")
    spec = importlib.util.spec_from_file_location("kirabridge_owned_window_receiver", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("Owned receiver support missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Receiver


def new_fixture():
    class OwnedWindows(receiver_class()):
        def __init__(self):
            self.window_messages, self.auxiliary = [], None
            super().__init__()

        def _window_proc(self, hwnd, message, wparam, lparam):
            if message in (0x0010, 0x0002, 0x0003, 0x0005):
                with self.lock:
                    self.window_messages.append(
                        {
                            "hwnd": str(hwnd),
                            "message": message,
                            "at_monotonic_ns": time.monotonic_ns(),
                        }
                    )
            if message == 0x0002:
                if hwnd == self.hwnd:
                    self.user.PostQuitMessage(0)
                return 0
            return super()._window_proc(hwnd, message, wparam, lparam)

        def ui_call(self, callback):
            results, errors, done = [], [], threading.Event()

            def execute():
                try:
                    results.append(callback())
                except Exception as error:
                    errors.append(error)

            self.tasks.put((execute, done))
            if not self.user.PostMessageW(self.hwnd, 0x8001, 0, 0) or not done.wait(5):
                raise RuntimeError("Owned UI setup request not acknowledged; never repeat")
            if errors:
                raise errors[0]
            return results[0]

        def create_auxiliary(self):
            def create():
                value = self.user.CreateWindowExW(
                    0,
                    self.class_name,
                    "KiraBridge owned auxiliary window",
                    0x00CF0000,
                    150,
                    160,
                    420,
                    180,
                    None,
                    None,
                    self.instance,
                    None,
                )
                if not value:
                    raise RuntimeError("Cannot create owned auxiliary window")
                self.auxiliary = int(value)
                self.user.ShowWindow(value, 5)
                # Setup only: normal activation of the auxiliary. The tested
                # activation of main is performed solely by the backend.
                self.user.SetForegroundWindow(value)
                return self.auxiliary

            return self.ui_call(create)

        def run(self):
            self.class_name = f"KiraBridgeWindowFixture_{os.getpid()}"
            self.instance = self.kernel.GetModuleHandleW(None)
            kind = self.WNDCLASSEX()
            kind.cbSize = ctypes.sizeof(kind)
            kind.lpfnWndProc, kind.hInstance = self.callback, self.instance
            kind.lpszClassName, kind.hbrBackground = self.class_name, 6
            if not self.user.RegisterClassExW(ctypes.byref(kind)):
                raise RuntimeError("Cannot register owned window fixture")
            self.hwnd = self.user.CreateWindowExW(
                0,
                self.class_name,
                f"KiraBridge WINDOWS TEST PID {os.getpid()}",
                0x00CF0000,
                100,
                100,
                660,
                340,
                None,
                None,
                self.instance,
                None,
            )
            if not self.hwnd:
                raise RuntimeError("Cannot create owned main window")
            self.user.ShowWindow(self.hwnd, 5)
            self.user.SetForegroundWindow(self.hwnd)
            self.ready.set()
            message = self.MSG()
            while True:
                value = self.user.GetMessageW(ctypes.byref(message), None, 0, 0)
                if value == 0:
                    break
                if value == -1:
                    raise RuntimeError("Owned window message loop failed")
                self.user.TranslateMessage(ctypes.byref(message))
                self.user.DispatchMessageW(ctypes.byref(message))
            # No keyboard layout is loaded, activated, changed or restored.

    return OwnedWindows()


def checked_snapshot(probe, target, *, allow_absent=False):
    state = probe.snapshot(int(target["hwnd"]))
    if not state["exists"]:
        if allow_absent:
            return state
        raise RuntimeError("Original owned window disappeared")
    if state["target"] != target or target["pid"] != str(os.getpid()):
        raise RuntimeError("Independent HWND owner/generation differs; no foreign control")
    return state


async def observe(
    probe,
    target,
    predicate,
    *,
    allow_absent=False,
    timeout=4,
    clock=time.monotonic,
    pause=asyncio.sleep,
):
    deadline = clock() + timeout
    while True:
        state = checked_snapshot(probe, target, allow_absent=allow_absent)
        if predicate(state):
            return state
        if clock() >= deadline:
            raise RuntimeError("Native window request was not independently observed; never replay")
        await pause(0.02)


async def run_mcp(fixture, probe, report, persist):
    import httpx
    import uvicorn

    from kirabridge.bridge_core.bridge import Bridge
    from kirabridge.bridge_core.config import Config, PrincipalConfig, private_directory
    from kirabridge.mcp_gateway.client import MCPClientPool, Peer
    from kirabridge.mcp_gateway.http import create_http_app

    nonce = secrets.token_hex(8)
    environment_key = "KIRABRIDGE_WINDOW_ACCEPTANCE_" + nonce.upper()
    if environment_key in os.environ:
        raise RuntimeError("Fresh authentication environment already exists")
    token = secrets.token_urlsafe(48)
    os.environ[environment_key] = token
    root = Path(tempfile.gettempdir()) / ("kirabridge-window-acceptance-" + secrets.token_hex(16))
    private_directory(root)
    report["isolated_state_dir"] = str(root / "state")
    policy = PrincipalConfig(
        approval_mode="automatic",
        client_type="operator",
        token_env=environment_key,
        capabilities=[
            "bridge.health",
            "task.read",
            "windows.window.list",
            "windows.window.control",
        ],
    )
    config = Config(data_dir=str(root / "state"), concurrency=1, principals={"local": policy})
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(64)
    config.port = sock.getsockname()[1]
    endpoint = f"http://127.0.0.1:{config.port}/mcp"
    serving, server = None, None
    try:
        bridge = Bridge(config)
        instrument_windows(bridge.windows_windows.require(), report, persist)
        app = create_http_app(bridge)
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
        async with bridge:
            serving = asyncio.create_task(server.serve(sockets=[sock]))
            try:
                async with asyncio.timeout(10):
                    while not server.started:
                        if serving.done():
                            await serving
                            raise RuntimeError("Owned MCP server stopped before readiness")
                        await asyncio.sleep(0.01)
                async with httpx.AsyncClient(trust_env=False) as client:
                    report["unauthenticated_http_status"] = (
                        await client.get(endpoint, timeout=3)
                    ).status_code
                if report["unauthenticated_http_status"] != 401:
                    raise RuntimeError("Unauthenticated window MCP was not refused")
                async with MCPClientPool(call_timeout=15) as clients:
                    await clients.connect(Peer("windows", url=endpoint, token=token))

                    async def call(tool, arguments):
                        reply = await clients.call("windows", tool, arguments)
                        if reply.isError or not isinstance(reply.structuredContent, dict):
                            raise RuntimeError(
                                "Local MCP tool/transport error; original ID must be reconciled"
                            )
                        return reply.structuredContent

                    async def submit(operation, arguments, label, effect=False):
                        task_id = "win_window_" + nonce + "_" + label
                        item = {
                            "task_id": task_id,
                            "operation": operation,
                            "label": label,
                            "state": "submitting_once",
                            "effect_attempted": None if effect else False,
                            "before_effect_hooks": 0,
                            "native_request_accepted": None,
                            "control_backend_entered": False,
                        }
                        report["task_requests"].append(item)
                        if effect:
                            report["window_effect_attempts"].append(item)
                            aggregate_attempts(report)
                        persist()  # Durable original ID before tool handoff.
                        began = time.monotonic_ns()
                        task = await call(
                            "task_request",
                            {
                                "request": {
                                    "task_id": task_id,
                                    "idempotency_key": task_id,
                                    "operation": operation,
                                    "arguments": arguments,
                                }
                            },
                        )
                        deadline = time.monotonic() + 8
                        while not task.get("error") and task.get("state") not in TERMINAL:
                            if time.monotonic() >= deadline:
                                raise RuntimeError(
                                    "Original window task unresolved; no replacement or retry"
                                )
                            await asyncio.sleep(0.02)
                            task = await call("task_get", {"task_id": task_id})
                        item["task_state"] = task.get("state")
                        item["error_code"] = (task.get("error") or {}).get("code")
                        item["elapsed_ms"] = (time.monotonic_ns() - began) / 1e6
                        persist()
                        return task, item

                    async def listed(label, hwnd):
                        task, _ = await submit("windows.window.list", {"limit": 64}, label)
                        if task.get("state") != "completed":
                            raise RuntimeError("Window list did not complete")
                        rows = [
                            row
                            for row in task["result"]["windows"]
                            if row["target"]["hwnd"] == str(hwnd)
                        ]
                        if len(rows) != 1:
                            raise RuntimeError("Exact owned window was not uniquely listed")
                        target = rows[0]["target"]
                        if set(target) != set(IDENTITY) or any(
                            not isinstance(target[key], str) for key in IDENTITY
                        ):
                            raise RuntimeError(
                                "Native identity lost canonical decimal-string contract"
                            )
                        checked_snapshot(probe, target)
                        return target

                    target = await listed("list_main", fixture.hwnd)
                    initial = checked_snapshot(probe, target)
                    report["initial_independent_state"] = initial
                    bounds = probe.bounds()

                    async def control(
                        action, label, predicate, *, requested_bounds=None, absent=False
                    ):
                        before = checked_snapshot(probe, target)
                        arguments = {"target": target, "action": action}
                        if requested_bounds is not None:
                            arguments["bounds"] = requested_bounds
                        task, item = await submit("windows.window.control", arguments, label, True)
                        item["native_backend_result"] = task.get("result")
                        persist()
                        if task.get("state") != "completed":
                            if action == "activate":
                                report["os_foreground_constraint"] = {
                                    "error_code": item["error_code"],
                                    "scope": (
                                        "Normal SetForegroundWindow may be denied; "
                                        "no lock bypass or retry"
                                    ),
                                }
                            raise RuntimeError(
                                "Window control did not complete; "
                                "original task retained without retry"
                            )
                        if item["before_effect_hooks"] != 1 or item["effect_attempted"] is not True:
                            raise RuntimeError("Missing conservative before-effect evidence")
                        after = await observe(probe, target, predicate, allow_absent=absent)
                        item["state"] = "independently_observed"
                        report["cases"].append(
                            {
                                "name": label,
                                "task_id": item["task_id"],
                                "before": before,
                                "after": after,
                                "backend_observed": task["result"].get("observed"),
                                "independent_os_readback": True,
                            }
                        )
                        persist()
                        return after

                    await control(
                        "move_resize",
                        "move_resize",
                        lambda state: state["rect"] == bounds,
                        requested_bounds=bounds,
                    )
                    await control(
                        "maximize",
                        "maximize",
                        lambda state: state["maximized"] and not state["minimized"],
                    )

                    def normal(state):
                        return (
                            not state["maximized"]
                            and not state["minimized"]
                            and state["rect"] == bounds
                        )

                    await control("restore", "restore_from_maximized", normal)
                    await control("minimize", "minimize", lambda state: state["minimized"])
                    if await listed("list_minimized", fixture.hwnd) != target:
                        raise RuntimeError("Minimized HWND identity changed")
                    await control("restore", "restore_from_minimized", normal)

                    auxiliary = await asyncio.to_thread(fixture.create_auxiliary)
                    auxiliary_target = await listed("list_auxiliary", auxiliary)
                    await observe(probe, auxiliary_target, lambda state: state["foreground"])
                    if checked_snapshot(probe, target)["foreground"]:
                        raise RuntimeError(
                            "Activation transition setup did not leave main nonforeground"
                        )
                    await control(
                        "activate",
                        "activate_from_owned_auxiliary",
                        lambda state: state["foreground"],
                    )
                    # Own fixture setup closes auxiliary once, then waits for
                    # real disappearance. A stale token must never reach Win32.
                    if not fixture.user.PostMessageW(auxiliary, 0x0010, 0, 0):
                        raise RuntimeError("Cannot request own auxiliary WM_CLOSE")
                    await observe(
                        probe,
                        auxiliary_target,
                        lambda state: not state["exists"],
                        allow_absent=True,
                    )
                    stable = checked_snapshot(probe, target)
                    stale, item = await submit(
                        "windows.window.control",
                        {"target": auxiliary_target, "action": "move_resize", "bounds": bounds},
                        "stale_auxiliary",
                        True,
                    )
                    stable_after_stale = checked_snapshot(probe, target) == stable
                    reconcile_stale_precontrol(item, stale, window_unchanged=stable_after_stale)
                    aggregate_attempts(report)
                    persist()
                    if (
                        (stale.get("error") or {}).get("code") != "windows_target_changed"
                        or item["before_effect_hooks"] != 0
                        or item["effect_attempted"] is not False
                        or not stable_after_stale
                    ):
                        raise RuntimeError("Stale auxiliary did not prove a pre-effect refusal")
                    report["stale_target_control"] = {
                        "task_id": item["task_id"],
                        "error_code": item["error_code"],
                        "before_effect_hooks": 0,
                        "effect_attempted": False,
                        "independent_main_unchanged": True,
                    }

                    config.principals["local"].capabilities.remove("windows.window.control")
                    forbidden, item = await submit(
                        "windows.window.control",
                        {"target": target, "action": "move_resize", "bounds": bounds},
                        "forbidden",
                        True,
                    )
                    count = bridge.store.db.execute(
                        "SELECT count(*) FROM tasks WHERE id=?", (item["task_id"],)
                    ).fetchone()[0]
                    if (
                        (forbidden.get("error") or {}).get("code") != "forbidden"
                        or count != 0
                        or item["before_effect_hooks"] != 0
                        or item["control_backend_entered"] is not False
                        or checked_snapshot(probe, target) != stable
                    ):
                        raise RuntimeError(
                            "Forbidden control admitted work or changed own receiver"
                        )
                    item["effect_attempted"], item["state"] = False, "forbidden_not_admitted"
                    aggregate_attempts(report)
                    report["forbidden_control"] = {
                        "task_id": item["task_id"],
                        "error_code": "forbidden",
                        "persisted_tasks": 0,
                        "before_effect_hooks": 0,
                        "effect_attempted": False,
                        "independent_main_unchanged": True,
                    }
                    config.principals["local"].capabilities.append("windows.window.control")
                    persist()
                    await control(
                        "close", "close_wm_close", lambda state: not state["exists"], absent=True
                    )
                    with fixture.lock:
                        close_messages = [
                            row for row in fixture.window_messages if row["message"] == 0x0010
                        ]
                        keys = list(fixture.events)
                    if keys or sum(row["hwnd"] == target["hwnd"] for row in close_messages) != 1:
                        raise RuntimeError(
                            "Own receiver did not acknowledge one WM_CLOSE and zero keys"
                        )
                    report["wm_close_receiver_ack"] = close_messages
                    report["keyboard_events_received"] = len(keys)
                    report["original_main_window_absent"] = not probe.snapshot(fixture.hwnd)[
                        "exists"
                    ]
                    if not report["original_main_window_absent"]:
                        raise RuntimeError(
                            "Original HWND was reused after close; absence is not confirmed"
                        )
            finally:
                server.should_exit = True
                if serving is not None:
                    await asyncio.wait_for(serving, 10)
    finally:
        sock.close()
        os.environ.pop(environment_key, None)


def worker(fixture, output):
    report = {
        "scope": (
            "Owned Windows HWNDs through real authenticated local MCP and independent Win32 reads"
        ),
        "passed": False,
        "platform": os.name,
        "clipboard_used": False,
        "keyboard_events_requested": 0,
        "host_mac_input": False,
        "production_credentials_used": False,
        "automatic_effect_retry": False,
        "fixture_setup_scope": (
            "Only own HWND creation/show/normal initial activation, "
            "auxiliary activation/WM_CLOSE and final cleanup; "
            "separate from backend effect attempts"
        ),
        "effect_attempted": False,
        "window_effect_attempts": [],
        "task_requests": [],
        "cases": [],
    }
    lock = threading.RLock()

    def persist():
        with lock:
            fixture.save_report(output, report)

    try:
        persist()
        if not fixture.ready.wait(5):
            raise RuntimeError("Owned window fixture not ready")
        asyncio.run(run_mcp(fixture, NativeReadback(), report, persist))
        report["passed"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        if hasattr(error, "provider_error"):
            report["provider_error"] = error.provider_error
    finally:
        # Cleanup is separate from the tested backend and never retries an
        # uncertain control. Queue auxiliary first so its UI thread destroys it
        # before main's WM_DESTROY ends the message loop.
        if not cleanup_can_close(report):
            report["passed"] = False
            report["cleanup_original_windows_absent"] = None
            report["cleanup_withheld_for_unresolved_effects"] = True
            report["state"] = "unknown_preserve_owned_fixture_no_retry"
            persist()
        else:
            try:
                handles = [value for value in (fixture.auxiliary, fixture.hwnd) if value]
                for hwnd in handles:
                    if fixture.user.IsWindow(hwnd):
                        pid = ctypes.c_uint32()
                        fixture.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        if pid.value != os.getpid():
                            raise RuntimeError("Cleanup target no longer belongs to own process")
                        if not fixture.user.PostMessageW(hwnd, 0x0010, 0, 0):
                            raise RuntimeError("Own cleanup WM_CLOSE request was not accepted")
                deadline = time.monotonic() + 3
                while (
                    any(fixture.user.IsWindow(hwnd) for hwnd in handles)
                    and time.monotonic() < deadline
                ):
                    threading.Event().wait(0.02)
                report["cleanup_original_windows_absent"] = all(
                    not fixture.user.IsWindow(hwnd) for hwnd in handles
                )
                if not report["cleanup_original_windows_absent"]:
                    report["passed"] = False
                    report["cleanup_error"] = "Owned HWND absence was not confirmed; no retry"
            except Exception as error:
                report["passed"] = False
                report["cleanup_error"] = f"{type(error).__name__}: {error}"
            finally:
                persist()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("Run only in the interactive Windows guest")
    try:
        output = arguments.output.open("x+", encoding="utf-8")
    except FileExistsError:
        parser.error("Output exists; reconcile that original run instead of repeating effects")
    with output:
        output.write(
            '{"state":"started","passed":false,"effect_attempted":false,"automatic_effect_retry":false}\n'
        )
        output.flush()
        os.fsync(output.fileno())
        fixture = new_fixture()
        thread = threading.Thread(target=worker, args=(fixture, output), daemon=True)
        thread.start()
        fixture.run()
        thread.join(timeout=20)
        if thread.is_alive() or fixture.error:
            raise SystemExit(fixture.error or "Owned window worker did not stop")
    report = json.loads(arguments.output.read_text(encoding="utf-8"))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
