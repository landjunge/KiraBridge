"""Injected Win32 process readback; never open or signal a native process."""

import ctypes
from types import SimpleNamespace

import pytest

from kirabridge import windows_setup_runtime as runtime
from kirabridge.bridge_core.models import BridgeError

CREATED = 134382404205187098
IMAGE = r"C:\owned\Python314\python.exe"


class Kernel:
    def __init__(self, *, state=258, image_ok=True, times_ok=True, handle=0x100000010):
        self.calls = []
        self.state, self.image_ok, self.times_ok, self.handle = state, image_ok, times_ok, handle
        self.OpenProcess = self.function("open", lambda *args: self.handle)
        self.GetProcessTimes = self.function("times", self.times)
        self.WaitForSingleObject = self.function("wait", lambda *args: self.state)
        self.QueryFullProcessImageNameW = self.function("image", self.image)
        self.CloseHandle = self.function("close", lambda *args: 1)

    def function(self, name, operation):
        def call(*args):
            self.calls.append((name, args))
            return operation(*args)

        return call

    def times(self, handle, created, *args):
        created._obj.value = CREATED
        return self.times_ok

    def image(self, handle, flags, destination, length):
        if self.state == 0:
            pytest.fail("An exited native process must not require an image query")
        destination.value = IMAGE
        length._obj.value = len(IMAGE)
        return self.image_ok


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setattr(runtime, "sys", SimpleNamespace(platform="win32"))

    def install(**settings):
        kernel = Kernel(**settings)
        monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
        return kernel

    return install


def names(kernel):
    return [name for name, _ in kernel.calls]


def test_exited_creation_time_and_signaled_handle_do_not_require_process_image(native):
    kernel = native(state=0, image_ok=False)
    observed = runtime.process_identity(123)
    assert observed == {
        "pid": 123,
        "created_100ns": str(CREATED),
        "image": None,
        "running": False,
    }
    assert names(kernel) == ["open", "times", "wait", "close"]
    assert kernel.calls[2][1] == (kernel.handle, 0)


def test_running_process_requires_image_after_creation_and_wait_checks(native):
    kernel = native()
    assert runtime.process_identity(123) == {
        "pid": 123,
        "created_100ns": str(CREATED),
        "image": IMAGE,
        "running": True,
    }
    assert names(kernel) == ["open", "times", "wait", "image", "close"]
    assert kernel.OpenProcess.restype is ctypes.c_void_p
    assert kernel.QueryFullProcessImageNameW.argtypes[0] is ctypes.c_void_p
    assert kernel.calls[-1][1] == (kernel.handle,)


def test_running_image_query_failure_remains_unknown_and_always_closes_handle(native):
    kernel = native(image_ok=False)
    with pytest.raises(BridgeError) as caught:
        runtime.process_identity(123)
    assert caught.value.code == "setup_process_unavailable"
    assert names(kernel) == ["open", "times", "wait", "image", "close"]


@pytest.mark.parametrize("state", [0, 258])
def test_missing_creation_time_never_confirms_exit_or_queries_image(native, state):
    kernel = native(state=state, times_ok=False)
    with pytest.raises(BridgeError) as caught:
        runtime.process_identity(123)
    assert caught.value.code == "setup_process_unavailable"
    assert names(kernel) == ["open", "times", "close"]


@pytest.mark.parametrize("state", [0xFFFFFFFF, 0x80, 1])
def test_unknown_wait_result_is_never_absence_or_running_identity(native, state):
    kernel = native(state=state)
    with pytest.raises(BridgeError) as caught:
        runtime.process_identity(123)
    assert caught.value.code == "setup_process_unavailable"
    assert names(kernel) == ["open", "times", "wait", "close"]


@pytest.mark.parametrize("error,absent", [(87, True), (5, False)])
def test_open_process_access_denied_is_not_absence(native, monkeypatch, error, absent):
    kernel = native(handle=0)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: error, raising=False)
    if absent:
        assert runtime.process_identity(123) is None
    else:
        with pytest.raises(BridgeError) as caught:
            runtime.process_identity(123)
        assert caught.value.code == "setup_process_unavailable"
    assert names(kernel) == ["open"]


def test_same_process_does_not_adopt_signaled_generation_even_with_matching_creation(native):
    kernel = native(state=0)
    assert not runtime.same_process({"pid": 123, "created_100ns": str(CREATED), "image": IMAGE})
    assert names(kernel) == ["open", "times", "wait", "close"]


def test_saved_tunnel_original_absence_accepts_exited_generation_without_image(native):
    from kirabridge import windows_setup_client

    kernel = native(state=0)
    assert windows_setup_client.original_absent(
        {"pid": 123, "created_100ns": str(CREATED), "image": IMAGE, "running": True}
    )
    assert names(kernel) == ["open", "times", "wait", "close"]
