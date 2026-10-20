import asyncio
import plistlib
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.desktop import DESKTOP_MESSAGES, MacDesktop, console_state


def raw_users(*users, root_list=False):
    root = {"IOConsoleUsers": list(users)}
    return plistlib.dumps([root] if root_list else root)


@pytest.mark.parametrize("root_list", [False, True])
@pytest.mark.parametrize("locked", [False, True])
def test_console_state_uses_matching_user_and_actual_lock_flag(root_list, locked):
    raw = raw_users(
        {"kCGSSessionUserIDKey": 99, "CGSSessionScreenIsLocked": True},
        {
            "kCGSSessionUserIDKey": 501,
            "kCGSSessionOnConsoleKey": True,
            "CGSSessionScreenIsLocked": locked,
        },
        root_list=root_list,
    )
    assert console_state(raw, 501) == ("desktop_locked" if locked else "available")


def test_another_users_active_desktop_does_not_confirm_our_session():
    raw = raw_users(
        {"kCGSSessionUserIDKey": 501, "kCGSSessionOnConsoleKey": False},
        {"kCGSSessionUserIDKey": 502, "kCGSSessionOnConsoleKey": True},
    )
    assert console_state(raw, 501) == "desktop_session_inactive"
    assert console_state(raw, 503) == "unknown"


@pytest.mark.parametrize("root", [{}, {"IOConsoleUsers": 1}, {"IOConsoleUsers": [1, {}]}, []])
def test_absent_or_unrecognized_console_data_is_unknown(root):
    assert console_state(plistlib.dumps(root), 501) == "unknown"


@pytest.mark.parametrize("failure", ["invalid_plist", "nonzero", "missing", "timeout"])
async def test_extra_probe_failure_does_not_remove_terminal_permission(monkeypatch, failure):
    monkeypatch.setattr(
        "kirabridge.platform_adapters.desktop.sys", SimpleNamespace(platform="darwin")
    )
    events = []

    class Child:
        returncode = None

        async def communicate(self):
            if failure == "timeout":
                raise TimeoutError
            self.returncode = 1 if failure == "nonzero" else 0
            return b"invalid plist", b""

        def kill(self):
            events.append("owned probe killed")

        async def wait(self):
            events.append("owned probe reaped")
            self.returncode = -9

    async def spawn(*argv, **kwargs):
        assert argv == ("/usr/sbin/ioreg", "-n", "Root", "-d1", "-a")
        events.append("probe")
        if failure == "missing":
            raise FileNotFoundError
        return Child()

    monkeypatch.setattr(
        "kirabridge.platform_adapters.desktop.asyncio.create_subprocess_exec", spawn
    )
    desktop = MacDesktop()
    await desktop.require_interactive()
    assert desktop.last["state"] == "unknown"
    assert desktop.last["observed_at"] is not None
    assert events == (
        ["probe", "owned probe killed", "owned probe reaped"] if failure == "timeout" else ["probe"]
    )


async def test_probe_cancellation_reaps_only_its_own_child(monkeypatch):
    monkeypatch.setattr(
        "kirabridge.platform_adapters.desktop.sys", SimpleNamespace(platform="darwin")
    )
    events = []

    class Child:
        returncode = None

        async def communicate(self):
            raise asyncio.CancelledError

        def kill(self):
            events.append("owned probe killed")

        async def wait(self):
            events.append("owned probe reaped")

    async def spawn(*args, **kwargs):
        return Child()

    monkeypatch.setattr(
        "kirabridge.platform_adapters.desktop.asyncio.create_subprocess_exec", spawn
    )
    with pytest.raises(asyncio.CancelledError):
        await MacDesktop().probe()
    assert events == ["owned probe killed", "owned probe reaped"]


@pytest.mark.parametrize("code", DESKTOP_MESSAGES)
async def test_known_unavailable_desktop_blocks_osascript_before_any_ui_action(
    bridge, monkeypatch, code
):
    monkeypatch.setattr("kirabridge.session_manager.sys", SimpleNamespace(platform="darwin"))

    async def state():
        return {"state": code}

    async def forbidden(*args, **kwargs):
        pytest.fail("No osascript, window, paste, Return, or replacement process allowed")

    monkeypatch.setattr(bridge.sessions.desktop, "probe", state)
    monkeypatch.setattr("kirabridge.session_manager.asyncio.create_subprocess_exec", forbidden)
    with pytest.raises(BridgeError) as error:
        await bridge.sessions.native("must never execute", mutation=True)
    assert error.value.code == code


@pytest.mark.parametrize("code", DESKTOP_MESSAGES)
async def test_selected_native_target_retains_concrete_desktop_error(
    bridge, config, monkeypatch, code
):
    config.principals["local"].capabilities += ["session.inspect"]

    async def catalog(principal):
        return {
            "status": "available",  # An unrelated tmux pane does not unblock Terminal.app.
            "sessions": [{"pane_id": "%1", "expected_pid": 100}],
            "transport_errors": {"terminal_app": {"code": code, "message": DESKTOP_MESSAGES[code]}},
        }

    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    with pytest.raises(BridgeError) as error:
        await bridge.sessions.selected("local", "terminal:123:ttys001", 123)
    assert error.value.code == code
    assert (await bridge.sessions.selected("local", "%1", 100))["expected_pid"] == 100
