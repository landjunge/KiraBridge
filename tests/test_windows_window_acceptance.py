"""Harness guards only: synthetic states do not prove native Windows acceptance."""

import asyncio
import importlib.util
import json
import os
from pathlib import Path

import pytest

from kirabridge.bridge_core.models import BridgeError, UncertainExecution

SPEC = importlib.util.spec_from_file_location(
    "windows_window_acceptance", Path(__file__).parents[1] / "scripts/accept_windows_windows.py"
)
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)
TARGET = {
    "hwnd": "100",
    "pid": str(os.getpid()),
    "process_created_100ns": "900",
    "thread_id": "401",
}


def pending():
    return {
        "effect_attempted": None,
        "before_effect_hooks": 0,
        "state": "submitting_once",
        "native_request_accepted": None,
        "control_backend_entered": False,
    }


def observed(backend, previous=()):
    item = pending()
    report = {"window_effect_attempts": [*previous, item]}
    snapshots = []
    HARNESS.instrument_windows(
        backend, report, lambda: snapshots.append(json.loads(json.dumps(report)))
    )
    return report, item, snapshots


def test_known_pre_effect_guard_persists_zero_hooks_and_false_attempt():
    class Backend:
        def control(self, target, action, *, bounds, before_effect):
            raise BridgeError("windows_target_changed", "Original target no longer exists")

    backend = Backend()
    report, item, snapshots = observed(backend)
    with pytest.raises(BridgeError):
        backend.control(None, "close")
    assert item["effect_attempted"] is False and item["before_effect_hooks"] == 0
    assert report["effect_attempted"] is False
    assert snapshots[-1]["window_effect_attempts"][0]["state"] == "refused_before_effect"


def test_native_unknown_without_hook_remains_unknown_never_zero():
    class Backend:
        def control(self, target, action, *, bounds, before_effect):
            raise UncertainExecution("windows_window_effect_unknown", "Do not replay")

    backend = Backend()
    report, item, _ = observed(backend)
    with pytest.raises(UncertainExecution):
        backend.control(None, "close")
    assert item["effect_attempted"] is None
    assert report["effect_attempted"] is None
    assert item["state"] == "unknown_no_retry"


def test_hook_is_durable_before_forwarding_and_request_ack_is_not_readback():
    events = []

    class Backend:
        def control(self, target, action, *, bounds, before_effect):
            before_effect()
            events.append("native")
            return {"request_accepted": True, "observed": False, "outcome": "requested"}

    backend = Backend()
    report, item, snapshots = observed(backend)
    result = backend.control(None, "maximize", before_effect=lambda: events.append("caller_hook"))
    assert events == ["caller_hook", "native"]
    assert snapshots[0]["window_effect_attempts"][0]["state"] == "backend_entered"
    assert snapshots[1]["window_effect_attempts"][0]["state"] == "before_native_request"
    assert item["effect_attempted"] is True and item["before_effect_hooks"] == 1
    assert item["native_request_accepted"] is True
    assert result["observed"] is False and report["effect_attempted"] is True


def test_failure_after_hook_is_not_retried_or_declared_no_effect():
    class Backend:
        calls = 0

        def control(self, target, action, *, bounds, before_effect):
            self.calls += 1
            before_effect()
            raise UncertainExecution("windows_window_effect_unknown", "Native outcome unknown")

    backend = Backend()
    report, item, _ = observed(backend)
    with pytest.raises(UncertainExecution):
        backend.control(None, "activate")
    assert backend.calls == 1 and item["effect_attempted"] is True
    assert report["effect_attempted"] is True and item["native_request_accepted"] is None


def test_later_refusal_does_not_clear_a_previous_unknown():
    report = {"window_effect_attempts": [{"effect_attempted": None}, {"effect_attempted": False}]}
    HARNESS.aggregate_attempts(report)
    assert report["effect_attempted"] is None


def test_independent_reader_rejects_foreign_generation_and_unexpected_absence():
    class Probe:
        def snapshot(self, hwnd):
            return {"exists": True, "target": {**TARGET, "process_created_100ns": "901"}}

    with pytest.raises(RuntimeError, match="generation differs"):
        HARNESS.checked_snapshot(Probe(), TARGET)

    class Absent:
        def snapshot(self, hwnd):
            return {"exists": False, "hwnd": str(hwnd)}

    with pytest.raises(RuntimeError, match="disappeared"):
        HARNESS.checked_snapshot(Absent(), TARGET)
    assert HARNESS.checked_snapshot(Absent(), TARGET, allow_absent=True)["exists"] is False


