import copy
import os

import pytest
from conftest import request

from kirabridge.bridge_core.models import BridgeError
from kirabridge.session_manager import SessionOpen, SessionReference
from kirabridge.session_resolution import resolve
from kirabridge.window_lifecycle import OwnedWindows


@pytest.fixture
def window(bridge, config, monkeypatch):
    row = {
        "pane_id": "terminal:900:ttys099",
        "expected_pid": 111,
        "tty": "/dev/ttys099",
        "transport": "terminal_app",
        "busy": False,
        "processes": [{"pid": 111, "name": "zsh"}],
    }
    state = {
        "row": row,
        "text": "KiraBridge visible % ",
        "identity": f"{os.getuid()} ttys099 start-A",
        "closed": [],
        "opened": [],
        "exists": True,
    }

    async def selected(*args):
        if not state["exists"]:
            raise BridgeError("session_selection_changed", "Gone")
        return copy.deepcopy(state["row"])

    async def read(*args):
        return {"text": state["text"]}

    async def identity(*args):
        return state["identity"]

    async def close(row, identity):
        state["closed"].append(row["pane_id"])
        state["exists"] = False
        return {"closed": True}

    async def catalog(*args):
        return {
            "status": "available",
            "sessions": [copy.deepcopy(state["row"])] if state["exists"] else [],
        }

    async def opened(command):
        state["opened"].append(command)
        raise AssertionError("Unnecessary window")

    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    monkeypatch.setattr(bridge.sessions, "selected", selected)
    monkeypatch.setattr(bridge.sessions, "read", read)
    monkeypatch.setattr(bridge.sessions.terminal_app, "process_identity", identity)
    monkeypatch.setattr(bridge.sessions.terminal_app, "close_idle", close)
    monkeypatch.setattr(bridge.sessions.terminal_app, "open", opened)
    bridge.prepare(
        "local",
        request(arguments={"path": config.principals["local"].roots[0]}, task_id="window-owner"),
    )
    return bridge, state


async def test_only_created_owned_idle_window_is_closed_after_task_and_restart(window):
    bridge, state = window
    await bridge.owned_windows.cleanup()
    assert not state["closed"]  # An ordinary user window is never adopted.
    await bridge.owned_windows.register("local", "window-owner", state["row"])
    await bridge.owned_windows.cleanup()
    assert not state["closed"]  # Owner task still waiting for approval.
    bridge.store.db.execute("UPDATE tasks SET state='completed' WHERE id='window-owner'")
    restarted = OwnedWindows(bridge.store, bridge.sessions)
    await restarted.cleanup()
    await restarted.cleanup()
    assert state["closed"] == [state["row"]["pane_id"]]


async def test_active_reuse_lease_preserves_window_of_finished_original_owner(window, config):
    bridge, state = window
    await bridge.owned_windows.register("local", "window-owner", state["row"])
    bridge.store.db.execute("UPDATE tasks SET state='completed' WHERE id='window-owner'")
    bridge.prepare(
        "local", request(arguments={"path": config.principals["local"].roots[0]}, task_id="later")
    )
    bridge.owned_windows.reserve("later", state["row"]["pane_id"])
    await bridge.owned_windows.cleanup()
    assert not state["closed"]
    bridge.store.db.execute("UPDATE tasks SET state='completed' WHERE id='later'")
    await bridge.owned_windows.cleanup()
    assert state["closed"] == [state["row"]["pane_id"]]


async def test_conflicting_window_identity_is_never_silently_adopted(window):
    bridge, state = window
    await bridge.owned_windows.register("local", "window-owner", state["row"])
    state["identity"] += " replacement"
    with pytest.raises(BridgeError) as conflict:
        await bridge.owned_windows.register("local", "new-owner", state["row"])
    assert conflict.value.code == "window_ownership_conflict"
    saved = bridge.store.db.execute(
        "SELECT task_id,identity FROM owned_terminal_windows"
    ).fetchone()
    assert saved["task_id"] == "window-owner" and saved["identity"] != state["identity"]
    assert not state["closed"]


@pytest.mark.parametrize(
    "change", ["git", "codex", "zsh", "busy", "input", "identity", "missing_receipt"]
)
async def test_cleanup_preserves_active_changed_and_uncertain_windows(window, tmp_path, change):
    bridge, state = window
    await bridge.owned_windows.register("local", "window-owner", state["row"])
    bridge.store.db.execute("UPDATE tasks SET state='completed' WHERE id='window-owner'")
    if change in {"git", "codex", "zsh"}:
        state["row"]["processes"].append({"pid": 222, "name": change})
    elif change == "busy":
        state["row"]["busy"] = True
    elif change == "input":
        state["text"] += "unfinished command"
    elif change == "identity":
        state["identity"] += " changed"
    else:
        bridge.owned_windows.command(
            state["row"]["pane_id"], "window-owner", tmp_path / "missing", "nonce"
        )
    await bridge.owned_windows.cleanup()
    assert not state["closed"]


