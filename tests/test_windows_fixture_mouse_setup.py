"""Fixture-only mouse guards/ABI with injected APIs; no host mouse or native UI."""

import ctypes
import json
from types import SimpleNamespace

import pytest
from test_windows_fixture_readiness import FIXTURE, receiver


def test_durable_unknown_precedes_one_complete_mouse_call_and_keyboard_is_separate():
    window, snapshots = receiver(), []
    api = window.fixture_mouse_api
    original = api.send_input

    def send(events):
        assert snapshots[-1]["setup_mouse_attempted"] is None
        assert snapshots[-1]["input_attempted"] is False
        return original(events)

    api.send_input = send
    result = window.setup_foreground_click(on_status=snapshots.append)
    assert result["setup_mouse_attempted"] is True and result["inserted_events"] == 3
    assert len(api.calls) == 1 and len(api.calls[0]) == 3
    assert [event.type for event in api.calls[0]] == [0, 0, 0]
    assert [event.mi.dwFlags for event in api.calls[0]] == [0xC001, 0x0002, 0x0004]
    assert len({event.mi.dwExtraInfo for event in api.calls[0]}) == 1
    assert not result["application_processing_confirmed"]


@pytest.mark.parametrize("failure", ["covered", "pid", "buttons", "class", "desktop"])
def test_refusal_before_mouse_when_window_or_desktop_is_not_safely_owned(failure):
    window, snapshots = receiver(), []
    api = window.fixture_mouse_api
    if failure == "covered":
        api.covered = True
    elif failure == "pid":
        window.user.owner += 1
    elif failure == "buttons":
        api.buttons = (1,)
    elif failure == "class":
        api.class_name = "ForeignFixture"
    else:
        api.desktop_error = "Input desktop is locked"
    with pytest.raises(RuntimeError):
        window.setup_foreground_click(on_status=snapshots.append)
    assert not api.calls
    assert snapshots[-1]["setup_mouse_attempted"] is False
    assert snapshots[-1]["setup_mouse"]["state"] == "refused_before_effect"


@pytest.mark.parametrize("failure", ["covered", "pid", "buttons"])
def test_rechecks_owner_cover_and_buttons_after_durable_marker_before_effect(failure):
    window, snapshots = receiver(), []
    api = window.fixture_mouse_api

    def persist(observation):
        snapshots.append(observation)
        if observation["setup_mouse_attempted"] is None:
            if failure == "covered":
                api.covered = True
            elif failure == "pid":
                window.user.owner += 1
            else:
                api.buttons = (2,)

    with pytest.raises(RuntimeError):
        window.setup_foreground_click(on_status=persist)
    assert snapshots[0]["setup_mouse_attempted"] is None
    assert snapshots[-1]["setup_mouse_attempted"] is False
    assert not api.calls


@pytest.mark.parametrize("count", [0, 1, 2, 4, True, "3", None])
def test_incomplete_or_invalid_mouse_ack_stays_unknown_without_retry_or_keys(count):
    window, snapshots = receiver(), []
    api = window.fixture_mouse_api
    api.count = count
    with pytest.raises(RuntimeError, match="incomplete"):
        window.setup_foreground_click(on_status=snapshots.append)
    assert len(api.calls) == 1
    assert snapshots[-1]["setup_mouse_attempted"] is True
    assert window.setup_mouse_evidence["state"] == "unknown_no_retry"
    with pytest.raises(RuntimeError, match="never retry"):
        window.setup_foreground_click(on_status=snapshots.append)
    # Even if partial input happened to activate the fixture, no readiness pass.
    window.user.current = window.hwnd
    with pytest.raises(RuntimeError, match="Uncertain fixture mouse"):
        window.wait_for_foreground(on_status=snapshots.append)
    assert window.setup_mouse_evidence["state"] == "unknown_no_retry" and len(api.calls) == 1


