import asyncio

import pytest
from test_session_ports import manager_without_core

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.linux.owned_terminal import LinuxOwnedTerminal
from kirabridge.session_manager import SessionReference


@pytest.fixture
async def terminal():
    owned = LinuxOwnedTerminal()
    yield owned
    for pane_id in list(owned._sessions):
        await owned.close(pane_id)


async def test_owned_pty_roundtrip(terminal, tmp_path):
    opened = await terminal.open_shell(str(tmp_path))
    assert opened["pane_id"].startswith("linux:")
    assert opened["busy"] is False
    await terminal.insert(opened["pane_id"], "printf 'hi\\n'")
    await terminal.press_return(opened["pane_id"])
    text = ""
    for _ in range(50):
        text = await terminal.read(opened["pane_id"])
        if "hi" in text and text.rstrip().endswith("KIRA_OWNED>"):
            break
        await asyncio.sleep(0.02)
    assert "hi" in text
    rows = await terminal.catalog()
    assert [row["pane_id"] for row in rows] == [opened["pane_id"]]
    await terminal.close(opened["pane_id"])
    assert await terminal.catalog() == []


async def test_owned_pty_rejects_control_characters(terminal, tmp_path):
    opened = await terminal.open_shell(str(tmp_path))
    with pytest.raises(BridgeError) as error:
        await terminal.insert(opened["pane_id"], "echo\nhidden")
    assert error.value.code == "invalid_arguments"


def test_session_reference_accepts_owned_pane():
    pane = SessionReference(pane_id="linux:42", expected_pid=42)
    assert pane.pane_id == "linux:42"


async def test_linux_selection_does_not_use_tmux():
    manager, _native, tmux, _seen = manager_without_core(rows=[])

    class Owned:
        async def catalog(self):
            return [
                {
                    "pane_id": "linux:9",
                    "expected_pid": 9,
                    "tty": "/dev/pts/9",
                    "busy": False,
                    "processes": [],
                }
            ]

    manager.linux = Owned()
    selected = await manager.selected("grok", "linux:9", 9)
    assert selected["pane_id"] == "linux:9"
    assert tmux.calls == []
