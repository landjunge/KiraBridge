"""Reuse each selected row for its screen read, never for a later dispatch."""

import copy
import json
import re
import shlex
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from conftest import request

from kirabridge.bridge_core.models import BridgeError
from kirabridge.private_files import write_private
from kirabridge.visible_terminal import VisibleTerminalInput


@pytest.fixture
def command(bridge, config, monkeypatch):
    policy = config.principals["local"]
    policy.capabilities.append("session.inspect")
    policy.approval_mode = "automatic"
    monkeypatch.setattr(bridge.tasks, "preflight", None)
    row = {
        "pane_id": "terminal:123:ttys004",
        "expected_pid": 345,
        "tty": "/dev/ttys004",
        "transport": "terminal_app",
        "busy": False,
        "processes": [{"pid": 345, "ppid": 344, "name": "zsh", "image": "/bin/zsh"}],
    }
    state = {"catalogs": 0, "reads": [], "identities": [], "posts": [], "row": row}

    async def catalog():
        state["catalogs"] += 1
        result = copy.deepcopy(row)
        if state.get("revoke_after_catalog"):
            policy.capabilities.remove("session.inspect")
        if state["catalogs"] == 3 and state.get("final_busy"):
            result["busy"] = True
        return [result]

    async def read(pane):
        assert pane == row["pane_id"]
        state["reads"].append(state["catalogs"])
        return "host project% "

    async def identity(pid):
        state["identities"].append(pid)
        return "501 ttys004 Wed Nov 4 12:00:00 2026"

    async def send(selected, text, observed_identity):
        assert all(selected[key] == value for key, value in row.items())
        assert observed_identity.startswith("501 ttys004 ")
        state["posts"].append(text)
        state["catalogs_at_dispatch"] = state["catalogs"]
        state["reads_at_dispatch"] = len(state["reads"])
        script = Path(shlex.split(text)[-1])
        nonce = re.search(r'"nonce": "([a-f0-9]+)"', script.read_text())[1]
        write_private(script.parent / "result.json", json.dumps({"nonce": nonce, "exit_code": 0}))

    transport = bridge.sessions.terminal_app
    monkeypatch.setattr(type(transport), "available", property(lambda self: True))
    monkeypatch.setattr(transport, "catalog", catalog)
    monkeypatch.setattr(transport, "read", read)
    monkeypatch.setattr(transport, "process_identity", identity)
    monkeypatch.setattr(transport, "send_confirmed", send)
    monkeypatch.setattr(bridge.sessions.tmux, "catalog", AsyncMock(return_value=[]))
    args = {
        "argv": [sys.executable, "-c", "pass"],
        "cwd": policy.roots[0],
        "pane_id": row["pane_id"],
        "expected_pid": row["expected_pid"],
        "create_if_needed": False,
    }
    return bridge, state, args


async def test_visible_command_uses_four_catalogues_with_fresh_screens_and_no_replay(command):
    bridge, state, args = command
    value = request("terminal.visible", args, task_id="scoped-command")
    async with bridge:
        bridge.prepare("local", value)
        task = await bridge.tasks.wait("local", value.task_id, 5)
        assert task["state"] == "completed", task
        assert task["result"]["exit_code"] == 0
        before_duplicate = copy.deepcopy(state)
        assert bridge.prepare("local", value)["state"] == "completed"
        assert state == before_duplicate
    # Actual SessionManager.selected/read/catalog methods ran throughout.
    assert state["catalogs"] == 4
    assert state["catalogs_at_dispatch"] == 3
    assert state["reads_at_dispatch"] == 2
    assert state["reads"] == [1, 3, 4]
    assert state["identities"] == [345] and len(state["posts"]) == 1


async def test_visible_command_final_busy_change_still_stops_before_any_input(command):
    bridge, state, args = command
    state["final_busy"] = True
    running = AsyncMock()
    with pytest.raises(BridgeError) as failure:
        await bridge.visible_terminal.execute(
            {"id": "final-switch", "principal": "local"},
            VisibleTerminalInput.model_validate(args),
            running,
        )
    assert failure.value.code == "visible_target_changed"
    assert state["catalogs"] == 3 and state["reads"] == [1]
    assert not state["identities"] and not state["posts"]
    running.assert_not_awaited()


@pytest.mark.parametrize("failure", ["ambiguous", "revoked"])
async def test_scoped_shell_read_preserves_ambiguity_and_fresh_read_permission(command, failure):
    bridge, state, args = command
    if failure == "ambiguous":
        state["row"]["identity_ambiguous"] = True
        # Auto-selection has no initial selected() call to reject ambiguity.
        args.pop("pane_id")
        args.pop("expected_pid")
    else:
        state["revoke_after_catalog"] = True
    running = AsyncMock()
    with pytest.raises(BridgeError) as error:
        await bridge.visible_terminal.execute(
            {"id": "unsafe-observation", "principal": "local"},
            VisibleTerminalInput.model_validate(args),
            running,
        )
    if failure == "ambiguous":
        assert error.value.code == "visible_target_ambiguous"
    assert state["catalogs"] == 1
    assert not state["reads"] and not state["identities"] and not state["posts"]
    running.assert_not_awaited()
