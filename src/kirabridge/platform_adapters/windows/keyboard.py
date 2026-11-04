"""Explicit Windows input: bounded real key pairs, pinned foreground, no clipboard.

This module has no macOS effect and does not reinterpret macOS key codes. Native
construction requires Windows; tests inject a Win32-shaped API. A successful
SendInput return proves insertion, never that an application processed a key.
"""

from __future__ import annotations

import ctypes
import os
import secrets
import threading
from dataclasses import asdict, dataclass
from typing import Callable

from kirabridge.bridge_core.models import BridgeError, UncertainExecution

KEYUP, UNICODE, SCANCODE, EXTENDED = 0x0002, 0x0004, 0x0008, 0x0001
MAX_KEYS = 32
MODIFIER_VKS = {"control": 0xA2, "alt": 0xA4, "shift": 0xA0, "windows": 0x5B}
MODIFIER_ORDER = ("control", "alt", "shift", "windows")
MODIFIER_SIDES = {
    0xA0: "left_shift",
    0xA1: "right_shift",
    0xA2: "left_control",
    0xA3: "right_control",
    0xA4: "left_alt",
    0xA5: "right_alt",
    0x5B: "left_windows",
    0x5C: "right_windows",
}
NAMED_KEYS = {
    "enter": 0x0D,
    "keypad_enter": 0x0D,
    "escape": 0x1B,
    "tab": 0x09,
    "space": 0x20,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "home": 0x24,
    "end": 0x23,
    "page_up": 0x21,
    "page_down": 0x22,
    "caps_lock": 0x14,
    "num_lock": 0x90,
    "scroll_lock": 0x91,
    "print_screen": 0x2C,
    "pause": 0x13,
    "keypad_decimal": 0x6E,
    "keypad_multiply": 0x6A,
    "keypad_plus": 0x6B,
    "keypad_divide": 0x6F,
    "keypad_minus": 0x6D,
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
    **{f"keypad_{i}": 0x60 + i for i in range(10)},
}
# These dedicated enhanced-key identities differ from numeric-keypad keys with
# the same low scan byte. Keep E0 even if a layout mapping reports only that byte.
# NumLock/Pause and explicit raw scan codes keep their separate existing framing.
EXTENDED_NAMED_KEYS = frozenset(
    {
        "left",
        "right",
        "up",
        "down",
        "home",
        "end",
        "page_up",
        "page_down",
        "insert",
        "delete",
        "print_screen",
        "keypad_divide",
        "keypad_enter",
    }
)


