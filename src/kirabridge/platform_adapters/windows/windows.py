"""Guarded top-level Windows window requests; no input or foreground-lock bypass.

Requests are single attempts, not application acknowledgements. Win32 cannot bind
an HWND mutation atomically to a process generation: identity is rechecked as late
as possible, but destruction/reuse can still race the actual native call.
"""

from __future__ import annotations

import ctypes
import os
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Callable

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.platform_adapters.windows.keyboard import Win32KeyboardAPI

MAX_WINDOWS, MAX_ENUM_WINDOWS = 64, 4096
INT_MIN, INT_MAX = -(2**31), 2**31 - 1
MAX_DIMENSION = 32768
COORDINATE_SPACE = "physical_screen_pixels"
ACTIONS = frozenset({"activate", "minimize", "maximize", "restore", "move_resize", "close"})
CAUSE_CODES = frozenset(
    {
        "windows_window_request_unconfirmed",
        "windows_target_changed",
        "windows_target_not_top_level",
        "windows_target_unavailable",
        "windows_desktop_unavailable",
        "windows_desktop_changed",
        "windows_dpi_restore_failed",
        "windows_dpi_unavailable",
        "windows_window_enumeration_failed",
    }
)
SHOW_COMMANDS = {"minimize": 6, "maximize": 3, "restore": 9}
SWP_NOZORDER, SWP_NOACTIVATE, SWP_ASYNCWINDOWPOS = 0x0004, 0x0010, 0x4000
WM_CLOSE = 0x0010
DWORD, LONG, BOOL, POINTER = ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32, ctypes.c_void_p
ENUMPROC = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(BOOL, POINTER, ctypes.c_ssize_t)


class RECT(ctypes.Structure):
    _fields_ = [(name, LONG) for name in ("left", "top", "right", "bottom")]


@dataclass(frozen=True)
class WindowIdentity:
    hwnd: int
    pid: int
    process_created_100ns: int
    thread_id: int

    def __post_init__(self):
        for name, value in asdict(self).items():
            bits = 32 if name in {"pid", "thread_id"} else 64
            if type(value) is not int or not 0 < value < 2**bits:
                raise ValueError("Windows identity needs positive native-width integers")

    def to_wire(self):
        return {name: str(value) for name, value in asdict(self).items()}

    @classmethod
    def from_wire(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("All four exact Windows identity fields are required")
        fields = {}
        for name, text in value.items():
            if (
                not isinstance(text, str)
                or not text.isascii()
                or not text.isdecimal()
                or text.startswith("0")
                or len(text) > 20
            ):
                raise ValueError("Windows identity fields need canonical decimal strings")
            fields[name] = int(text)
        return cls(**fields)


@dataclass(frozen=True)
class WindowBounds:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self):
        if any(type(value) is not int for value in asdict(self).values()):
            raise ValueError("Window coordinates and dimensions must be strict integers")
        if not INT_MIN <= self.x <= INT_MAX or not INT_MIN <= self.y <= INT_MAX:
            raise ValueError("Window coordinates must fit signed Win32 integers")
        if not 1 <= self.width <= MAX_DIMENSION or not 1 <= self.height <= MAX_DIMENSION:
            raise ValueError("Window dimensions must be between 1 and 32768 pixels")
        if self.x + self.width > INT_MAX or self.y + self.height > INT_MAX:
            raise ValueError("Window rectangle must not overflow signed Win32 coordinates")

    @classmethod
    def from_value(cls, value):
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("move_resize needs exactly x, y, width and height")
        return cls(**value)


