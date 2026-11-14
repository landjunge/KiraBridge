"""Real Core control tasks cannot interrupt an original owner's desktop turn."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import request, submit


def peers(bridge):
    rows = [
        {
            "pane_id": f"terminal:{window}:ttys{tty:03d}",
            "expected_pid": pid,
            "window_id": window,
            "visual_window_id": window,
            "tty": f"/dev/ttys{tty:03d}",
            "script_tab_count": 1,
            "tab_count": 1,
            "ui_window_count": 2,
            "identity_ambiguous": False,
            "selection_ambiguous": False,
            "processes": [{"pid": pid, "name": "zsh"}],
        }
        for window, tty, pid in [(101, 1, 345), (202, 2, 346)]
    ]

    async def catalog():
        assert bridge.sessions.lock.locked()
        return deepcopy(rows)

    async def focused(pane):
        assert bridge.sessions.lock.locked() and pane == rows[0]["pane_id"]
        return {"focused": True}

    async def closed(pane):
        assert bridge.sessions.lock.locked() and pane == rows[0]["pane_id"]
        return {"closed": True, "remaining": 1}

    native = SimpleNamespace(
        available=True,
        catalog=AsyncMock(side_effect=catalog),
        focus=AsyncMock(side_effect=focused),
        close_tab=AsyncMock(side_effect=closed),
        front_tab=AsyncMock(return_value={"window_id": 101, "tty": rows[0]["tty"]}),
    )
    bridge.sessions.terminal_app = native
    return rows, native


def claimed(bridge, operation, arguments, identifier):
    bridge.tasks.preflight = None
    submit(bridge, request(operation, arguments, task_id=identifier))
    task = bridge.store.claim_exact(bridge.tasks.owner, bridge.config.lease_seconds, identifier)
    assert task and task["request_sha256"]
    return task


@pytest.mark.parametrize("operation", ["session.focus", "session.close"])
@pytest.mark.parametrize("change", ["stable", "revoked", "pid"])
async def test_control_waits_for_real_original_turn_then_observes_fresh_authority(
    bridge, config, operation, change
):
    config.principals["local"].capabilities.append("session.inspect")
    rows, native = peers(bridge)
    target = {"pane_id": rows[0]["pane_id"], "expected_pid": rows[0]["expected_pid"]}
    text = claimed(bridge, "session.input", {**target, "text": "original text"}, "original-text")
    control = claimed(bridge, operation, target, "control")
    bridge.tasks.executor = bridge._execute_operation  # Only the native peer is synthetic.
    async with bridge.desktop_input.transaction() as turn:
        original = bridge.terminal_input.bind_stored("local", text["id"], turn)
        original.check("terminal.input.inspect")
        turn.mark_attempted()
        pending = asyncio.create_task(bridge.tasks._execute(control))
        try:
            for _ in range(20):
                if bridge.store.get(control["id"])["state"] == "running":
                    break
                await asyncio.sleep(0)
            assert bridge.store.get(control["id"])["state"] == "running"
            assert not pending.done()
            native.catalog.assert_not_awaited()
            native.focus.assert_not_awaited()
            native.close_tab.assert_not_awaited()
            native.front_tab.assert_not_awaited()
            if change == "revoked":
                config.principals["local"].capabilities.remove("session.input")
            elif change == "pid":
                rows[0]["expected_pid"] += 100
        except BaseException:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            raise
    await asyncio.wait_for(pending, 2)
    final = bridge.store.get(control["id"])
    if change == "stable":
        assert final["state"] == "completed"
        assert final["result"]["focused" if operation == "session.focus" else "closed"] is True
        (native.focus if operation == "session.focus" else native.close_tab).assert_awaited_once()
    else:
        assert final["error"]["code"] == (
            "forbidden" if change == "revoked" else "session_selection_changed"
        )
        native.focus.assert_not_awaited()
        native.close_tab.assert_not_awaited()
        native.front_tab.assert_not_awaited()
        if change == "revoked":
            native.catalog.assert_not_awaited()
    assert not bridge.sessions.lock.locked()


@pytest.mark.parametrize("shape", ["physical_multitab", "ambiguous", "missing"])
async def test_close_refuses_physical_multitab_or_unconfirmed_target_before_native_effect(
    bridge, config, shape
):
    config.principals["local"].capabilities.append("session.inspect")
    rows, native = peers(bridge)
    if shape == "physical_multitab":
        rows[0]["tab_count"] = 3  # Each macOS scripting window still has exactly one tab.
    elif shape == "ambiguous":
        rows[0]["selection_ambiguous"] = True
    else:
        del rows[0]["visual_window_id"]
    task = claimed(
        bridge, "session.close", {"pane_id": rows[0]["pane_id"], "expected_pid": 345}, "close"
    )
    bridge.tasks.executor = bridge._execute_operation
    await bridge.tasks._execute(task)
    assert bridge.store.get(task["id"])["error"]["code"] == "terminal_window_unsupported"
    native.close_tab.assert_not_awaited()
