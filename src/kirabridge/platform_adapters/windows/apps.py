"""Windows application launch and focus plans. No macOS process or bundle calls."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from kirabridge.bridge_core.models import BridgeError, UncertainExecution

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010
DETACHED_PROCESS = 0x00000008
CREATE_UNICODE_ENVIRONMENT = 0x00000400
STARTF_USESHOWWINDOW = 0x00000001
SW_SHOWNORMAL = 1
FORBIDDEN_LAUNCH_FLAGS = CREATE_NO_WINDOW | DETACHED_PROCESS


def quote_windows(arg: str) -> str:
    """Quote one CreateProcess argument using the Microsoft C runtime rules."""
    if not isinstance(arg, str) or "\x00" in arg or any(ord(char) < 32 for char in arg):
        raise ValueError("A Windows argument cannot contain NUL or ASCII controls")
    if arg == "":
        return '""'
    if not any(char in arg for char in ' \t"'):
        return arg
    quoted, slashes = ['"'], 0
    for char in arg:
        if char == "\\":
            slashes += 1
            continue
        if char == '"':
            quoted.append("\\" * (slashes * 2 + 1))
            quoted.append(char)
        else:
            quoted.append("\\" * slashes)
            quoted.append(char)
        slashes = 0
    quoted.append("\\" * (slashes * 2))
    quoted.append('"')
    return "".join(quoted)


def windows_image(image: str) -> str:
    if (
        not isinstance(image, str)
        or not len(image) >= 8
        or len(image) > 260
        or "\x00" in image
        or not image.endswith(".exe")
        or image[1:3] != ":\\"
        or not image[0].isascii()
        or not image[0].isalpha()
    ):
        raise ValueError("Use one absolute Windows .exe path")
    parts = image.split("\\")
    if any(part in {"", ".", ".."} for part in parts[1:]):
        raise ValueError("The application path cannot contain empty or parent segments")
    if any(char in image for char in '<>"|?*'):
        raise ValueError("The application path contains a forbidden Windows character")
    return image


def launch_plan(image: str, argv: tuple[str, ...] = (), *, console: bool = False) -> dict:
    """A shown CreateProcess plan. CREATE_NO_WINDOW and detached launch are refused."""
    image = windows_image(image)
    if type(console) is not bool:
        raise ValueError("console must be a boolean")
    if not isinstance(argv, tuple) or len(argv) > 8:
        raise ValueError("Launch accepts at most eight extra arguments")
    command = " ".join(quote_windows(part) for part in (image, *argv))
    if len(command) > 8192:
        raise ValueError("The Windows command line exceeds 8192 characters")
    flags = CREATE_UNICODE_ENVIRONMENT | (CREATE_NEW_CONSOLE if console else 0)
    if flags & FORBIDDEN_LAUNCH_FLAGS:
        raise ValueError("A hidden or detached launch is not a visible application start")
    return {
        "image": image,
        "argv": (image, *argv),
        "command_line": command,
        "creation_flags": flags,
        "show": SW_SHOWNORMAL,
        "startup_flags": STARTF_USESHOWWINDOW,
        "console": console,
        "hidden": False,
        "inherits_handles": False,
    }


def assert_visible_plan(plan: dict) -> None:
    flags = plan["creation_flags"]
    if (
        flags & FORBIDDEN_LAUNCH_FLAGS
        or plan["show"] != SW_SHOWNORMAL
        or plan["hidden"]
        or plan["inherits_handles"]
    ):
        raise BridgeError("windows_launch_hidden", "Refusing a hidden Windows application launch")


class Win32ProcessLauncher:
    """CreateProcessW with a normal shown window. Constructed only on Windows."""

    def __init__(self):
        if sys.platform != "win32":
            raise BridgeError("unsupported_platform", "Windows application launch requires Windows")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateProcessW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.LPCWSTR,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.kernel.CreateProcessW.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.kernel.GetProcessTimes.restype = wintypes.BOOL

    def launch(self, plan: dict) -> dict:
        assert_visible_plan(plan)
        startup = _STARTUPINFOW()
        startup.cb = ctypes.sizeof(startup)
        startup.dwFlags = plan["startup_flags"]
        startup.wShowWindow = plan["show"]
        process = _PROCESS_INFORMATION()
        command = ctypes.create_unicode_buffer(plan["command_line"])
        created = self.kernel.CreateProcessW(
            plan["image"],
            command,
            None,
            None,
            False,
            plan["creation_flags"],
            None,
            None,
            ctypes.byref(startup),
            ctypes.byref(process),
        )
        if not created or not process.dwProcessId:
            raise BridgeError(
                "windows_app_launch_failed", "CreateProcess did not start the application"
            )
        try:
            created_100ns = self._created(process.hProcess)
        except Exception as error:
            raise UncertainExecution(
                "windows_app_launch_unknown",
                "The process was created but its identity was not read; do not launch again",
            ) from error
        finally:
            if process.hThread:
                self.kernel.CloseHandle(process.hThread)
            if process.hProcess:
                self.kernel.CloseHandle(process.hProcess)
        return {
            "pid": str(int(process.dwProcessId)),
            "process_created_100ns": str(created_100ns),
            "image": plan["image"],
            "visible_requested": True,
            "creation_flags": plan["creation_flags"],
            "application_processing_confirmed": False,
            "automatic_retry": False,
        }

    def _created(self, handle) -> int:
        creation, exit_time, kernel, user = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
        if not self.kernel.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            raise OSError("GetProcessTimes failed")
        return (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]
