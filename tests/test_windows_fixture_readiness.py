"""Fixture control tests; injected APIs never post native keys or change OS focus."""

import importlib.util
import json
import os
from pathlib import Path

import pytest

from kirabridge.bridge_core.models import BridgeError, UncertainExecution

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "accept_windows_keyboard.py"
SPEC = importlib.util.spec_from_file_location("windows_keyboard_guest_fixture_test", SOURCE)
FIXTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURE)


class User:
    def __init__(self):
        self.current = 200
        self.owner = os.getpid()
        self.captions = []

    def IsWindow(self, hwnd):
        return hwnd == 100

    def GetForegroundWindow(self):
        return self.current

    def GetWindowThreadProcessId(self, hwnd, pointer):
        pointer._obj.value = self.owner if hwnd == 100 else 999
        return 401

    def SetWindowTextW(self, hwnd, caption):
        assert hwnd == 100 and self.owner == os.getpid()
        self.captions.append(caption)

    def SetForegroundWindow(self, _):
        pytest.fail("Foreground wait must never force activation")


def receiver():
    result = FIXTURE.Receiver.__new__(FIXTURE.Receiver)
    result.user, result.hwnd, result.error = User(), 100, None
    result.input_case_name = "case-one"
    return result


def test_waits_for_ordinary_own_window_activation_without_focus_stealing():
    window, observations, now = receiver(), [], [0.0]

    def wait(seconds):
        now[0] += seconds
        if now[0] >= 0.1:
            window.user.current = 100

    result = window.wait_for_foreground(
        timeout=1, on_status=observations.append, clock=lambda: now[0], wait=wait
    )
    assert result["foreground_ready"] and result["hwnd"] == "100"
    assert [item["phase"] for item in observations] == ["waiting_for_foreground", "ready"]
    assert all(item["input_attempted"] is False for item in observations)
    assert f"CLICK THIS WINDOW PID {os.getpid()}" in window.user.captions[0]
    assert f"READY PID {os.getpid()}" in window.user.captions[-1]


def test_foreground_timeout_is_bounded_and_proves_no_send_was_attempted():
    window, observations, now = receiver(), [], [0.0]

    def wait(seconds):
        now[0] += seconds

    with pytest.raises(RuntimeError, match="foreground_timeout; no input attempted"):
        window.wait_for_foreground(
            timeout=0.1, on_status=observations.append, clock=lambda: now[0], wait=wait
        )
    assert now[0] == pytest.approx(0.1)
    assert observations[-1]["phase"] == "foreground_timeout"
    assert observations[-1]["input_attempted"] is False


def test_reused_hwnd_with_another_pid_is_not_our_fixture_and_is_not_relabelled():
    window = receiver()
    window.user.owner = 123456
    window.user.current = 100
    with pytest.raises(RuntimeError, match="window_unavailable"):
        window.wait_for_foreground()
    assert not window.user.captions


def test_known_pre_send_error_records_zero_attempts_not_an_empty_cases_guess():
    window, report, snapshots = receiver(), {}, []

    class Backend:
        def send(self, target, strokes, before_send):
            raise BridgeError("windows_target_changed", "Known pre-send guard failed")

    backend = Backend()
    window.instrument_keyboard(
        backend, report, persist=lambda: snapshots.append(json.loads(json.dumps(report)))
    )
    with pytest.raises(BridgeError):
        backend.send(None, [])
    assert snapshots[0]["input_attempted"] is None
    assert report["input_attempted"] is False and report["input_attempt_hooks"] == 0
    assert report["case_attempts"][0]["input_attempted"] is False
    assert report["case_attempts"][0]["inserted_events"] is None


def test_success_counts_before_send_hooks_and_acknowledged_native_calls():
    window, report, snapshots = receiver(), {}, []

    class Backend:
        def send(self, target, strokes, before_send):
            before_send()
            before_send()
            return {"native_calls": 2, "inserted_events": 4}

    backend = Backend()
    window.instrument_keyboard(
        backend, report, persist=lambda: snapshots.append(json.loads(json.dumps(report)))
    )
    backend.send(None, [])
    assert snapshots[0]["input_attempted"] is None
    assert report["input_attempted"] is True and report["input_attempt_hooks"] == 2
    case = report["case_attempts"][0]
    assert case["native_calls_acknowledged"] == 2 and case["inserted_events"] == 4
    assert case["state"] == "inserted"


def test_partial_native_failure_retains_attempt_and_unknown_inserted_count():
    window, report = receiver(), {}

    class Backend:
        def send(self, target, strokes, before_send):
            before_send()
            raise UncertainExecution("windows_keyboard_partial", "Do not replay")

    backend = Backend()
    window.instrument_keyboard(backend, report, persist=lambda: None)
    with pytest.raises(UncertainExecution):
        backend.send(None, [])
    assert report["input_attempted"] is True
    assert report["case_attempts"][0]["inserted_events"] is None
    assert report["case_attempts"][0]["native_calls_acknowledged"] is None


def test_previous_unknown_is_not_coerced_to_false_by_a_later_pre_send_failure():
    window = receiver()
    report = {"input_attempted": None, "case_attempts": [{"input_attempted": None}]}

    class Backend:
        def send(self, target, strokes, before_send):
            raise BridgeError("windows_target_changed", "Known pre-send guard failed")

    backend = Backend()
    window.instrument_keyboard(backend, report, persist=lambda: None)
    with pytest.raises(BridgeError):
        backend.send(None, [])
    assert report["input_attempted"] is None
    assert report["case_attempts"][-1]["input_attempted"] is False
