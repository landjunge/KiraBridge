"""Injected window effects/ABI contracts; these tests are not Windows acceptance."""

import ctypes
import json
import os
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.platform_adapters.windows.windows import (
    BOOL,
    DWORD,
    ENUMPROC,
    INT_MAX,
    POINTER,
    RECT,
    SWP_ASYNCWINDOWPOS,
    SWP_NOACTIVATE,
    SWP_NOZORDER,
    WM_CLOSE,
    WindowBounds,
    WindowIdentity,
    WindowsWindowAPI,
    WindowsWindows,
    _bind_window_functions,
)


class FakeWindows:
    def __init__(self):
        self.target = WindowIdentity(2**53 + 7, 400, 134000000000000003, 401)
        self.present = True
        self.visible, self.minimized, self.maximized, self.foreground = True, False, False, False
        self.rect = {"x": 10, "y": 20, "width": 500, "height": 300}
        self.calls, self.desktop_checks, self.coordinate_entries = [], 0, 0
        self.before_snapshot, self.after_request = None, None
        self.accepted, self.failure, self.desktop_failure = True, None, None
        self.restore_failure = False
        self.handles, self.truncated = [self.target.hwnd], False

    @contextmanager
    def physical_coordinates(self):
        self.coordinate_entries += 1
        try:
            yield
        finally:
            self.coordinate_entries -= 1
            if self.restore_failure:
                raise BridgeError("windows_dpi_restore_failed", "fixture")

    def validate_desktop(self):
        self.desktop_checks += 1
        if self.desktop_failure:
            raise BridgeError(self.desktop_failure, "fixture")

    def enumerate_windows(self, limit):
        return self.handles[:limit], self.truncated or len(self.handles) > limit

    def snapshot(self, hwnd):
        assert self.coordinate_entries == 1
        if self.before_snapshot:
            self.before_snapshot()
        if not self.present:
            return None
        return {
            "target": self.target,
            "title": "Owned fixture",
            "class_name": "KiraTest",
            "rect": dict(self.rect),
            "visible": self.visible,
            "minimized": self.minimized,
            "maximized": self.maximized,
            "foreground": self.foreground,
        }

    def request(self, target, action, bounds):
        self.calls.append((target, action, bounds))
        if self.failure:
            raise self.failure
        if self.after_request:
            self.after_request(action, bounds)
        return self.accepted, 0


def error_code(code, function):
    with pytest.raises(BridgeError) as error:
        function()
    assert error.value.code == code
    return error.value


def test_exact_identity_uses_four_canonical_strings_and_no_layout():
    target = FakeWindows().target
    wire = json.loads(json.dumps(target.to_wire()))
    assert set(wire) == {"hwnd", "pid", "process_created_100ns", "thread_id"}
    assert all(type(value) is str for value in wire.values())
    assert wire["hwnd"] == "9007199254740999"
    assert WindowIdentity.from_wire(wire) == target


@pytest.mark.parametrize("value", [0, True, "0", "01", "+2", "1e3", "１", "9" * 21])
def test_identity_rejects_ambiguous_wire_values(value):
    wire = FakeWindows().target.to_wire()
    wire["hwnd"] = value
    with pytest.raises(ValueError):
        WindowIdentity.from_wire(wire)


@pytest.mark.parametrize("name,bits", [("pid", 32), ("thread_id", 32), ("hwnd", 64)])
def test_identity_native_widths_are_checked(name, bits):
    wire = FakeWindows().target.to_wire()
    wire[name] = str(2**bits)
    with pytest.raises(ValueError):
        WindowIdentity.from_wire(wire)


@pytest.mark.parametrize(
    "change",
    [
        {"x": True},
        {"x": 1.0},
        {"y": float("nan")},
        {"y": float("inf")},
        {"x": -(2**31) - 1},
        {"x": INT_MAX},
        {"y": INT_MAX},
        {"width": 0},
        {"height": 32769},
        {"height": "40"},
    ],
)
def test_invalid_or_overflowing_bounds_fail_before_hook_or_effect(change):
    api = FakeWindows()
    with pytest.raises(ValueError):
        WindowsWindows(api).control(
            api.target,
            "move_resize",
            bounds={**api.rect, **change},
            before_effect=lambda: pytest.fail("Invalid bounds reached authorization hook"),
        )
    assert not api.calls and api.desktop_checks == 0


def test_bounds_allow_negative_screen_coordinates_and_native_extremes():
    assert WindowBounds(-(2**31), -200, 32768, 1).x == -(2**31)
    assert WindowBounds(INT_MAX - 1, INT_MAX - 1, 1, 1).height == 1


