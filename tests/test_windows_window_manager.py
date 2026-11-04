"""Authorization, deadlines and persistent window-task identity; no native effects."""

import asyncio

import pytest
from pydantic import ValidationError

import kirabridge.windows_windows as manager_module
from kirabridge.bridge_core.models import BridgeError, TaskRequest, UncertainExecution
from kirabridge.desktop_input import DesktopInput
from kirabridge.platform_adapters.windows.windows import WindowIdentity
from kirabridge.windows_windows import (
    WindowsWindowControlInput,
    WindowsWindowListInput,
    WindowsWindowManager,
    WindowsWindowTargetInput,
)

TARGET = WindowIdentity(100, 400, 132000000000000003, 401)


class Backend:
    def __init__(self, *, partial=False):
        self.effects = []
        self.partial = partial

    def inspect(self, target):
        if target != TARGET:
            raise BridgeError("windows_target_changed", "No such original target")
        return {"target": target.to_wire()}

    def list(self, limit):
        return {"windows": [self.inspect(TARGET)], "limit": limit, "effect_attempted": False}

    def control(self, target, action, *, bounds=None, before_effect=None):
        self.inspect(target)
        before_effect()
        self.effects.append((target, action, bounds))
        if self.partial:
            raise UncertainExecution("windows_window_effect_unknown", "No automatic replay")
        return {"action": action, "target": target.to_wire(), "request_accepted": True}


def window_request(task_id="window-control-1", **arguments):
    return TaskRequest(
        task_id=task_id,
        idempotency_key=task_id,
        operation="windows.window.control",
        arguments={"target": TARGET.to_wire(), "action": "maximize", **arguments},
    )


@pytest.mark.parametrize("bad", [400, True, "01", "0", "１", str(2**32)])
def test_window_identity_rejects_ambiguous_or_oversize_pid(bad):
    with pytest.raises(ValidationError):
        WindowsWindowTargetInput.model_validate({**TARGET.to_wire(), "pid": bad})


@pytest.mark.parametrize(
    "arguments",
    [
        {"action": "move_resize"},
        {"bounds": {"x": 1, "y": 2, "width": 300, "height": 200}},
        {"action": "kill"},
        {"action": "move_resize", "bounds": {"x": 1, "y": 2, "width": True, "height": 2}},
        {"action": "move_resize", "bounds": {"x": 2**31 - 1, "y": 0, "width": 2, "height": 2}},
    ],
)
def test_invalid_control_rejected_before_dispatch(arguments):
    with pytest.raises(ValidationError):
        WindowsWindowControlInput.model_validate(window_request(**arguments).arguments)


@pytest.mark.parametrize("operation", ["windows.window.list", "windows.window.control"])
def test_nonwindows_rejected_before_persistence(bridge, operation):
    bridge.windows_windows.host = "darwin"
    request = window_request()
    request.operation = operation
    if operation.endswith("list"):
        request.arguments = {}
    with pytest.raises(BridgeError, match="require Windows"):
        bridge.prepare("local", request)
    assert bridge.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_control_requires_list_permission_before_persistence(bridge):
    bridge.windows_windows.host = "win32"
    bridge.config.principals["local"].capabilities.remove("windows.window.list")
    with pytest.raises(BridgeError) as caught:
        bridge.submit("local", window_request())
    assert caught.value.code == "forbidden"
    assert bridge.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


@pytest.mark.parametrize("partial,expected", [(False, "completed"), (True, "unknown")])
async def test_original_window_task_never_replays(bridge, partial, expected):
    backend = Backend(partial=partial)
    bridge.windows_windows = WindowsWindowManager(
        bridge.security.authorize,
        bridge.desktop_input,
        backend_factory=lambda: backend,
        host="win32",
    )
    request = window_request()
    grant = bridge.security.grant("local", request)
    async with bridge:
        bridge.submit("local", request, grant)
        result = await bridge.tasks.wait("local", request.task_id, timeout=5)
        assert result["state"] == expected
        assert bridge.submit("local", request, grant)["id"] == request.task_id
        await asyncio.sleep(0.02)
        assert len(backend.effects) == 1


async def test_stale_target_fails_before_running():
    backend, events = Backend(), []
    manager = WindowsWindowManager(
        lambda *args: None,
        DesktopInput(asyncio.Lock()),
        backend_factory=lambda: backend,
        host="win32",
    )

    async def running(event):
        events.append(event)

    args = window_request(target={**TARGET.to_wire(), "hwnd": "101"}).arguments
    with pytest.raises(BridgeError) as caught:
        await manager.execute(
            {"operation": "windows.window.control", "principal": "local"},
            WindowsWindowControlInput.model_validate(args),
            running,
        )
    assert caught.value.code == "windows_target_changed"
    assert not events and not backend.effects


@pytest.mark.parametrize("expire_before", [True, False])
async def test_late_native_return_never_claims_success(monkeypatch, expire_before):
    now, backend = [0.0], Backend()
    monkeypatch.setattr(manager_module.time, "monotonic", lambda: now[0])

    def control(target, action, *, bounds=None, before_effect=None):
        if expire_before:
            now[0] = 0.02
        before_effect()
        backend.effects.append(action)
        now[0] = 0.02
        return {"request_accepted": True}

    backend.control = control
    manager = WindowsWindowManager(
        lambda *args: None,
        DesktopInput(asyncio.Lock(), timeout=0.01),
        backend_factory=lambda: backend,
        host="win32",
    )

    async def running(event):
        pass

    with pytest.raises(BridgeError) as caught:
        await manager.execute(
            {"operation": "windows.window.control", "principal": "local"},
            WindowsWindowControlInput.model_validate(window_request().arguments),
            running,
        )
    assert caught.value.code == (
        "windows_window_deadline_expired" if expire_before else "windows_window_deadline_unknown"
    )
    assert len(backend.effects) == (0 if expire_before else 1)


async def test_permission_revoked_while_marking_running_refuses_native_effect():
    backend, allowed = Backend(), [True]

    def authorize(*args):
        if not allowed[0]:
            raise BridgeError("forbidden", "Revoked")

    manager = WindowsWindowManager(
        authorize, DesktopInput(asyncio.Lock()), backend_factory=lambda: backend, host="win32"
    )

    async def running(event):
        allowed[0] = False

    with pytest.raises(BridgeError) as caught:
        await manager.execute(
            {"operation": "windows.window.control", "principal": "local"},
            WindowsWindowControlInput.model_validate(window_request().arguments),
            running,
        )
    assert caught.value.code == "forbidden" and not backend.effects


async def test_list_shares_desktop_lock_without_claiming_effect():
    desktop, backend = DesktopInput(asyncio.Lock()), Backend()
    manager = WindowsWindowManager(
        lambda *args: None, desktop, backend_factory=lambda: backend, host="win32"
    )

    async def running(event):
        assert desktop.lock.locked()

    result = await manager.execute(
        {"operation": "windows.window.list", "principal": "local"},
        WindowsWindowListInput(limit=1),
        running,
    )
    assert result["limit"] == 1 and not result["effect_attempted"] and not backend.effects