async def test_uncertain_close_is_not_repeated_after_restart_and_blocks_creation(
    window, monkeypatch
):
    bridge, state = window
    await bridge.owned_windows.register("local", "window-owner", state["row"])
    bridge.store.db.execute("UPDATE tasks SET state='completed' WHERE id='window-owner'")
    attempts = []

    async def uncertain(*args):
        attempts.append(True)
        raise BridgeError("session_transport_unavailable", "Native result unknown")

    monkeypatch.setattr(bridge.sessions.terminal_app, "close_idle", uncertain)
    await bridge.owned_windows.cleanup()
    restarted = OwnedWindows(bridge.store, bridge.sessions)
    await restarted.cleanup()
    assert len(attempts) == 1 and restarted.creation_blocked()
    assert restarted.is_reserved(state["row"]["pane_id"])
    assert not state["closed"]


async def test_reused_shell_receives_initial_argv_exactly_once(window, config, monkeypatch):
    import shlex

    bridge, state = window
    config.principals["local"].executables.append("/usr/bin/printf")
    monkeypatch.setattr(bridge.security, "validate_window", lambda *args: None)
    commands = []

    async def send(row, command, identity):
        commands.append(command)
        return {"sent": True}

    monkeypatch.setattr(bridge.sessions.terminal_app, "send_confirmed", send)
    argv = ["/usr/bin/printf", "%s", "literal $(never execute) value"]
    result = await bridge.sessions.open(
        "local",
        SessionOpen(cwd=config.principals["local"].roots[0], argv=argv),
        task_id="reuse-one-command",
    )
    assert result["reused"] and len(commands) == 1
    assert commands[0].count(shlex.join(argv)) == 1
    assert not state["opened"]


async def test_repeated_open_requests_reuse_same_exact_free_shell(window, config, monkeypatch):
    bridge, state = window

    async def catalog(principal):
        return {"sessions": [copy.deepcopy(state["row"])]}

    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    monkeypatch.setattr(bridge.security, "validate_window", lambda *args: None)
    for _ in range(3):
        result = await bridge.sessions.open(
            "local",
            SessionOpen(cwd=config.principals["local"].roots[0], controlled_shell=True),
            task_id=f"window-reuse-{_}",
        )
        assert result["reused"] is True and result["opened"] is False
    assert not state["opened"]


async def test_stale_agent_binding_refresh_is_unique_and_explicit_when_ambiguous(
    bridge, config, monkeypatch
):
    from kirabridge.bridge_core.config import AgentConfig, VisibleTerminalBinding

    config.agents["codex"] = AgentConfig(kind="codex")
    config.visible_handoffs.bindings["codex"] = VisibleTerminalBinding(
        pane_id="terminal:1:ttys001", expected_pid=10, agent_pid=11, ready_pattern="ready"
    )
    rows = [
        {
            "pane_id": "terminal:2:ttys002",
            "expected_pid": 20,
            "transport": "terminal_app",
            "processes": [{"pid": 21, "name": "codex"}],
        }
    ]

    async def catalog(principal):
        return {"sessions": bridge.sessions.describe(copy.deepcopy(rows))}

    async def selected(principal, pane, pid):
        found = [row for row in rows if row["pane_id"] == pane and row["expected_pid"] == pid]
        if not found:
            raise BridgeError("session_selection_changed", "Stale")
        return copy.deepcopy(found[0])

    monkeypatch.setattr(bridge.sessions, "selected", selected)
    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    binding = await resolve(bridge.sessions, config.visible_handoffs.bindings, "local", "codex")
    assert binding.expected_pid == 20 and binding.agent_pid == 21
    assert config.visible_handoffs.bindings["codex"].expected_pid == 10
    rows.append(
        {
            "pane_id": "terminal:3:ttys003",
            "expected_pid": 30,
            "transport": "terminal_app",
            "processes": [{"pid": 31, "name": "codex"}],
        }
    )
    with pytest.raises(BridgeError, match="Select an exact"):
        await resolve(bridge.sessions, config.visible_handoffs.bindings, "local", "codex")
    selected_binding = await resolve(
        bridge.sessions,
        config.visible_handoffs.bindings,
        "local",
        "codex",
        SessionReference(pane_id="terminal:3:ttys003", expected_pid=30),
    )
    assert selected_binding.agent_pid == 31