def test_list_and_inspection_are_read_only_physical_and_bounded():
    api = FakeWindows()
    api.truncated = True
    result = WindowsWindows(api).list(1)
    assert result["windows"][0]["target"] == api.target.to_wire()
    assert result["truncated"] and result["limit"] == 1
    assert not result["effect_attempted"] and result["coordinate_space"] == "physical_screen_pixels"
    assert WindowsWindows(api).inspect(api.target)["rect"] == api.rect
    assert not api.calls and api.coordinate_entries == 0


@pytest.mark.parametrize("limit", [0, 65, True, 1.0])
def test_list_limit_is_strict_and_checked_before_any_native_read(limit):
    api = FakeWindows()
    with pytest.raises(ValueError):
        WindowsWindows(api).list(limit)
    assert api.desktop_checks == 0


def test_list_skips_vanished_window_without_mutating_or_inventing_target():
    api = FakeWindows()
    api.present = False
    result = WindowsWindows(api).list()
    assert result["windows"] == [] and result["skipped_unavailable"] == 1
    assert not api.calls


@pytest.mark.parametrize("field", ["pid", "thread_id", "process_created_100ns"])
def test_changed_target_before_authorization_never_attempts_effect(field):
    api = FakeWindows()
    target = api.target
    api.target = replace(api.target, **{field: getattr(api.target, field) + 1})
    error_code(
        "windows_target_changed",
        lambda: WindowsWindows(api).control(
            target, "close", before_effect=lambda: pytest.fail("Stale target reached hook")
        ),
    )
    assert not api.calls


def test_identity_is_rechecked_after_authorization_hook_before_native_mutation():
    api = FakeWindows()
    target = api.target

    def changed():
        api.target = replace(api.target, process_created_100ns=api.target.process_created_100ns + 1)

    error_code(
        "windows_target_changed",
        lambda: WindowsWindows(api).control(target, "close", before_effect=changed),
    )
    assert not api.calls


@pytest.mark.parametrize("code", ["forbidden", "windows_window_deadline_expired"])
def test_revoked_authorization_and_expired_deadline_do_not_attempt_effect(code):
    api = FakeWindows()

    def refuse():
        raise BridgeError(code, "fixture")

    error_code(code, lambda: WindowsWindows(api).control(api.target, "close", before_effect=refuse))
    assert not api.calls


def test_desktop_switch_in_hook_rejects_before_native_call():
    api = FakeWindows()

    def switched():
        api.desktop_failure = "windows_desktop_changed"

    error_code(
        "windows_desktop_changed",
        lambda: WindowsWindows(api).control(api.target, "minimize", before_effect=switched),
    )
    assert not api.calls


@pytest.mark.parametrize(
    "action", ["activate", "minimize", "maximize", "restore", "move_resize", "close"]
)
def test_async_acceptance_is_separate_from_immediate_observation(action):
    api = FakeWindows()
    api.maximized = action == "restore"
    hook = []
    result = WindowsWindows(api).control(
        api.target,
        action,
        bounds=WindowBounds(40, 50, 600, 400) if action == "move_resize" else None,
        before_effect=lambda: hook.append("authorized"),
    )
    assert len(api.calls) == len(hook) == 1
    assert result["request_accepted"] and result["effect_attempted"]
    assert not result["observed"] and result["outcome"] == "requested"
    assert not result["automatic_retry"]


def test_move_resize_observes_exact_outer_rectangle_without_implicit_restore():
    api = FakeWindows()
    api.after_request = lambda action, bounds: api.rect.update(vars(bounds))
    result = WindowsWindows(api).control(
        api.target, "move_resize", bounds=WindowBounds(-40, 50, 600, 400)
    )
    assert result["observed"] and result["observed_state"]["rect"]["x"] == -40
    assert [call[1] for call in api.calls] == ["move_resize"]


def test_close_acknowledges_request_without_any_post_request_window_inspection():
    api = FakeWindows()

    def accepted(action, bounds):
        api.before_snapshot = lambda: pytest.fail("Close performed a post-request HWND read")
        api.desktop_failure = "windows_desktop_changed"
        api.target = replace(api.target, pid=999)

    target = api.target
    api.after_request = accepted
    result = WindowsWindows(api).control(api.target, "close")
    assert result["target"] == target.to_wire()
    assert result["request_accepted"] and result["effect_attempted"]
    assert result["observed"] is False and result["outcome"] == "requested"
    assert result["observed_state"] is None and result["application_processing_confirmed"] is False
    assert result["scope"] == "WM_CLOSE accepted; completion requires independent observation"
    assert api.desktop_checks == 4  # Both exact pre-effect guards, no post-effect desktop work.
    assert len(api.calls) == 1