def test_native_mouse_exception_is_unknown_and_never_guesses_release_cleanup():
    window, snapshots = receiver(), []
    window.fixture_mouse_api.failure = OSError("Injected native uncertainty")
    with pytest.raises(OSError):
        window.setup_foreground_click(on_status=snapshots.append)
    assert len(window.fixture_mouse_api.calls) == 1
    assert snapshots[-1]["setup_mouse"]["state"] == "unknown_no_retry"


def test_missing_durable_callback_never_reaches_native_mouse():
    window = receiver()
    with pytest.raises(RuntimeError, match="durable"):
        window.setup_foreground_click()
    assert not window.fixture_mouse_api.calls


def test_already_foreground_requires_no_mouse_and_reports_confirmation():
    window, snapshots = receiver(), []
    window.user.current = window.hwnd
    result = window.wait_for_foreground(on_status=snapshots.append)
    assert result["foreground_ready"] and result["setup_mouse"]["foreground_confirmed"]
    assert result["setup_mouse_attempted"] is False
    assert len(snapshots) == 1 and not window.fixture_mouse_api.calls


def test_partial_setup_stops_acceptance_before_keyboard_backend_construction(tmp_path, monkeypatch):
    window = receiver()
    window.ready = SimpleNamespace(wait=lambda timeout: True)
    window.fixture_mouse_api.count = 2
    window.user.PostMessageW = lambda *arguments: True
    monkeypatch.setattr(
        FIXTURE, "WindowsKeyboard", lambda: pytest.fail("Keyboard started after partial mouse")
    )
    path = tmp_path / "native-free-report.json"
    with path.open("x+", encoding="utf-8") as output:
        FIXTURE.run_acceptance(window, output)
    report = json.loads(path.read_text())
    assert report["input_attempted"] is False and report["cases"] == []
    assert report["setup_mouse_attempted"] is True
    assert report["setup_mouse"]["state"] == "unknown_no_retry" and not report["passed"]
    assert len(window.fixture_mouse_api.calls) == 1


class Function:
    def __init__(self, result=1):
        self.result, self.calls = result, []

    def __call__(self, *arguments):
        self.calls.append(arguments)
        return self.result


def test_fixture_mouse_native_abi_point_by_value_and_single_three_event_call(monkeypatch):
    names = [
        "IsWindow",
        "IsWindowVisible",
        "IsIconic",
        "GetWindowThreadProcessId",
        "GetClassNameW",
        "GetWindowLongPtrW",
        "GetClientRect",
        "ClientToScreen",
        "WindowFromPoint",
        "GetSystemMetrics",
        "GetAsyncKeyState",
        "SetThreadDpiAwarenessContext",
        "SendInput",
    ]
    user = SimpleNamespace(**{name: Function() for name in names})
    FIXTURE.bind_fixture_mouse(user)
    assert ctypes.sizeof(FIXTURE.POINT) == 8 and ctypes.sizeof(FIXTURE.RECT) == 16
    assert user.WindowFromPoint.argtypes == [FIXTURE.POINT]
    assert user.WindowFromPoint.restype is ctypes.c_void_p
    assert user.GetWindowLongPtrW.restype is ctypes.c_ssize_t
    assert user.GetAsyncKeyState.restype is ctypes.c_int16
    api = FIXTURE.FixtureMouseAPI.__new__(FIXTURE.FixtureMouseAPI)
    api.user = user
    user.SendInput.result = 3
    monkeypatch.setattr(ctypes, "set_last_error", lambda value: None, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 0, raising=False)
    inputs = FIXTURE.fixture_mouse_inputs(
        {"point": (-500, 200), "virtual_screen": (-1920, 0, 3840, 1080)}
    )
    assert api.send_input(inputs) == (3, 0)
    assert len(user.SendInput.calls) == 1 and user.SendInput.calls[0][0] == 3
    assert user.SendInput.calls[0][2] == ctypes.sizeof(FIXTURE.INPUT)
    assert 0 <= inputs[0].mi.dx <= 65535 and 0 <= inputs[0].mi.dy <= 65535
