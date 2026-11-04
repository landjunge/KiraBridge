"""Real Windows shortcut acceptance against one owned, normally activated window.

Ctrl+A, Ctrl+S, Shift+Tab and Alt+F2 are consumed by this fixture only. No file,
clipboard, desktop-global Windows shortcut, production server or other window is
used. Run once with a NEW durable receipt; reconcile any uncertain original run.
The held-modifier negative control injects a guard observation, not a held key.
"""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import math
import os
import statistics
import threading
import time
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.windows.keyboard import (
    Win32KeyboardAPI,
    WindowsKeyboard,
    shortcut_stroke,
)

KEY_MESSAGES = {0x100: "down", 0x101: "up", 0x104: "down", 0x105: "up"}
QUEUE_MODIFIERS = {"control": 0x11, "alt": 0x12, "shift": 0x10, "windows": 0x5B}
CASES = [
    ("ctrl-a", "a", ("control",), 0x11, 0x41),
    ("ctrl-s", "s", ("control",), 0x11, 0x53),
    ("shift-tab", "tab", ("shift",), 0x10, 0x09),
    ("alt-f2", "f2", ("alt",), 0x12, 0x71),
]


def load_receiver_type():
    source = Path(__file__).with_name("accept_windows_keyboard.py")
    spec = importlib.util.spec_from_file_location("kirabridge_shortcut_receiver_base", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("Owned receiver fixture source is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Receiver


class ShortcutReceiver(load_receiver_type()):
    def __init__(self):
        super().__init__()
        self.raw_events, self.actions, self.control_units = [], [], []
        self.user.GetKeyState.argtypes = [ctypes.c_int32]
        self.user.GetKeyState.restype = ctypes.c_int16

    def _window_proc(self, hwnd, message, wparam, lparam):
        if message in KEY_MESSAGES:
            # GetKeyState observes the UI thread's dequeued event state, unlike
            # GetAsyncKeyState after all SendInput records may already be queued.
            # https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-getkeystate
            modifiers = tuple(
                name for name, vk in QUEUE_MODIFIERS.items() if self.user.GetKeyState(vk) & 0x8000
            )
            item = {
                "kind": KEY_MESSAGES[message],
                "vk": int(wparam),
                "scan": (lparam >> 16) & 0xFF,
                "extended": bool(lparam & (1 << 24)),
                "tag": int(self.user.GetMessageExtraInfo()),
                "at_monotonic_ns": time.monotonic_ns(),
                "message": message,
                "system_key": message in (0x104, 0x105),
                "alt_context": bool(lparam & (1 << 29)),
                "queue_modifiers": modifiers,
            }
            with self.lock:
                self.raw_events.append(item)
                self.events.append(dict(item))
                if item["kind"] == "down":
                    for name, _, required, _, key_vk in CASES:
                        if wparam == key_vk and modifiers == required:
                            self.actions.append({"name": name, "tag": item["tag"]})
            # Never pass Alt to DefWindowProc: the fixture consumes its own
            # shortcut and does not open a menu or move focus to another window.
            # https://learn.microsoft.com/windows/win32/inputdev/wm-syskeyup
            return 0
        if message in (0x102, 0x106):
            with self.lock:
                self.control_units.append(int(wparam))
            return 0
        return super()._window_proc(hwnd, message, wparam, lparam)


class RecordingAPI:
    """Observe each actual native call, persist its plan before any possible effect."""

    def __init__(self, api, report, persist):
        self.api, self.report, self.persist = api, report, persist
        self.calls = []
        self.active_case = None

    def __getattr__(self, name):
        return getattr(self.api, name)

    def send_input(self, events):
        observation = {
            "name": self.active_case,
            "events": [
                {
                    "virtual_key": event.virtual_key,
                    "scan_code": event.scan_code,
                    "flags": event.flags,
                    "tag": event.extra_info,
                }
                for event in events
            ],
            "inserted_events": None,
            "win32_error": None,
        }
        self.calls.append(observation)
        self.report["native_calls"] = self.calls
        self.persist()
        started = time.monotonic_ns()
        try:
            count, error = self.api.send_input(events)
            observation["inserted_events"], observation["win32_error"] = count, error
            return count, error
        finally:
            observation["elapsed_ms"] = (time.monotonic_ns() - started) / 1e6
            self.persist()


def snapshot(receiver):
    with receiver.lock:
        return [dict(event) for event in receiver.raw_events], [
            dict(action) for action in receiver.actions
        ]


def require_owned_target(receiver, keyboard):
    target = keyboard.inspect_foreground()
    if target.hwnd != receiver.hwnd or target.pid != os.getpid():
        raise RuntimeError("Own fixture is not foreground; no shortcut attempted")
    return target


def check_case(receiver, recording, keyboard, report, persist, case):
    name, key, modifiers, modifier_vk, key_vk = case
    target = require_owned_target(receiver, keyboard)
    receiver.input_case_name = recording.active_case = name
    expected = [("down", modifier_vk), ("down", key_vk), ("up", key_vk), ("up", modifier_vk)]
    item = {"name": name, "passed": False, "target": target.to_wire(), "expected_events": expected}
    report["cases"].append(item)
    persist()
    call_index, started, result = len(recording.calls), time.monotonic_ns(), None
    try:
        result = keyboard.send(target, [shortcut_stroke(key, modifiers)])
        tag = result["event_tag"]
        deadline = time.monotonic() + 3
        while True:
            all_events, all_actions = snapshot(receiver)
            events = [event for event in all_events if event["tag"] == tag]
            actions = [action for action in all_actions if action["tag"] == tag]
            if len(events) >= 4 and len(actions) >= 1:
                break
            if time.monotonic() >= deadline:
                break
            threading.Event().wait(0.01)
        # This queue roundtrip makes any already-queued extras visible before
        # checking exact counts. It posts no key or application-side action.
        barrier, done = lambda: None, threading.Event()
        receiver.tasks.put((barrier, done))
        if not receiver.user.PostMessageW(receiver.hwnd, 0x8001, 0, 0) or not done.wait(3):
            raise RuntimeError("Own receiver did not acknowledge the observation barrier")
        all_events, all_actions = snapshot(receiver)
        events = [event for event in all_events if event["tag"] == tag]
        actions = [action for action in all_actions if action["tag"] == tag]
        item["receiver_events"], item["receiver_actions"] = events, actions
        item["native_result"] = result
        persist()
        base_events = [event for event in events if event["vk"] == key_vk]
        exact = [(event["kind"], event["vk"]) for event in events] == expected
        if not exact or len(actions) != 1 or actions[0]["name"] != name:
            raise RuntimeError("Receiver exact shortcut order or single action mismatch")
        if len(base_events) != 2 or any(
            tuple(event["queue_modifiers"]) != modifiers for event in base_events
        ):
            raise RuntimeError("Receiver queue modifier state does not match shortcut")
        if name == "alt-f2" and (
            [event["message"] for event in base_events] != [0x104, 0x105]
            or not all(event["alt_context"] for event in base_events)
        ):
            raise RuntimeError("Alt shortcut lacks real WM_SYSKEY/Alt-context delivery")
        if name != "alt-f2" and any(event["system_key"] for event in base_events):
            raise RuntimeError("Non-Alt shortcut unexpectedly arrived as WM_SYSKEY")
        if (
            result["native_calls"] != 1
            or result["inserted_events"] != 4
            or len(recording.calls) != call_index + 1
        ):
            raise RuntimeError("Shortcut was not one complete four-event native call")
        if recording.pressed_modifiers():
            raise RuntimeError("Modifiers remain pressed; stop without guessed cleanup")
        require_owned_target(receiver, keyboard)
        item["passed"] = True
    finally:
        # Preserve receiver evidence even if native insertion or an assertion fails.
        all_events, all_actions = snapshot(receiver)
        calls = recording.calls[call_index:]
        tags = {event["tag"] for call in calls for event in call["events"]}
        item["receiver_events"] = [event for event in all_events if event["tag"] in tags]
        item["receiver_actions"] = [action for action in all_actions if action["tag"] in tags]
        item["native_calls"] = calls
        item["elapsed_ms"] = (time.monotonic_ns() - started) / 1e6
        persist()


def held_modifier_control(receiver, recording, report, persist):
    class HeldObservationAPI:
        def __getattr__(self, name):
            return getattr(recording, name)

        def pressed_modifiers(self):
            return ("left_control",)

        def send_input(self, events):
            raise RuntimeError("Held-modifier guard incorrectly reached native injection")

    keyboard = WindowsKeyboard(HeldObservationAPI())
    receiver.instrument_keyboard(keyboard, report, persist=persist)
    receiver.input_case_name = "held-modifier-negative-control"
    before, calls_before = snapshot(receiver), len(recording.calls)
    target = require_owned_target(receiver, keyboard)
    try:
        keyboard.send(target, [shortcut_stroke("a", ("control",))])
    except BridgeError as error:
        if error.code != "windows_modifiers_busy":
            raise
    else:
        raise RuntimeError("Held-modifier control was not rejected")
    if snapshot(receiver) != before or len(recording.calls) != calls_before:
        raise RuntimeError("Held-modifier refusal unexpectedly changed receiver or native calls")
    report["held_modifier_control"] = {
        "passed": True,
        "evidence": "Injected held-modifier guard observation; no held key synthesized",
        "error_code": "windows_modifiers_busy",
        "native_calls": 0,
        "receiver_added_events": 0,
        "input_attempted": False,
    }
    persist()


def run_acceptance(receiver, output):
    report = {
        "scope": "Real Windows SendInput shortcuts consumed only by owned receiver",
        "passed": False,
        "input_attempted": False,
        "input_attempt_hooks": 0,
        "case_attempts": [],
        "cases": [],
        "native_calls": [],
        "clipboard_used": False,
        "host_mac_input": False,
        "desktop_global_windows_shortcuts_executed": False,
        "windows_modifier_native_acceptance": (
            "Not executed; native encoder covered by injected unit test"
        ),
        "automatic_retry": False,
        "uncertain_input_replayed": False,
    }

    def persist():
        receiver.save_report(output, report)

    def readiness(observation):
        report["foreground_readiness"] = observation
        persist()

    started = time.monotonic_ns()
    try:
        persist()
        if not receiver.ready.wait(5):
            raise RuntimeError("Owned receiver did not become ready")
        receiver.wait_for_foreground(on_status=readiness)
        receiver.set_layout("00000409")
        recording = RecordingAPI(Win32KeyboardAPI(), report, persist)
        keyboard = WindowsKeyboard(recording)
        receiver.instrument_keyboard(keyboard, report, persist=persist)
        for case in CASES:
            check_case(receiver, recording, keyboard, report, persist, case)
        held_modifier_control(receiver, recording, report, persist)
        samples = [item["elapsed_ms"] for item in report["cases"]]
        report["timing"] = {
            "count": len(samples),
            "total_ms": sum(samples),
            "p50_ms": statistics.median(samples),
            "p95_ms": sorted(samples)[math.ceil(0.95 * len(samples)) - 1],
            "percentile_method": (
                "nearest rank; four distinct shortcuts, no repeated physical input"
            ),
        }
        report["passed"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        if hasattr(error, "provider_error"):
            report["provider_error"] = error.provider_error
    finally:
        report["elapsed_including_foreground_wait_ms"] = (time.monotonic_ns() - started) / 1e6
        persist()
        if receiver.hwnd:
            receiver.user.PostMessageW(receiver.hwnd, 0x8002, 0, 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Run only inside an interactive Windows guest")
    try:
        output = args.output.open("x+", encoding="utf-8")
    except FileExistsError:
        parser.error("Original receipt exists; reconcile it, never replay input")
    with output:
        output.write('{"passed":false,"input_attempted":false,"automatic_retry":false}\n')
        output.flush()
        os.fsync(output.fileno())
        receiver = ShortcutReceiver()
        worker = threading.Thread(target=run_acceptance, args=(receiver, output), daemon=True)
        worker.start()
        receiver.run()
        worker.join(timeout=5)
        if worker.is_alive() or receiver.error:
            raise SystemExit(receiver.error or "Shortcut acceptance worker did not stop")
        result = json.loads(args.output.read_text(encoding="utf-8"))
        result["fixture_window_closed"] = not bool(receiver.user.IsWindow(receiver.hwnd))
        if not result["fixture_window_closed"]:
            result["passed"] = False
            result["close_error"] = "Owned receiver window still exists"
        receiver.save_report(output, result)
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