def test_observation_polls_independent_reads_without_repeating_control():
    now, calls = [0.0], []

    class Probe:
        def snapshot(self, hwnd):
            calls.append(hwnd)
            return {"exists": True, "target": TARGET, "maximized": now[0] >= 0.04}

    async def pause(seconds):
        now[0] += seconds

    result = asyncio.run(
        HARNESS.observe(
            Probe(), TARGET, lambda state: state["maximized"], clock=lambda: now[0], pause=pause
        )
    )
    assert result["maximized"] is True and calls == [100, 100, 100]


def test_observation_timeout_is_bounded_without_control_retry():
    now, calls = [0.0], []

    class Probe:
        def snapshot(self, hwnd):
            calls.append(hwnd)
            return {"exists": True, "target": TARGET, "maximized": False}

    async def pause(seconds):
        now[0] += seconds

    with pytest.raises(RuntimeError, match="never replay"):
        asyncio.run(
            HARNESS.observe(
                Probe(),
                TARGET,
                lambda state: state["maximized"],
                timeout=0.04,
                clock=lambda: now[0],
                pause=pause,
            )
        )
    assert now[0] == pytest.approx(0.04) and len(calls) == 3


def test_native_cli_refuses_host_before_creating_output(tmp_path):
    if os.name == "nt":
        pytest.skip("This guard specifically verifies a non-Windows host")
    path = tmp_path / "must-not-exist.json"
    with pytest.raises(SystemExit) as error:
        HARNESS.main(["--output", str(path)])
    assert error.value.code == 2 and not path.exists()


def test_independent_readback_declares_windows_llp64_abi_without_native_calls(monkeypatch):
    import ctypes
    from types import SimpleNamespace

    class DLL:
        def __init__(self):
            self.functions = {}

        def __getattr__(self, name):
            if name not in self.functions:

                def never_call(*arguments):
                    pytest.fail("ABI test must not invoke a native API")

                self.functions[name] = never_call
            return self.functions[name]

    user, kernel = DLL(), DLL()
    monkeypatch.setattr(HARNESS, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        ctypes, "WinDLL", lambda name, **kwargs: user if name == "user32" else kernel, raising=False
    )
    probe = HARNESS.NativeReadback()
    assert ctypes.sizeof(probe.RECT) == 16
    assert ctypes.sizeof(probe.PLACEMENT) == 44
    assert user.GetWindowRect.restype is ctypes.c_int32
    assert user.GetWindowRect.argtypes[0] is ctypes.c_void_p
    assert kernel.GetProcessTimes.argtypes[0] is ctypes.c_void_p
    assert kernel.CloseHandle.restype is ctypes.c_int32


def test_terminal_manager_inspect_refusal_before_control_can_prove_no_effect():
    item = pending()
    task = {"state": "failed", "error": {"code": "windows_target_changed"}}
    assert HARNESS.reconcile_stale_precontrol(item, task, window_unchanged=True)
    assert item["effect_attempted"] is False
    assert item["state"] == "manager_inspect_refused_before_control"


@pytest.mark.parametrize("condition", ["unknown", "entered", "changed", "other_error"])
def test_missing_hook_alone_never_coerces_unknown_to_no_effect(condition):
    item = pending()
    task = {"state": "failed", "error": {"code": "windows_target_changed"}}
    if condition == "unknown":
        task["state"] = "unknown"
    elif condition == "entered":
        item["control_backend_entered"] = True
    elif condition == "other_error":
        task["error"]["code"] = "windows_window_effect_unknown"
    assert not HARNESS.reconcile_stale_precontrol(
        item, task, window_unchanged=condition != "changed"
    )
    assert item["effect_attempted"] is None


@pytest.mark.parametrize(
    "attempted,state",
    [(None, "submitting_once"), (True, "unknown_no_retry"), (True, "native_returned")],
)
def test_cleanup_never_repeats_an_unresolved_close_or_other_effect(attempted, state):
    assert not HARNESS.cleanup_can_close(
        {
            "window_effect_attempts": [
                {"effect_attempted": attempted, "state": state, "label": "close_wm_close"}
            ]
        }
    )


def test_cleanup_is_allowed_after_independent_observation_or_proven_no_effect():
    assert HARNESS.cleanup_can_close(
        {
            "window_effect_attempts": [
                {"effect_attempted": True, "state": "independently_observed"},
                {"effect_attempted": False, "state": "manager_inspect_refused_before_control"},
            ]
        }
    )
