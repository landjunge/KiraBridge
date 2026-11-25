import asyncio
from types import SimpleNamespace

import pytest
from test_session_ports import manager_without_core

import kirabridge.session_manager as sessions
from kirabridge.bridge_core.models import BridgeError
from kirabridge.session_manager import SessionInput


def linux_manager(monkeypatch):
    manager, native, tmux, _ = manager_without_core(rows=[])
    native.available = False
    monkeypatch.setattr(sessions.sys, "platform", "linux")

    async def missing_tmux():
        raise BridgeError("session_transport_unavailable", "tmux is not installed")

    tmux.catalog = missing_tmux
    manager.input_release = SimpleNamespace(
        dispatch=lambda principal, args, task_id: args,
        sent=lambda principal, task_id: None,
    )
    return manager, native, tmux


async def test_linux_default_catalog_available_without_tmux_and_without_sessions(monkeypatch):
    manager, _, _ = linux_manager(monkeypatch)
    result = await manager.catalog("chatgpt")
    assert result["transport"] == "linux" and result["status"] == "available"
    assert result["sessions"] == []
    assert result["transport_errors"]["tmux"]["code"] == "session_transport_unavailable"


async def test_chatgpt_owned_linux_roundtrip_without_tmux(monkeypatch, tmp_path):
    manager, native, tmux = linux_manager(monkeypatch)
    opened = await manager.linux.open_shell(str(tmp_path))
    pane, pid = opened["pane_id"], opened["expected_pid"]
    try:
        catalog = await manager.catalog("chatgpt")
        assert [row["pane_id"] for row in catalog["sessions"]] == [pane]
        with pytest.raises(BridgeError) as wrong_pid:
            await manager.selected("chatgpt", pane, pid + 1)
        assert wrong_pid.value.code == "session_selection_changed"
        await manager.send(
            "chatgpt",
            SessionInput(
                pane_id=pane,
                expected_pid=pid,
                text="printf 'LINUX_OWNED_ROUTE_OK\\n'",
                submit=True,
                require_idle=True,
            ),
            task_id="owned-roundtrip",
        )
        async with asyncio.timeout(5):
            while True:
                read = await manager.read("chatgpt", pane, pid)
                if "LINUX_OWNED_ROUTE_OK\r\n" in read["text"] and read["text"].rstrip().endswith(
                    "KIRA_OWNED>"
                ):
                    break
                await asyncio.sleep(0.02)
        closed = await manager.close_tab("chatgpt", pane, pid)
        assert closed["closed"] is True
        assert (await manager.catalog("chatgpt"))["sessions"] == []
        assert native.calls == tmux.calls == []
    finally:
        if pane in manager.linux._sessions:
            await manager.linux.close(pane)