def _bind_window_functions(user, callback_type=ENUMPROC):
    """Explicit LLP64 ABI; importable/testable on a non-Windows LP64 host."""
    signatures = {
        "EnumWindows": ([callback_type, ctypes.c_ssize_t], BOOL),
        "EnumDesktopWindows": ([POINTER, callback_type, ctypes.c_ssize_t], BOOL),
        "GetAncestor": ([POINTER, DWORD], POINTER),
        "GetWindowRect": ([POINTER, ctypes.POINTER(RECT)], BOOL),
        "IsWindowVisible": ([POINTER], BOOL),
        "IsIconic": ([POINTER], BOOL),
        "IsZoomed": ([POINTER], BOOL),
        "GetWindowTextW": ([POINTER, ctypes.c_wchar_p, ctypes.c_int32], ctypes.c_int32),
        "GetClassNameW": ([POINTER, ctypes.c_wchar_p, ctypes.c_int32], ctypes.c_int32),
        "SetThreadDpiAwarenessContext": ([POINTER], POINTER),
        "SetForegroundWindow": ([POINTER], BOOL),
        "ShowWindowAsync": ([POINTER, ctypes.c_int32], BOOL),
        "SetWindowPos": (
            [
                POINTER,
                POINTER,
                ctypes.c_int32,
                ctypes.c_int32,
                ctypes.c_int32,
                ctypes.c_int32,
                DWORD,
            ],
            BOOL,
        ),
        "PostMessageW": ([POINTER, DWORD, ctypes.c_size_t, ctypes.c_ssize_t], BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(user, name)
        function.argtypes, function.restype = arguments, result


class WindowsWindowAPI:
    """Native boundary. Construction on macOS/Linux fails before loading DLLs."""

    def __init__(self):
        self._identity_api = Win32KeyboardAPI()
        self.user, self.kernel = self._identity_api.user, self._identity_api.kernel
        _bind_window_functions(self.user)

    def validate_desktop(self):
        self._identity_api.validate_desktop()

    @contextmanager
    def physical_coordinates(self):
        # GetWindowRect is otherwise DPI-virtualized. This changes only our thread.
        previous = self.user.SetThreadDpiAwarenessContext(POINTER(-4).value)
        if not previous:
            raise BridgeError("windows_dpi_unavailable", "Cannot select physical coordinates")
        try:
            yield
        finally:
            if not self.user.SetThreadDpiAwarenessContext(previous):
                raise BridgeError("windows_dpi_restore_failed", "Cannot restore thread DPI context")

    def _on_current_desktop(self, hwnd):
        desktop = self.user.GetThreadDesktop(self.kernel.GetCurrentThreadId())
        if not desktop:
            raise BridgeError("windows_desktop_unavailable", "Cannot inspect current desktop")
        found, stopped, count = False, False, 0

        def callback(candidate, _):
            nonlocal found, stopped, count
            count += 1
            found = candidate == hwnd
            stopped = found or count >= MAX_ENUM_WINDOWS
            return not stopped

        function = ENUMPROC(callback)
        if not self.user.EnumDesktopWindows(desktop, function, 0) and not stopped:
            raise BridgeError("windows_desktop_unavailable", "Cannot enumerate current desktop")
        if not found:
            raise BridgeError("windows_target_changed", "Target is not on the current desktop")

    def enumerate_windows(self, limit):
        handles, stopped, count = [], False, 0

        def callback(hwnd, _):
            nonlocal stopped, count
            count += 1
            if self.user.IsWindowVisible(hwnd) and self.user.GetAncestor(hwnd, 2) == hwnd:
                handles.append(int(hwnd))
            stopped = len(handles) > limit or count >= MAX_ENUM_WINDOWS
            return not stopped

        function = ENUMPROC(callback)
        if not self.user.EnumWindows(function, 0) and not stopped:
            raise BridgeError("windows_window_enumeration_failed", "Cannot enumerate windows")
        return handles[:limit], stopped

    def _identity(self, hwnd):
        if not self.user.IsWindow(hwnd):
            return None
        ancestor = self.user.GetAncestor(hwnd, 2)
        if ancestor != hwnd:
            if not ancestor and not self.user.IsWindow(hwnd):
                return None
            raise BridgeError(
                "windows_target_not_top_level", "Child windows are not control targets"
            )
        try:
            self._on_current_desktop(hwnd)
        except BridgeError as error:
            if error.code == "windows_target_changed" and not self.user.IsWindow(hwnd):
                return None
            raise
        pid = DWORD()
        thread = self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not thread or not pid.value:
            if not self.user.IsWindow(hwnd):
                return None
            raise BridgeError("windows_target_changed", "Window owner disappeared")
        try:
            created = self._identity_api._created(pid.value)
        except BridgeError as error:
            if error.code == "windows_target_unavailable" and not self.user.IsWindow(hwnd):
                return None
            raise
        current_pid = DWORD()
        current_thread = self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(current_pid))
        if (not current_thread or not current_pid.value) and not self.user.IsWindow(hwnd):
            return None
        if current_thread != thread or current_pid.value != pid.value:
            raise BridgeError("windows_target_changed", "Window owner changed during process query")
        return WindowIdentity(int(hwnd), pid.value, created, thread)

    def _confirmed_absence(self, hwnd):
        # A missing identity followed by a live handle is a contradiction, even
        # if a replacement window happens to have the same process/thread token.
        if self.user.IsWindow(hwnd):
            raise BridgeError(
                "windows_target_changed", "Window disappeared and reappeared during readback"
            )
        return None

    def snapshot(self, hwnd):
        target = self._identity(hwnd)
        if target is None:
            return self._confirmed_absence(hwnd)
        rectangle = RECT()
        if not self.user.GetWindowRect(hwnd, ctypes.byref(rectangle)):
            if not self.user.IsWindow(hwnd):
                return self._confirmed_absence(hwnd)
            raise BridgeError("windows_target_unavailable", "Cannot read window rectangle")
        title, kind = ctypes.create_unicode_buffer(513), ctypes.create_unicode_buffer(256)
        # GetWindowTextW does not wait for another process's hung window. For our
        # own process it can send WM_GETTEXT synchronously, so deliberately omit it.
        if target.pid != os.getpid():
            self.user.GetWindowTextW(hwnd, title, len(title))
        self.user.GetClassNameW(hwnd, kind, len(kind))
        state = {
            "target": target,
            "title": title.value,
            "title_omitted_for_same_process": target.pid == os.getpid(),
            "class_name": kind.value,
            "rect": {
                "x": rectangle.left,
                "y": rectangle.top,
                "width": rectangle.right - rectangle.left,
                "height": rectangle.bottom - rectangle.top,
            },
            "visible": bool(self.user.IsWindowVisible(hwnd)),
            "minimized": bool(self.user.IsIconic(hwnd)),
            "maximized": bool(self.user.IsZoomed(hwnd)),
            "foreground": self.user.GetForegroundWindow() == hwnd,
        }
        current = self._identity(hwnd)
        if current is None:
            return self._confirmed_absence(hwnd)
        if current != target:
            raise BridgeError(
                "windows_target_changed", "Window generation changed during inspection"
            )
        if not self.user.IsWindow(hwnd):
            return self._confirmed_absence(hwnd)
        return state

    def request(self, target, action, bounds):
        ctypes.set_last_error(0)
        if action == "activate":
            accepted = self.user.SetForegroundWindow(target.hwnd)
        elif action in SHOW_COMMANDS:
            accepted = self.user.ShowWindowAsync(target.hwnd, SHOW_COMMANDS[action])
        elif action == "move_resize":
            accepted = self.user.SetWindowPos(
                target.hwnd,
                None,
                bounds.x,
                bounds.y,
                bounds.width,
                bounds.height,
                SWP_NOZORDER | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS,
            )
        elif action == "close":
            accepted = self.user.PostMessageW(target.hwnd, WM_CLOSE, 0, 0)
        else:
            raise ValueError("Unsupported Windows window action")
        return bool(accepted), ctypes.get_last_error()


class WindowsWindows:
    def __init__(self, api=None):
        self.api = api if api is not None else WindowsWindowAPI()
        self._lock = threading.Lock()

    @contextmanager
    def _transaction(self):
        if not self._lock.acquire(blocking=False):
            raise BridgeError("windows_window_busy", "Another window operation is active")
        try:
            yield
        finally:
            self._lock.release()

    @staticmethod
    def _wire(state):
        return {**state, "target": state["target"].to_wire()}

    def _guard(self, target):
        self.api.validate_desktop()
        state = self.api.snapshot(target.hwnd)
        if state is None or state["target"] != target:
            raise BridgeError("windows_target_changed", "Exact top-level window identity changed")
        self.api.validate_desktop()
        return state

    def list(self, limit=32):
        if type(limit) is not int or not 1 <= limit <= MAX_WINDOWS:
            raise ValueError("Window limit must be an integer from 1 to 64")
        with self._transaction(), self.api.physical_coordinates():
            self.api.validate_desktop()
            handles, truncated = self.api.enumerate_windows(limit)
            windows, skipped = [], 0
            for hwnd in handles:
                self.api.validate_desktop()
                try:
                    state = self.api.snapshot(hwnd)
                except BridgeError as error:
                    if error.code not in {
                        "windows_target_changed",
                        "windows_target_unavailable",
                        "windows_target_not_top_level",
                    }:
                        raise
                    skipped += 1
                    continue
                if state is not None and state["visible"]:
                    windows.append(self._wire(state))
                else:
                    skipped += 1
            self.api.validate_desktop()
            return {
                "windows": windows,
                "limit": limit,
                "truncated": truncated,
                "skipped_unavailable": skipped,
                "coordinate_space": COORDINATE_SPACE,
                "effect_attempted": False,
            }

    def inspect(self, target):
        if not isinstance(target, WindowIdentity):
            raise ValueError("An exact WindowIdentity is required")
        with self._transaction(), self.api.physical_coordinates():
            return {
                **self._wire(self._guard(target)),
                "coordinate_space": COORDINATE_SPACE,
                "effect_attempted": False,
            }

    def control(
        self, target, action, *, bounds=None, before_effect: Callable[[], None] | None = None
    ):
        if not isinstance(target, WindowIdentity):
            raise ValueError("An exact WindowIdentity is required")
        if not isinstance(action, str) or action not in ACTIONS:
            raise ValueError("Unsupported Windows window action")
        if action == "move_resize":
            bounds = WindowBounds.from_value(bounds)
        elif bounds is not None:
            raise ValueError("Bounds apply only to move_resize")
        attempted, native_request_accepted = False, None
        with self._transaction():
            try:
                with self.api.physical_coordinates():
                    self._guard(target)
                    if before_effect is not None:
                        before_effect()
                    self._guard(target)
                    attempted = True
                    accepted, native_error = self.api.request(target, action, bounds)
                    native_request_accepted = accepted if type(accepted) is bool else None
                    if accepted is not True:
                        reason = (
                            "Windows may have denied foreground activation"
                            if action == "activate"
                            else "Windows did not confirm the asynchronous request"
                        )
                        raise BridgeError("windows_window_request_unconfirmed", reason)
                    self.api.validate_desktop()
                    after = self.api.snapshot(target.hwnd)
                    if after is not None and after["target"] != target:
                        raise BridgeError("windows_target_changed", "HWND was reused after request")
                    if after is None and action != "close":
                        raise BridgeError(
                            "windows_target_changed", "Window disappeared after request"
                        )
                    self.api.validate_desktop()
                    observed = self._observed(action, bounds, after)
                    result = {
                        "action": action,
                        "target": target.to_wire(),
                        "request_accepted": True,
                        "effect_attempted": True,
                        "observed": observed,
                        "outcome": "observed" if observed else "requested",
                        "observed_state": None if after is None else self._wire(after),
                        "native_error": native_error,
                        "coordinate_space": COORDINATE_SPACE,
                        "automatic_retry": False,
                        "scope": (
                            "Single request and immediate readback; no application acknowledgement"
                        ),
                    }
                return result
            except BaseException as error:
                if not attempted:
                    raise
                failure = UncertainExecution(
                    "windows_window_effect_unknown",
                    f"Window {action} was attempted but cannot be confirmed; "
                    "reconcile the original task, never replay automatically"
                    + ("; Windows may deny foreground activation" if action == "activate" else ""),
                )
                kind = "BridgeError" if isinstance(error, BridgeError) else "Exception"
                if type(error) in {
                    OSError,
                    RuntimeError,
                    TypeError,
                    ValueError,
                    TimeoutError,
                    AttributeError,
                    KeyError,
                    KeyboardInterrupt,
                    SystemExit,
                }:
                    kind = type(error).__name__
                code = error.code if isinstance(error, BridgeError) else None
                failure.provider_error = {
                    "native_request_accepted": native_request_accepted,
                    "cause_type": kind,
                    "cause_code": code if type(code) is str and code in CAUSE_CODES else None,
                }
                raise failure from error

    @staticmethod
    def _observed(action, bounds, state):
        if action == "close":
            return state is None
        if action == "activate":
            return state["foreground"]
        if action == "minimize":
            return state["minimized"]
        if action == "maximize":
            return state["maximized"] and not state["minimized"]
        if action == "restore":
            return state["visible"] and not state["minimized"] and not state["maximized"]
        return state["rect"] == asdict(bounds)