@dataclass(frozen=True)
class WindowTarget:
    hwnd: int
    pid: int
    process_created_100ns: int
    thread_id: int
    keyboard_layout: int

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in asdict(self).values()):
            raise ValueError("Windows target identity fields must be positive integers")
        for name, value in asdict(self).items():
            bits = 32 if name in ("pid", "thread_id") else 64
            if value >= 1 << bits:
                raise ValueError("Windows target identity exceeds its native integer width")

    def to_wire(self):
        """Opaque handles and FILETIME remain exact across JavaScript JSON clients."""
        return {
            name: value if name in ("pid", "thread_id") else str(value)
            for name, value in asdict(self).items()
        }

    @classmethod
    def from_wire(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("All exact Windows target identity fields are required")
        fields = dict(value)
        for name in ("hwnd", "process_created_100ns", "keyboard_layout"):
            text = fields[name]
            if (
                not isinstance(text, str)
                or not text.isascii()
                or not text.isdecimal()
                or text.startswith("0")
                or len(text) > 20
            ):
                raise ValueError("Opaque Windows target fields need canonical decimal strings")
            fields[name] = int(text)
        return cls(**fields)


@dataclass(frozen=True)
class KeyStroke:
    """One layout base label/named key/scancode, or explicitly Unicode input.

    Character case alone never adds Shift. Layout-required modifiers (e.g. Shift
    for '!' or Ctrl+Alt for German '@') must be supplied explicitly. Unicode uses
    VK_PACKET and is deliberately not described as a physical key representation.
    """

    named: str | None = None
    character: str | None = None
    scan_code: int | None = None
    unicode: str | None = None
    extended: bool = False
    modifiers: tuple[str, ...] = ()
    repeat: int = 1

    def __post_init__(self):
        if (
            sum(v is not None for v in (self.named, self.character, self.scan_code, self.unicode))
            != 1
        ):
            raise ValueError("Choose exactly one Windows key representation")
        if type(self.repeat) is not int or not 1 <= self.repeat <= 20:
            raise ValueError("Repeat must be an integer from 1 to 20")
        if type(self.extended) is not bool or (self.extended and self.scan_code is None):
            raise ValueError("Extended applies only to an explicit scan code")
        if self.scan_code is not None and (
            type(self.scan_code) is not int or not 1 <= self.scan_code <= 0x7F
        ):
            raise ValueError("Scan code must be an unprefixed physical code from 1 to 127")
        if self.named is not None and (
            not isinstance(self.named, str) or self.named not in NAMED_KEYS
        ):
            raise ValueError("Unsupported Windows named key")
        if not isinstance(self.modifiers, tuple) or len(set(self.modifiers)) != len(self.modifiers):
            raise ValueError("Modifiers must be a unique tuple")
        if any(m not in MODIFIER_VKS for m in self.modifiers):
            raise ValueError("Unsupported Windows modifier; use control/alt/shift/windows")
        if self.unicode is not None and self.modifiers:
            raise ValueError("Unicode packets do not accept shortcut modifiers")
        for value in (self.character, self.unicode):
            if value is not None:
                if not isinstance(value, str) or len(value) != 1 or not value.isprintable():
                    raise ValueError("A key character must be one printable Unicode scalar")
                value.encode("utf-16-le")  # Reject lone surrogates, never silently replace them.


def shortcut_stroke(key: str, modifiers: tuple[str, ...]) -> KeyStroke:
    """One explicit chord using a layout base label or a Windows named key.

    ``("a", ("control",))`` describes Ctrl+A; a capital letter never adds
    Shift. This helper parses no shortcut expression and inserts no Unicode
    packets. The normal native planner owns mapping, modifiers, guards and the
    single complete SendInput call; no cleanup or retry is added here.
    """
    if not isinstance(key, str) or not key or len(key) > 32:
        raise ValueError("A shortcut needs one base character or a Windows named key")
    if not isinstance(modifiers, tuple) or not 1 <= len(modifiers) <= 4:
        raise ValueError("A shortcut needs one to four explicit Windows modifiers")
    return KeyStroke(**{"named" if key in NAMED_KEYS else "character": key}, modifiers=modifiers)


@dataclass(frozen=True)
class KeyEvent:
    virtual_key: int = 0
    scan_code: int = 0
    flags: int = 0
    extra_info: int = 0


# Windows LONG/DWORD are 32-bit even on 64-bit Windows and LP64 test hosts.
WORD, DWORD, LONG, ULONG_PTR = ctypes.c_uint16, ctypes.c_uint32, ctypes.c_int32, ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", WORD),
        ("wScan", WORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", LONG),
        ("dy", LONG),
        ("mouseData", DWORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", DWORD), ("wParamL", WORD), ("wParamH", WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("payload",)
    _fields_ = [("type", DWORD), ("payload", _INPUTUNION)]


class Win32KeyboardAPI:
    """Small ctypes boundary, loaded only in a real Windows process."""

    def __init__(self):
        if os.name != "nt":
            raise BridgeError("unsupported_platform", "Native Windows keyboard needs Windows")
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        P, U, INT, B = ctypes.c_void_p, DWORD, ctypes.c_int32, ctypes.c_int32
        signatures = {
            "GetForegroundWindow": ([], P),
            "IsWindow": ([P], B),
            "GetWindowThreadProcessId": ([P, ctypes.POINTER(U)], U),
            "GetKeyboardLayout": ([U], P),
            "GetAsyncKeyState": ([INT], ctypes.c_int16),
            "VkKeyScanExW": ([ctypes.c_wchar, P], ctypes.c_int16),
            "MapVirtualKeyExW": ([U, U, P], U),
            "SendInput": ([U, ctypes.POINTER(INPUT), INT], U),
            "OpenInputDesktop": ([U, B, U], P),
            "CloseDesktop": ([P], B),
            "GetThreadDesktop": ([U], P),
            "GetUserObjectInformationW": ([P, INT, P, U, ctypes.POINTER(U)], B),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.user, name)
            function.argtypes, function.restype = arguments, result
        self.kernel.OpenProcess.argtypes = [U, B, U]
        self.kernel.OpenProcess.restype = P
        self.kernel.CloseHandle.argtypes, self.kernel.CloseHandle.restype = [P], B
        self.kernel.GetCurrentThreadId.argtypes, self.kernel.GetCurrentThreadId.restype = [], U
        self.kernel.GetProcessTimes.argtypes = [P, P, P, P, P]
        self.kernel.GetProcessTimes.restype = B

    def _created(self, pid):
        process = self.kernel.OpenProcess(0x1000, False, pid)
        if not process:
            raise BridgeError(
                "windows_target_unavailable", "Cannot inspect target process identity"
            )
        try:
            values = [ctypes.c_uint64() for _ in range(4)]
            if not self.kernel.GetProcessTimes(process, *(ctypes.byref(v) for v in values)):
                raise BridgeError("windows_target_unavailable", "Target process time unavailable")
            return values[0].value
        finally:
            self.kernel.CloseHandle(process)

    def foreground(self):
        hwnd = self.user.GetForegroundWindow()
        if not hwnd or not self.user.IsWindow(hwnd):
            raise BridgeError("windows_foreground_unavailable", "No existing foreground window")
        pid = DWORD()
        thread = self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        layout = self.user.GetKeyboardLayout(thread)
        return WindowTarget(
            int(hwnd), pid.value, self._created(pid.value), thread, int(layout or 0)
        )

    def _desktop_name(self, handle):
        buffer, required = ctypes.create_unicode_buffer(1024), DWORD()
        if not handle or not self.user.GetUserObjectInformationW(
            handle, 2, buffer, ctypes.sizeof(buffer), ctypes.byref(required)
        ):
            raise BridgeError("windows_desktop_unavailable", "Cannot verify input desktop")
        return buffer.value

    def validate_desktop(self):
        desktop = self.user.OpenInputDesktop(0, False, 0x0001)
        if not desktop:
            raise BridgeError(
                "windows_desktop_unavailable", "Input desktop is locked or unavailable"
            )
        try:
            current = self.user.GetThreadDesktop(self.kernel.GetCurrentThreadId())
            if self._desktop_name(desktop) != self._desktop_name(current):
                raise BridgeError("windows_desktop_changed", "A different input desktop is active")
        finally:
            self.user.CloseDesktop(desktop)

    def pressed_modifiers(self):
        return tuple(name for vk, name in MODIFIER_SIDES.items() if self.key_is_down(vk))

    def key_is_down(self, virtual_key):
        return bool(self.user.GetAsyncKeyState(virtual_key) & 0x8000)

    def map_character(self, character, layout):
        value = self.user.VkKeyScanExW(character, layout)
        if value == -1:
            raise BridgeError(
                "windows_key_unavailable", "Character has no key in the target layout"
            )
        return value & 0xFF, (value >> 8) & 0xFF

    def map_scan(self, virtual_key, layout):
        value = self.user.MapVirtualKeyExW(virtual_key, 4, layout)
        prefix, scan = value >> 8, value & 0xFF
        if not scan or prefix not in (0, 0xE0):
            raise BridgeError(
                "windows_key_unavailable", "Key requires unsupported scan-code framing"
            )
        return scan, prefix == 0xE0

    def map_scan_to_virtual(self, scan, extended, layout):
        value = self.user.MapVirtualKeyExW(scan | (0xE000 if extended else 0), 3, layout)
        if not 1 <= value <= 254:
            raise BridgeError("windows_key_unavailable", "Scan code has no key in target layout")
        return value

    def send_input(self, events):
        inputs = (INPUT * len(events))()
        for item, event in zip(inputs, events, strict=True):
            item.type = 1
            item.ki = KEYBDINPUT(
                event.virtual_key, event.scan_code, event.flags, 0, event.extra_info
            )
        ctypes.set_last_error(0)
        count = self.user.SendInput(len(inputs), inputs, ctypes.sizeof(INPUT))
        return int(count), ctypes.get_last_error()


class WindowsKeyboard:
    def __init__(self, api=None):
        self.api = api if api is not None else Win32KeyboardAPI()
        self._lock = threading.Lock()

    def inspect_foreground(self):
        self.api.validate_desktop()
        first = self.api.foreground()
        if self.api.foreground() != first:
            raise BridgeError("windows_target_changed", "Foreground changed during inspection")
        return first

    def _guard(self, target, virtual_key=None):
        self.api.validate_desktop()
        if self.api.foreground() != target:
            raise BridgeError(
                "windows_target_changed", "Foreground identity or keyboard layout changed"
            )
        if self.api.pressed_modifiers():
            raise BridgeError(
                "windows_modifiers_busy", "Release held modifiers before native input"
            )
        if virtual_key is not None and self.api.key_is_down(virtual_key):
            raise BridgeError("windows_key_busy", "Requested key is already held; no input sent")

    def _scan_pair(self, vk, scan, extended, tag):
        flags = SCANCODE | (EXTENDED if extended else 0)
        return (KeyEvent(vk, scan, flags, tag), KeyEvent(vk, scan, flags | KEYUP, tag))

    def _plan(self, stroke, target, tag):
        if stroke.unicode is not None:
            raw = stroke.unicode.encode("utf-16-le")
            events = []
            for offset in range(0, len(raw), 2):
                unit = int.from_bytes(raw[offset : offset + 2], "little")
                events.extend(
                    (KeyEvent(0, unit, UNICODE, tag), KeyEvent(0, unit, UNICODE | KEYUP, tag))
                )
            return tuple(events), None
        modifiers = [m for m in MODIFIER_ORDER if m in stroke.modifiers]
        vk = None
        if stroke.character is not None:
            label = stroke.character.lower()
            if len(label) != 1 or ord(label) > 0xFFFF:
                raise BridgeError(
                    "windows_key_unavailable", "Use explicit Unicode input for this scalar"
                )
            vk, required = self.api.map_character(label, target.keyboard_layout)
            provided = sum(
                bit for name, bit in (("shift", 1), ("control", 2), ("alt", 4)) if name in modifiers
            )
            if required & ~7 or required & provided != required:
                raise BridgeError(
                    "windows_key_modifiers_required", "Layout-required modifiers missing"
                )
        elif stroke.named is not None:
            vk = NAMED_KEYS[stroke.named]
        if stroke.scan_code is not None:
            vk = self.api.map_scan_to_virtual(
                stroke.scan_code, stroke.extended, target.keyboard_layout
            )
            key = self._scan_pair(0, stroke.scan_code, stroke.extended, tag)
        elif stroke.named == "pause":
            key = (KeyEvent(vk, 0, 0, tag), KeyEvent(vk, 0, KEYUP, tag))
        else:
            scan, extended = self.api.map_scan(vk, target.keyboard_layout)
            key = self._scan_pair(vk, scan, extended or stroke.named in EXTENDED_NAMED_KEYS, tag)
        starts, ends = [], []
        for modifier in modifiers:
            code = MODIFIER_VKS[modifier]
            scan, extended = self.api.map_scan(code, target.keyboard_layout)
            down, up = self._scan_pair(code, scan, extended or modifier == "windows", tag)
            starts.append(down)
            ends.insert(0, up)
        return tuple([*starts, *key, *ends]), vk

    def send(self, target, strokes, *, before_send: Callable[[], None] | None = None):
        """No activation/retry. Each native call includes a complete key/modifier pair.

        Foreground checks precede SendInput but Windows offers no atomic HWND-bound
        SendInput. A scheduling/focus race remains; receiver evidence is separate.
        Any incomplete native call stops immediately, without guessed cleanup.
        """
        if not isinstance(target, WindowTarget):
            raise ValueError("A freshly inspected Windows target is required")
        strokes = tuple(strokes)
        if not strokes or any(not isinstance(s, KeyStroke) for s in strokes):
            raise ValueError("A sequence needs Windows KeyStroke values")
        if sum(s.repeat for s in strokes) > MAX_KEYS:
            raise ValueError("A sequence may contain at most 32 key pairs")
        tag = secrets.randbits(min(48, ctypes.sizeof(ULONG_PTR) * 8 - 1)) or 1
        completed, inserted, attempted, native_calls = 0, 0, False, 0
        native_incomplete, current_modifiers = False, ()
        with self._lock:
            self._guard(target)
            # Validate the whole intent/layout before the first possible effect.
            planned = [(self._plan(s, target, tag), s.repeat) for s in strokes]
            try:
                for (events, vk), repeat in planned:
                    for _ in range(repeat):
                        self._guard(target, vk)
                        if before_send is not None:
                            before_send()
                        self._guard(target, vk)
                        attempted = True
                        native_incomplete = True
                        current_modifiers = tuple(
                            e for e in events if e.virtual_key in MODIFIER_VKS.values()
                        )
                        native_calls += 1
                        count, error = self.api.send_input(events)
                        if type(count) is not int or not 0 <= count <= len(events):
                            raise RuntimeError("Invalid SendInput acknowledgement")
                        inserted += count
                        if count != len(events):
                            failure = UncertainExecution(
                                "windows_send_input_incomplete",
                                "Input incomplete; reconcile the original task, never replay",
                            )
                            failure.provider_error = {
                                "inserted_this_call": count,
                                "requested_this_call": len(events),
                                "win32_error": error,
                                "uipi_cause_not_diagnosable": True,
                            }
                            raise failure
                        native_incomplete = False
                        completed += 1
            except Exception as cause:
                if attempted:
                    failure = (
                        cause
                        if isinstance(cause, UncertainExecution)
                        else UncertainExecution(
                            "windows_keyboard_partial",
                            "Input stopped after an attempt; do not replay",
                        )
                    )
                    failure.provider_error = {
                        **getattr(failure, "provider_error", {}),
                        "completed_keys": completed,
                        "inserted_events": inserted,
                        "native_calls": native_calls,
                        "cause_code": getattr(cause, "code", "execution_error"),
                        "input_pair_may_be_incomplete": native_incomplete,
                        "modifiers_may_remain_pressed": native_incomplete
                        and bool(current_modifiers),
                        "automatic_retry": False,
                        "receiver_processing_confirmed": False,
                    }
                    if failure is cause:
                        raise
                    raise failure from cause
                raise
        return {
            "requested_keys": sum(s.repeat for s in strokes),
            "completed_keys": completed,
            "inserted_events": inserted,
            "native_calls": native_calls,
            "physical_key_events": all(s.unicode is None for s in strokes),
            "receiver_processing_confirmed": False,
            "automatic_retry": False,
            "target": target.to_wire(),
            "event_tag": tag,
            "scope": "SendInput insertion; not application acknowledgement or physical hardware",
        }
