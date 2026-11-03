"""Run only inside an interactive Windows guest; own window, genuine OS events.

No clipboard and no keys sent to another application. The fixture verifies actual
WM_KEYDOWN/WM_KEYUP delivery and WM_CHAR text, separately from SendInput counts.
It tests US/German layouts on its own UI thread and restores that thread's layout.
Python stdlib plus an installed KiraBridge checkout suffice; no SDK/compiler/Tk.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import queue
import threading
import time
from pathlib import Path

from kirabridge.platform_adapters.windows.keyboard import KeyStroke, WindowsKeyboard


class Receiver:
    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("Windows guest required; never run native tests on the host Mac")
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.tasks, self.events, self.units = queue.Queue(), [], []
        self.lock, self.ready = threading.Lock(), threading.Event()
        self.hwnd, self.original_layout = None, None
        self.error = None
        self.input_case_name = "windows.keyboard.sequence"
        P, U, INT, S = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32, ctypes.c_size_t
        self.proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, P, U, S, ctypes.c_ssize_t)

        class WNDCLASSEX(ctypes.Structure):
            _fields_ = [
                ("cbSize", U),
                ("style", U),
                ("lpfnWndProc", self.proc_type),
                ("cbClsExtra", INT),
                ("cbWndExtra", INT),
                ("hInstance", P),
                ("hIcon", P),
                ("hCursor", P),
                ("hbrBackground", P),
                ("lpszMenuName", ctypes.c_wchar_p),
                ("lpszClassName", ctypes.c_wchar_p),
                ("hIconSm", P),
            ]

        class POINT(ctypes.Structure):
            _fields_ = [("x", INT), ("y", INT)]

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", P),
                ("message", U),
                ("wParam", S),
                ("lParam", ctypes.c_ssize_t),
                ("time", U),
                ("pt", POINT),
                ("lPrivate", U),
            ]

        self.WNDCLASSEX, self.MSG = WNDCLASSEX, MSG
        signatures = {
            "RegisterClassExW": ([ctypes.POINTER(WNDCLASSEX)], ctypes.c_uint16),
            "CreateWindowExW": (
                [U, ctypes.c_wchar_p, ctypes.c_wchar_p, U, INT, INT, INT, INT, P, P, P, P],
                P,
            ),
            "DefWindowProcW": ([P, U, S, ctypes.c_ssize_t], ctypes.c_ssize_t),
            "ShowWindow": ([P, INT], INT),
            "SetForegroundWindow": ([P], INT),
            "GetForegroundWindow": ([], P),
            "IsWindow": ([P], INT),
            "GetWindowThreadProcessId": ([P, ctypes.POINTER(U)], U),
            "SetWindowTextW": ([P, ctypes.c_wchar_p], INT),
            "GetMessageW": ([ctypes.POINTER(MSG), P, U, U], INT),
            "TranslateMessage": ([ctypes.POINTER(MSG)], INT),
            "DispatchMessageW": ([ctypes.POINTER(MSG)], ctypes.c_ssize_t),
            "GetMessageExtraInfo": ([], ctypes.c_ssize_t),
            "PostMessageW": ([P, U, S, ctypes.c_ssize_t], INT),
            "DestroyWindow": ([P], INT),
            "PostQuitMessage": ([INT], None),
            "LoadKeyboardLayoutW": ([ctypes.c_wchar_p, U], P),
            "ActivateKeyboardLayout": ([P, U], P),
            "GetKeyboardLayout": ([U], P),
        }
        for name, (arguments, result) in signatures.items():
            fn = getattr(self.user, name)
            fn.argtypes, fn.restype = arguments, result
        self.kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        self.kernel.GetModuleHandleW.restype = P
        self.callback = self.proc_type(self._window_proc)

    @staticmethod
    def save_report(output, report):
        output.seek(0)
        output.write(json.dumps(report, indent=2, ensure_ascii=True) + "\n")
        output.truncate()
        output.flush()
        os.fsync(output.fileno())

    def foreground_status(self):
        own_pid = ctypes.c_uint32()
        own_window = bool(self.hwnd and self.user.IsWindow(self.hwnd))
        if own_window:
            self.user.GetWindowThreadProcessId(self.hwnd, ctypes.byref(own_pid))
            own_window = own_pid.value == os.getpid()
        current = self.user.GetForegroundWindow()
        pid = ctypes.c_uint32()
        if current:
            self.user.GetWindowThreadProcessId(current, ctypes.byref(pid))
        return {
            "window_created": own_window,
            "hwnd": str(self.hwnd) if self.hwnd else None,
            "pid": os.getpid(),
            "window_owner_pid": own_pid.value or None,
            "foreground_hwnd": str(current) if current else None,
            "foreground_pid": pid.value or None,
            "foreground_ready": own_window and current == self.hwnd and pid.value == os.getpid(),
        }

    def wait_for_foreground(self, *, timeout=120, on_status=None, clock=time.monotonic, wait=None):
        """Wait for ordinary activation of our own window; never steal focus in a loop."""
        if (
            type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or not 0 < timeout <= 300
        ):
            raise ValueError("Fixture foreground wait must be finite and at most 300 seconds")
        pause = wait or threading.Event().wait
        started, previous = clock(), None
        if self.foreground_status()["window_created"]:
            self.user.SetWindowTextW(self.hwnd, f"KiraBridge CLICK THIS WINDOW PID {os.getpid()}")
        while True:
            status = self.foreground_status()
            elapsed = clock() - started
            phase = "ready" if status["foreground_ready"] else "waiting_for_foreground"
            if elapsed >= timeout and not status["foreground_ready"]:
                phase = "foreground_timeout"
            if not status["window_created"] or self.error:
                phase = "window_unavailable"
            if phase != previous:
                observation = {
                    **status,
                    "phase": phase,
                    "elapsed_ms": round(elapsed * 1000, 3),
                    "input_attempted": False,
                    "timeout_seconds": timeout,
                }
                print(
                    json.dumps({"event": "windows_fixture_foreground", **observation}), flush=True
                )
                if on_status is not None:
                    on_status(observation)
                previous = phase
            if phase == "ready":
                self.user.SetWindowTextW(self.hwnd, f"KiraBridge READY PID {os.getpid()}")
                return observation
            if phase != "waiting_for_foreground":
                raise RuntimeError(f"Owned fixture {phase}; no input attempted")
            pause(min(0.05, max(0, timeout - elapsed)))

    def instrument_keyboard(self, keyboard, report, *, persist):
        """Test-only observations around the unchanged guarded backend and native hook.

        Persist null before entering a potentially effectful call. If the process
        stops before return, that receipt stays uncertain. A normal pre-hook error
        proves zero attempted input; never infer zero from an empty cases list.
        """
        original = keyboard.send
        report.setdefault("input_attempted", False)
        report.setdefault("input_attempt_hooks", 0)
        report.setdefault("case_attempts", [])
        report["input_attempt_scope"] = "Before-send hook; conservatively before last target check"

        def reconcile():
            states = [item["input_attempted"] for item in report["case_attempts"]]
            report["input_attempted"] = (
                True if True in states else None if None in states else False
            )

        def observed_send(target, strokes, *, before_send=None):
            item = {
                "name": self.input_case_name,
                "input_attempted": None,
                "input_attempt_hooks": 0,
                "native_calls_acknowledged": None,
                "inserted_events": None,
                "state": "dispatching",
            }
            report["case_attempts"].append(item)
            reconcile()
            persist()

            def mark():
                if before_send is not None:
                    before_send()
                item["input_attempted"] = True
                item["input_attempt_hooks"] += 1
                report["input_attempt_hooks"] += 1
                reconcile()

            try:
                result = original(target, strokes, before_send=mark)
                item.update(
                    {
                        "state": "inserted",
                        "native_calls_acknowledged": result["native_calls"],
                        "inserted_events": result["inserted_events"],
                    }
                )
                if item["input_attempt_hooks"] != result["native_calls"]:
                    raise RuntimeError(
                        "Native-call receipt differs from observed before-send hooks"
                    )
                return result
            except BaseException as error:
                if item["input_attempt_hooks"] == 0:
                    item["input_attempted"] = False
                item["state"], item["error_type"] = "failed", type(error).__name__
                item["inserted_events"] = None
                raise
            finally:
                reconcile()
                persist()

        keyboard.send = observed_send

    def text(self):
        with self.lock:
            data = b"".join(u.to_bytes(2, "little") for u in self.units)
        return data.decode("utf-16-le", errors="surrogatepass")

    def _window_proc(self, hwnd, message, wparam, lparam):
        try:
            if message in (0x0100, 0x0101, 0x0104, 0x0105):
                with self.lock:
                    self.events.append(
                        {
                            "kind": "up" if message in (0x0101, 0x0105) else "down",
                            "vk": int(wparam),
                            "scan": (lparam >> 16) & 0xFF,
                            "extended": bool(lparam & (1 << 24)),
                            "tag": int(self.user.GetMessageExtraInfo()),
                            "at_monotonic_ns": time.monotonic_ns(),
                        }
                    )
            if message == 0x0102:  # WM_CHAR; surrogate code units are retained exactly.
                with self.lock:
                    if wparam == 8:
                        if self.units:
                            last = self.units.pop()
                            if (
                                0xDC00 <= last <= 0xDFFF
                                and self.units
                                and 0xD800 <= self.units[-1] <= 0xDBFF
                            ):
                                self.units.pop()
                    else:
                        self.units.append(10 if wparam == 13 else int(wparam))
                preview = (
                    self.text()
                    .encode("utf-16-le", errors="surrogatepass")
                    .decode("utf-16-le", errors="replace")
                )
                self.user.SetWindowTextW(hwnd, "KiraBridge keyboard fixture: " + preview)
                return 0
            if message == 0x8001:
                callback, done = self.tasks.get_nowait()
                try:
                    callback()
                finally:
                    done.set()
                return 0
            if message == 0x8002:
                self.user.DestroyWindow(hwnd)
                return 0
            if message == 0x0002:
                if self.original_layout:
                    self.user.ActivateKeyboardLayout(self.original_layout, 0)
                self.user.PostQuitMessage(0)
                return 0
        except Exception as error:
            self.error = f"{type(error).__name__}: {error}"
            self.user.PostQuitMessage(1)
            return 0
        return self.user.DefWindowProcW(hwnd, message, wparam, lparam)

    def set_layout(self, identifier):
        result = []

        def change():
            layout = self.user.LoadKeyboardLayoutW(identifier, 1)
            if layout:
                result.append(int(layout))

        done = threading.Event()
        self.tasks.put((change, done))
        if not self.user.PostMessageW(self.hwnd, 0x8001, 0, 0) or not done.wait(3):
            raise RuntimeError("Owned fixture UI did not acknowledge layout request")
        if not result:
            raise RuntimeError(f"Windows keyboard layout unavailable: {identifier}")
        return result[0]

    def run(self):
        name = f"KiraBridgeKeyboardFixture_{os.getpid()}"
        instance = self.kernel.GetModuleHandleW(None)
        window_class = self.WNDCLASSEX()
        window_class.cbSize = ctypes.sizeof(window_class)
        window_class.lpfnWndProc = self.callback
        window_class.hInstance, window_class.lpszClassName = instance, name
        window_class.hbrBackground = (
            6  # System COLOR_WINDOW brush; owned fixture surface stays visible.
        )
        if not self.user.RegisterClassExW(ctypes.byref(window_class)):
            raise RuntimeError("Cannot register owned fixture window")
        self.hwnd = self.user.CreateWindowExW(
            0x00000008,  # WS_EX_TOPMOST: visible fixture; normal activation remains required.
            name,
            f"KiraBridge CLICK THIS WINDOW PID {os.getpid()}",
            0x00CF0000,
            100,
            100,
            900,
            220,
            None,
            None,
            instance,
            None,
        )
        if not self.hwnd:
            raise RuntimeError("Cannot create owned fixture window")
        self.original_layout = self.user.GetKeyboardLayout(0)
        self.user.ShowWindow(self.hwnd, 5)
        self.user.SetForegroundWindow(self.hwnd)  # Only the fixture's own newly created HWND.
        self.ready.set()
        message = self.MSG()
        while True:
            result = self.user.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result == 0:
                break
            if result == -1:
                raise RuntimeError("Fixture Windows message loop failed")
            self.user.TranslateMessage(ctypes.byref(message))
            self.user.DispatchMessageW(ctypes.byref(message))


def run_acceptance(receiver, output):
    report = {
        "scope": "Real SendInput and receiver WM_KEY/WM_CHAR inside Windows guest",
        "platform": os.name,
        "clipboard_used": False,
        "host_mac_input": False,
        "cases": [],
        "passed": False,
        "input_attempted": False,
        "input_attempt_hooks": 0,
        "case_attempts": [],
    }

    def persist():
        receiver.save_report(output, report)

    def foreground(observation):
        report["foreground_readiness"] = observation
        persist()

    try:
        persist()
        if not receiver.ready.wait(5):
            raise RuntimeError("Fixture window did not become ready")
        receiver.wait_for_foreground(on_status=foreground)
        keyboard = WindowsKeyboard()
        receiver.instrument_keyboard(keyboard, report, persist=persist)

        def pairs(*keys):
            return [(kind, key) for key in keys for kind in ("down", "up")]

        def send_case(
            name, strokes, text_suffix, expected_events, physical=True, require_extended=False
        ):
            receiver.input_case_name = name
            target = keyboard.inspect_foreground()
            if target.hwnd != receiver.hwnd or target.pid != os.getpid():
                raise RuntimeError("Owned fixture is not foreground; no input attempted")
            before = receiver.text()
            started = time.monotonic_ns()
            result = keyboard.send(target, strokes)
            expected = text_suffix(before) if callable(text_suffix) else before + text_suffix
            event_count = len(expected_events)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                with receiver.lock:
                    events = [e for e in receiver.events if e["tag"] == result["event_tag"]]
                if receiver.text() == expected and len(events) >= event_count:
                    break
                threading.Event().wait(0.01)
            observed_text = receiver.text()
            # Retain actual receiver evidence before any assertion can reject it.
            observation = {
                "text_before": before,
                "expected_text": expected,
                "observed_text": observed_text,
                "received_events": events,
                "expected_events": expected_events,
                "expected_event_count": event_count,
                "event_count_exact": len(events) == event_count,
                "text_exact": observed_text == expected,
                "key_order_exact": [(e["kind"], e["vk"]) for e in events] == expected_events,
                "require_extended": require_extended,
                "extended_flags_exact": len(events) == event_count
                and all(e["extended"] for e in events)
                if require_extended
                else None,
            }
            report["case_attempts"][-1]["receiver_observation"] = observation
            persist()
            if not observation["text_exact"] or len(events) != event_count:
                raise RuntimeError(f"{name}: receiver text or exact event count mismatch")
            if not observation["key_order_exact"]:
                raise RuntimeError(f"{name}: receiver exact down/up key order mismatch")
            if require_extended and not observation["extended_flags_exact"]:
                raise RuntimeError(f"{name}: expected extended scan-code flag missing")
            if result["physical_key_events"] != physical:
                raise RuntimeError(f"{name}: physical/Unicode representation mismatch")
            report["cases"].append(
                {
                    "name": name,
                    "target": result["target"],
                    "elapsed_ms": (time.monotonic_ns() - started) / 1e6,
                    "inserted_events": result["inserted_events"],
                    "received_events": events,
                    "text_exact": True,
                    "key_order_exact": True,
                    "physical_key_events": physical,
                    "completed_keys": result["completed_keys"],
                    "input_attempted": True,
                    "input_attempt_hooks": report["case_attempts"][-1]["input_attempt_hooks"],
                }
            )

        receiver.set_layout("00000409")
        strokes = [KeyStroke(character="s", modifiers=("shift",))]
        strokes.extend(
            KeyStroke(named="space") if c == " " else KeyStroke(character=c) for c in "tern am"
        )
        eight_events = [
            ("down", 0x10),
            *pairs(0x53),
            ("up", 0x10),
            *pairs(0x54, 0x45, 0x52, 0x4E, 0x20, 0x41, 0x4D),
        ]
        send_case("us-eight-physical-keys", strokes, "Stern am", eight_events)
        send_case(
            "us-layout-yz",
            [KeyStroke(character="y"), KeyStroke(character="z")],
            "yz",
            pairs(0x59, 0x5A),
        )
        receiver.set_layout("00000407")
        send_case(
            "german-layout-yz-umlaut",
            [KeyStroke(character="y"), KeyStroke(character="z"), KeyStroke(character="ä")],
            "yzä",
            pairs(0x59, 0x5A, 0xDE),
        )
        altgr_events = [("down", 0x11), ("down", 0x12), *pairs(0x51), ("up", 0x12), ("up", 0x11)]
        send_case(
            "german-altgr",
            [KeyStroke(character="@", modifiers=("control", "alt"))],
            "@",
            altgr_events,
        )
        send_case(
            "explicit-unicode",
            [KeyStroke(unicode="€"), KeyStroke(unicode="😀")],
            "€😀",
            pairs(0xE7, 0xE7, 0xE7),
            physical=False,
        )
        send_case("return", [KeyStroke(named="enter")], "\n", pairs(0x0D))
        send_case("backspace", [KeyStroke(named="backspace")], lambda text: text[:-1], pairs(0x08))
        send_case(
            "extended-arrow", [KeyStroke(named="right")], "", pairs(0x27), require_extended=True
        )
        send_case("function-key", [KeyStroke(named="f2")], "", pairs(0x71))
        report["passed"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        report["uncertain_input_replayed"] = False
        if hasattr(error, "provider_error"):
            report["provider_error"] = error.provider_error
    finally:
        try:
            persist()
        finally:
            if receiver.hwnd:
                receiver.user.PostMessageW(receiver.hwnd, 0x8002, 0, 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Run this fixture only in an interactive Windows guest")
    try:
        output = args.output.open("x+", encoding="utf-8")
    except FileExistsError:
        parser.error("Use a new evidence filename; never overwrite an uncertain previous run")
    with output:
        output.write(
            '{"state":"started","passed":false,"automatic_retry":false,'
            '"input_attempted":false,"input_attempt_hooks":0}\n'
        )
        output.flush()
        os.fsync(output.fileno())
        receiver = Receiver()
        worker = threading.Thread(target=run_acceptance, args=(receiver, output), daemon=True)
        worker.start()
        receiver.run()
        worker.join(timeout=5)
        if worker.is_alive() or receiver.error:
            raise SystemExit(receiver.error or "Acceptance worker did not stop")
    result = json.loads(args.output.read_text(encoding="utf-8"))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
