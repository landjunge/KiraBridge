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
        if state["catalogs"] == 1 and state.get("initially_missing"):
            return []
        result = copy.deepcopy(row)
        if state.get("revoke_after_catalog") == state["catalogs"]:
            policy.capabilities.remove("session.inspect")
        if state["catalogs"] == 2 and state.get("final_busy"):
            result["busy"] = True
        if state["catalogs"] == 2 and state.get("final_process_change"):
            result["processes"].append(
                {"pid": 346, "ppid": 345, "name": "vim", "image": "/usr/bin/vim"}
            )
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


async def test_visible_command_keeps_final_selection_screens_and_no_replay(command):
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
    assert state["catalogs"] == 3
    assert state["catalogs_at_dispatch"] == 2
    assert state["reads_at_dispatch"] == 2
    assert state["reads"] == [1, 2, 3]
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
    assert state["catalogs"] == 2 and state["reads"] == [1]
    assert not state["identities"] and not state["posts"]
    running.assert_not_awaited()


@pytest.mark.parametrize("change", ["final_process_change", "revoke_after_catalog"])
async def test_visible_command_revalidates_process_and_authority_before_dispatch(command, change):
    bridge, state, args = command
    state[change] = 2 if change == "revoke_after_catalog" else True
    running = AsyncMock()
    with pytest.raises(BridgeError):
        await bridge.visible_terminal.execute(
            {"id": "final-revalidation", "principal": "local"},
            VisibleTerminalInput.model_validate(args),
            running,
        )
    assert state["catalogs"] == 2 and state["reads"] == [1]
    assert not state["identities"] and not state["posts"]
    running.assert_not_awaited()


@pytest.mark.parametrize("target", ["legacy", "created"])
async def test_visible_command_retains_canonical_row_for_legacy_and_created_shell(command, target):
    bridge, state, args = command
    if target == "legacy":
        state["row"]["legacy_expected_pid"] = 344
        args["expected_pid"] = 344
    else:
        state["initially_missing"] = True
        args.pop("pane_id")
        args.pop("expected_pid")
        args["create_if_needed"] = True
        bridge.sessions.open = AsyncMock(
            return_value={
                "pane_id": state["row"]["pane_id"],
                "expected_pid": 345,
                "tty": state["row"]["tty"],
            }
        )
    result = await bridge.visible_terminal.execute(
        {"id": "canonical-row", "principal": "local"},
        VisibleTerminalInput.model_validate(args),
        AsyncMock(),
    )
    assert result["expected_pid"] == 345 and result["exit_code"] == 0
    assert state["identities"] == [345] and len(state["posts"]) == 1
    if target == "created":
        bridge.sessions.open.assert_awaited_once()


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


@pytest.mark.parametrize("prompt", ["host project%   ", "➜  ~     ", "host project% typed"])
async def test_idle_shell_unconfirmed_input_is_not_reported_as_process_busy(command, prompt):
    bridge, state, args = command

    async def unconfirmed(pane):
        assert pane == state["row"]["pane_id"]
        return prompt

    bridge.sessions.terminal_app.read = unconfirmed
    running = AsyncMock()
    with pytest.raises(BridgeError) as failure:
        await bridge.visible_terminal.execute(
            {"id": "input-unknown", "principal": "local"},
            VisibleTerminalInput.model_validate(args),
            running,
        )
    assert failure.value.code == "visible_input_unknown"
    assert not state["row"]["busy"] and not state["posts"]
    running.assert_not_awaited()


async def test_unknown_input_without_safe_shell_does_not_open_replacement_window(command):
    bridge, state, args = command
    bridge.sessions.terminal_app.read = AsyncMock(return_value="host project%    ")
    bridge.sessions.open = AsyncMock(side_effect=AssertionError("must preserve ambiguous input"))
    args.pop("pane_id")
    args.pop("expected_pid")
    args["create_if_needed"] = True
    with pytest.raises(BridgeError) as failure:
        await bridge.visible_terminal.execute(
            {"id": "no-window-loop", "principal": "local"},
            VisibleTerminalInput.model_validate(args),
            AsyncMock(),
        )
    assert failure.value.code == "visible_input_unknown"
    assert not state["posts"]
    bridge.sessions.open.assert_not_awaited()


async def test_auto_selection_uses_existing_safe_shell_beside_unknown_input(command):
    bridge, state, args = command
    leaf = bridge.sessions.terminal_app
    safe = state["row"]
    unknown = copy.deepcopy(safe)
    unknown.update(pane_id="terminal:122:ttys003", tty="/dev/ttys003", expected_pid=344)
    unknown["processes"] = [{"pid": 344, "ppid": 343, "name": "zsh", "image": "/bin/zsh"}]

    async def catalog():
        state["catalogs"] += 1
        return [copy.deepcopy(unknown), copy.deepcopy(safe)]

    async def read(pane):
        state["reads"].append(state["catalogs"])
        return "host project%    " if pane == unknown["pane_id"] else "host project% "

    leaf.catalog, leaf.read = catalog, read
    bridge.sessions.open = AsyncMock(side_effect=AssertionError("existing safe shell is available"))
    args.pop("pane_id")
    args.pop("expected_pid")
    args["create_if_needed"] = True
    result = await bridge.visible_terminal.execute(
        {"id": "safe-existing-shell", "principal": "local"},
        VisibleTerminalInput.model_validate(args),
        AsyncMock(),
    )
    assert result["pane_id"] == safe["pane_id"] and result["exit_code"] == 0
    assert len(state["posts"]) == 1
    bridge.sessions.open.assert_not_awaited()


async def test_dirty_git_prompt_is_confirmed_as_empty_without_posting_input(command):
    bridge, state, _ = command
    bridge.sessions.terminal_app.read = AsyncMock(
        return_value=(
            "Last login: Thursday\n➜  KiraBridge git:(fix/visible-busy-idle-20261021) ✗ \n\n"
        )
    )
    assert await bridge.visible_terminal.suitable("local", state["row"])
    assert not state["posts"]