@pytest.mark.parametrize("action", ["activate", "minimize", "maximize", "restore", "move_resize"])
def test_other_actions_still_reject_reused_hwnd_after_attempt_as_unknown(action):
    api = FakeWindows()
    target = api.target
    api.after_request = lambda action, bounds: setattr(api, "target", replace(target, pid=999))
    error = error_code(
        "windows_window_effect_unknown",
        lambda: WindowsWindows(api).control(
            target, action, bounds=WindowBounds(0, 0, 100, 100) if action == "move_resize" else None
        ),
    )
    assert isinstance(error, UncertainExecution) and len(api.calls) == 1


@pytest.mark.parametrize("accepted,failure", [(False, None), (True, OSError("Unconfirmed post"))])
def test_failed_native_close_is_unknown_with_ack_evidence_without_retry(accepted, failure):
    api = FakeWindows()
    api.accepted, api.failure = accepted, failure
    error = error_code(
        "windows_window_effect_unknown", lambda: WindowsWindows(api).control(api.target, "close")
    )
    assert error.provider_error["native_request_accepted"] is (False if failure is None else None)
    assert len(api.calls) == 1


@pytest.mark.parametrize("failure", ["false", "exception", "readback", "desktop", "dpi_restore"])
def test_all_failure_paths_after_native_attempt_are_unknown_without_retry(failure):
    api = FakeWindows()
    if failure == "false":
        api.accepted = False
    elif failure == "exception":
        api.failure = OSError("fixture")
    elif failure == "readback":

        def fail_readback(action, bounds):
            api.before_snapshot = lambda: (_ for _ in ()).throw(OSError("fixture"))

        api.after_request = fail_readback
    elif failure == "desktop":
        api.after_request = lambda action, bounds: setattr(
            api, "desktop_failure", "windows_desktop_changed"
        )
    else:
        api.restore_failure = True
    error = error_code(
        "windows_window_effect_unknown", lambda: WindowsWindows(api).control(api.target, "activate")
    )
    assert isinstance(error, UncertainExecution) and len(api.calls) == 1
    assert api.coordinate_entries == 0


def test_concurrent_window_operation_does_not_wait_or_attempt_any_effect():
    api = FakeWindows()
    backend = WindowsWindows(api)
    backend._lock.acquire()
    try:
        error_code("windows_window_busy", lambda: backend.control(api.target, "close"))
    finally:
        backend._lock.release()
    assert not api.calls and api.desktop_checks == 0


class Function:
    def __init__(self, result=1):
        self.calls, self.result = [], result

    def __call__(self, *arguments):
        self.calls.append(arguments)
        return self.result


def native_api_stub(monkeypatch):
    names = [
        "EnumWindows",
        "EnumDesktopWindows",
        "GetAncestor",
        "GetWindowRect",
        "IsWindowVisible",
        "IsIconic",
        "IsZoomed",
        "GetWindowTextW",
        "GetClassNameW",
        "SetThreadDpiAwarenessContext",
        "SetForegroundWindow",
        "ShowWindowAsync",
        "SetWindowPos",
        "PostMessageW",
    ]
    user = SimpleNamespace(**{name: Function() for name in names})
    _bind_window_functions(user)
    api = WindowsWindowAPI.__new__(WindowsWindowAPI)
    api.user = user
    monkeypatch.setattr(ctypes, "set_last_error", lambda error: None, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 0, raising=False)
    return api


def test_native_abi_preserves_llp64_rect_callback_and_pointer_message_widths(monkeypatch):
    api = native_api_stub(monkeypatch)
    assert ctypes.sizeof(RECT) == 16 and RECT.bottom.offset == 12
    assert ctypes.sizeof(DWORD) == ctypes.sizeof(BOOL) == 4
    assert api.user.SetForegroundWindow.argtypes == [POINTER]
    assert api.user.EnumWindows.argtypes == [ENUMPROC, ctypes.c_ssize_t]
    assert api.user.PostMessageW.argtypes == [POINTER, DWORD, ctypes.c_size_t, ctypes.c_ssize_t]
    assert api.user.SetThreadDpiAwarenessContext.restype is POINTER


@pytest.mark.parametrize("action,command", [("minimize", 6), ("maximize", 3), ("restore", 9)])
def test_native_show_uses_async_single_request(action, command, monkeypatch):
    api = native_api_stub(monkeypatch)
    target = FakeWindows().target
    assert api.request(target, action, None) == (True, 0)
    assert api.user.ShowWindowAsync.calls == [(target.hwnd, command)]
    assert not api.user.SetForegroundWindow.calls


def test_native_move_keeps_zorder_and_foreground_and_posts_close_without_termination(monkeypatch):
    api = native_api_stub(monkeypatch)
    target = FakeWindows().target
    api.request(target, "move_resize", WindowBounds(-30, 40, 500, 300))
    assert api.user.SetWindowPos.calls == [
        (target.hwnd, None, -30, 40, 500, 300, SWP_ASYNCWINDOWPOS | SWP_NOACTIVATE | SWP_NOZORDER)
    ]
    api.request(target, "close", None)
    assert api.user.PostMessageW.calls == [(target.hwnd, WM_CLOSE, 0, 0)]
    assert not api.user.SetForegroundWindow.calls


def test_native_identity_refuses_child_before_process_query_or_mutation(monkeypatch):
    api = native_api_stub(monkeypatch)
    api.user.IsWindow = Function(1)
    api.user.GetAncestor = Function(999)
    error_code("windows_target_not_top_level", lambda: api._identity(100))
    assert not api.user.PostMessageW.calls and not api.user.SetWindowPos.calls


def test_native_identity_rechecks_owner_after_process_creation_query(monkeypatch):
    api = native_api_stub(monkeypatch)
    api.user.IsWindow = Function(1)
    api.user.GetAncestor = lambda hwnd, flag: hwnd
    owner = [400, 401]

    def get_owner(hwnd, pointer):
        ctypes.cast(pointer, ctypes.POINTER(DWORD))[0] = owner[0]
        return owner[1]

    def created(pid):
        owner[0] = 999
        return 134000000000000003

    api.user.GetWindowThreadProcessId = get_owner
    api._on_current_desktop = lambda hwnd: None
    api._identity_api = SimpleNamespace(_created=created)
    error_code("windows_target_changed", lambda: api._identity(100))
    assert not api.user.PostMessageW.calls


def test_native_desktop_membership_is_not_guessed_from_handle_existence(monkeypatch):
    api = native_api_stub(monkeypatch)
    api.user.GetThreadDesktop = Function(700)
    api.kernel = SimpleNamespace(GetCurrentThreadId=Function(401))

    def enumerate_desktop(desktop, callback, parameter):
        assert desktop == 700
        return callback(100, parameter) and callback(200, parameter)

    api.user.EnumDesktopWindows = enumerate_desktop
    api._on_current_desktop(200)
    error_code("windows_target_changed", lambda: api._on_current_desktop(999))


def test_native_enumeration_excludes_hidden_and_child_windows_and_is_bounded(monkeypatch):
    api = native_api_stub(monkeypatch)
    seen = []
    api.user.IsWindowVisible = lambda hwnd: hwnd != 100
    api.user.GetAncestor = lambda hwnd, flag: 300 if hwnd == 200 else hwnd

    def enumerate_windows(callback, parameter):
        for hwnd in [100, 200, 300, 400, 500]:
            seen.append(hwnd)
            if not callback(hwnd, parameter):
                return 0
        return 1

    api.user.EnumWindows = enumerate_windows
    assert api.enumerate_windows(1) == ([300], True)
    assert seen == [100, 200, 300, 400]


def test_native_dpi_context_is_restored_even_after_read_failure(monkeypatch):
    api = native_api_stub(monkeypatch)
    api.user.SetThreadDpiAwarenessContext.result = 700
    with pytest.raises(RuntimeError):
        with api.physical_coordinates():
            raise RuntimeError("fixture")
    assert api.user.SetThreadDpiAwarenessContext.calls == [(POINTER(-4).value,), (700,)]


def test_snapshot_disappearance_at_final_identity_is_freshly_confirmed_absence(monkeypatch):
    api = native_api_stub(monkeypatch)
    identities = iter([FakeWindows().target, None])
    api._identity = lambda hwnd: next(identities)
    api.user.GetForegroundWindow = Function(0)
    api.user.IsWindow = Function(0)
    assert api.snapshot(FakeWindows().target.hwnd) is None


def disappearing_native_api(monkeypatch, stage):
    api = native_api_stub(monkeypatch)
    state = {"present": True, "owner_queries": 0}
    api.user.IsWindow = lambda hwnd: int(state["present"])

    def ancestor(hwnd, flag):
        if stage in {"ancestor", "real_child_then_gone"}:
            state["present"] = False
            return None if stage == "ancestor" else 999
        return hwnd

    def desktop(hwnd):
        if stage in {"desktop", "unavailable_desktop"}:
            state["present"] = False
            raise BridgeError(
                "windows_target_changed" if stage == "desktop" else "windows_desktop_unavailable",
                "private exception text",
            )

    def owner(hwnd, pointer):
        state["owner_queries"] += 1
        if stage == "missing_owner" or (stage == "missing_recheck" and state["owner_queries"] == 2):
            state["present"] = False
            return 0
        value = 400
        if stage == "owner_mismatch_then_gone" and state["owner_queries"] == 2:
            value, state["present"] = 999, False
        ctypes.cast(pointer, ctypes.POINTER(DWORD))[0] = value
        return 401

    def created(pid):
        if stage in {"creation", "live_creation_error"}:
            state["present"] = stage == "live_creation_error"
            raise BridgeError("windows_target_unavailable", "private exception text")
        return 134000000000000003

    def rectangle(hwnd, pointer):
        if stage in {"rectangle", "live_rectangle_error"}:
            state["present"] = stage == "live_rectangle_error"
            return 0
        return 1

    api.user.GetAncestor = ancestor
    api._on_current_desktop = desktop
    api.user.GetWindowThreadProcessId = owner
    api._identity_api = SimpleNamespace(_created=created)
    api.user.GetWindowRect = rectangle
    api.user.GetForegroundWindow = Function(100)
    return api


@pytest.mark.parametrize(
    "stage", ["ancestor", "desktop", "missing_owner", "creation", "missing_recheck", "rectangle"]
)
def test_disappearance_during_native_read_returns_only_freshly_confirmed_absence(
    monkeypatch, stage
):
    api = disappearing_native_api(monkeypatch, stage)
    assert api.snapshot(100) is None


@pytest.mark.parametrize(
    "stage,code",
    [
        ("real_child_then_gone", "windows_target_not_top_level"),
        ("owner_mismatch_then_gone", "windows_target_changed"),
        ("live_rectangle_error", "windows_target_unavailable"),
        ("live_creation_error", "windows_target_unavailable"),
        ("unavailable_desktop", "windows_desktop_unavailable"),
    ],
)
def test_observed_contradictions_or_unrelated_errors_are_not_downgraded_to_absence(
    monkeypatch, stage, code
):
    api = disappearing_native_api(monkeypatch, stage)
    error_code(code, lambda: api.snapshot(100))


@pytest.mark.parametrize("first_missing", [True, False])
def test_missing_identity_followed_by_present_same_token_handle_is_not_closed(
    monkeypatch, first_missing
):
    api = native_api_stub(monkeypatch)
    identities = iter([None] if first_missing else [FakeWindows().target, None])
    api._identity = lambda hwnd: next(identities)
    api.user.IsWindow = Function(1)
    api.user.GetForegroundWindow = Function(0)
    error_code("windows_target_changed", lambda: api.snapshot(100))


@pytest.mark.parametrize(
    "failure,acknowledged,cause",
    [
        ("false", False, "windows_window_request_unconfirmed"),
        ("request_exception", None, None),
        ("readback", True, "windows_target_changed"),
    ],
)
def test_uncertain_provider_error_keeps_only_confirmed_ack_and_bounded_cause(
    failure, acknowledged, cause
):
    api = FakeWindows()
    if failure == "false":
        api.accepted = False
    elif failure == "request_exception":
        api.failure = OSError("secret URL/password must not enter provider evidence")
    else:

        def readback(action, bounds):
            api.target = replace(api.target, pid=999)

        api.after_request = readback
    action = "minimize" if failure == "readback" else "close"
    error = error_code(
        "windows_window_effect_unknown", lambda: WindowsWindows(api).control(api.target, action)
    )
    assert error.provider_error["native_request_accepted"] is acknowledged
    assert error.provider_error["cause_code"] == cause
    assert "secret" not in json.dumps(error.provider_error)
    assert len(api.calls) == 1


def test_untrusted_exception_name_code_and_message_are_not_provider_diagnostics():
    api = FakeWindows()
    secret_error = type("PrivatePasswordToken", (Exception,), {})
    api.failure = secret_error("https://secret.invalid/capability")
    error = error_code(
        "windows_window_effect_unknown", lambda: WindowsWindows(api).control(api.target, "close")
    )
    assert error.provider_error == {
        "native_request_accepted": None,
        "cause_type": "Exception",
        "cause_code": None,
    }


@pytest.mark.skipif(os.name == "nt", reason="Native constructor is valid on Windows")
def test_default_native_constructor_cannot_control_host_macos_windows():
    error_code("unsupported_platform", WindowsWindows)
