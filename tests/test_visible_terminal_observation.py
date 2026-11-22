"""Reuse each selected row for its screen read, never for a later dispatch."""

import copy
import json
import re
import shlex
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import request

from kirabridge.bridge_core.models import BridgeError
from kirabridge.private_files import write_private
from kirabridge.visible_terminal import VisibleTerminalInput

# The generated command script is a zsh script; without zsh the receipt tests
# cannot run (Ubuntu CI images ship no zsh).
ZSH = shutil.which("zsh")


@pytest.fixture
def command(bridge, config, monkeypatch):
    monkeypatch.setattr(
        "kirabridge.visible_terminal.current_platform", lambda: SimpleNamespace(name="macos")
    )
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
    # Actual SessionManager.selected/read/catalog methods ran throughout. The screen is read
    # once before dispatch (the native dispatch confirms the empty prompt itself) and once
    # after, reusing the row observed at dispatch: two catalogues, two reads.
    assert state["catalogs"] == 2
    assert state["catalogs_at_dispatch"] == 2
    assert state["reads_at_dispatch"] == 1
    assert state["reads"] == [1, 2]
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


async def test_unknown_input_creates_separate_controlled_shell_when_requested(command, monkeypatch):
    bridge, state, args = command
    transport = bridge.sessions.terminal_app
    existing = copy.deepcopy(state["row"])
    created = copy.deepcopy(existing)
    created.update(
        pane_id="terminal:124:ttys005",
        expected_pid=346,
        tty="/dev/ttys005",
        processes=[{"pid": 346, "ppid": 343, "name": "zsh", "image": "/bin/zsh"}],
    )
    async def catalog():
        rows = [existing, created] if bridge.sessions.open.await_count else [existing]
        return copy.deepcopy(rows)

    async def read(pane):
        return "host project%    " if pane == existing["pane_id"] else "KiraBridge visible % "

    async def identity(pid):
        assert pid == created["expected_pid"]
        return "501 ttys005 Wed Nov 4 12:00:00 2026"

    async def send(selected, text, observed_identity):
        assert selected["pane_id"] == created["pane_id"]
        assert observed_identity.startswith("501 ttys005 ")
        state["posts"].append((selected["pane_id"], text))
        script = Path(shlex.split(text)[-1])
        nonce = re.search(r'"nonce": "([a-f0-9]+)"', script.read_text())[1]
        write_private(script.parent / "result.json", json.dumps({"nonce": nonce, "exit_code": 0}))

    monkeypatch.setattr(transport, "catalog", catalog)
    monkeypatch.setattr(transport, "read", read)
    monkeypatch.setattr(transport, "process_identity", identity)
    monkeypatch.setattr(transport, "send_confirmed", send)
    bridge.sessions.open = AsyncMock(
        return_value={
            "pane_id": created["pane_id"],
            "expected_pid": created["expected_pid"],
            "tty": created["tty"],
        }
    )
    args.pop("pane_id")
    args.pop("expected_pid")
    args["create_if_needed"] = True
    result = await bridge.visible_terminal.execute(
        {"id": "separate-controlled-shell", "principal": "local"},
        VisibleTerminalInput.model_validate(args),
        AsyncMock(),
    )
    bridge.sessions.open.assert_awaited_once()
    opened_args = bridge.sessions.open.await_args
    assert opened_args.args[1].controlled_shell is True
    assert result["pane_id"] == created["pane_id"] and result["success"]
    assert result["terminal_target"] == {
        "route": "new_controlled_visible_shell",
        "preserved_existing_input_issue": "visible_input_unknown",
    }
    assert [pane for pane, _text in state["posts"]] == [created["pane_id"]]
    state["posts"].clear()
    reused = await bridge.visible_terminal.execute(
        {"id": "reuse-controlled-shell", "principal": "local"},
        VisibleTerminalInput.model_validate(args),
        AsyncMock(),
    )
    assert reused["pane_id"] == created["pane_id"] and reused["success"]
    assert reused["terminal_target"]["route"] == "existing_visible_shell"
    assert [pane for pane, _text in state["posts"]] == [created["pane_id"]]
    bridge.sessions.open.assert_awaited_once()


async def test_unknown_input_create_if_needed_false_does_not_open(command):
    bridge, state, args = command
    bridge.sessions.terminal_app.read = AsyncMock(return_value="host project%    ")
    bridge.sessions.open = AsyncMock(side_effect=AssertionError("creation is disabled"))
    args.pop("pane_id")
    args.pop("expected_pid")
    args["create_if_needed"] = False
    with pytest.raises(BridgeError) as failure:
        await bridge.visible_terminal.execute(
            {"id": "no-fallback", "principal": "local"},
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
    assert result["terminal_target"] == {
        "route": "existing_visible_shell",
        "preserved_existing_input_issue": "visible_input_unknown",
    }
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


async def test_checking_stops_at_the_first_suitable_window(command, monkeypatch):
    bridge, state, args = command
    transport = bridge.sessions.terminal_app
    rows = []
    for number in (9, 3, 7):
        item = copy.deepcopy(state["row"])
        item.update(pane_id=f"terminal:1{number}:ttys00{number}", tty=f"/dev/ttys00{number}")
        rows.append(item)
    reads, posts = [], []

    async def catalog():
        return copy.deepcopy(rows)

    async def read(pane):
        reads.append(pane)
        return "host project% "

    async def identity(pid):
        return "501 ttys003 Wed Nov 4 12:00:00 2026"

    async def send(selected, text, observed_identity):
        posts.append(selected["pane_id"])
        script = Path(shlex.split(text)[-1])
        nonce = re.search(r'"nonce": "([a-f0-9]+)"', script.read_text())[1]
        write_private(script.parent / "result.json", json.dumps({"nonce": nonce, "exit_code": 0}))

    for name, function in (
        ("catalog", catalog),
        ("read", read),
        ("process_identity", identity),
        ("send_confirmed", send),
    ):
        monkeypatch.setattr(transport, name, function)
    value = request(
        "terminal.visible",
        {**args, "pane_id": None, "expected_pid": None},
        task_id="first-suitable",
    )
    async with bridge:
        bridge.prepare("local", value)
        task = await bridge.tasks.wait("local", value.task_id, 5)
    assert task["state"] == "completed", task
    # The lowest pane id is used; the other two idle shells are never read before dispatch.
    assert posts == ["terminal:13:ttys003"]
    assert "terminal:19:ttys009" not in reads and "terminal:17:ttys007" not in reads


async def test_layout_change_of_other_windows_does_not_abort_the_dispatch(command):
    """ui_window_count changes when any other window opens; the target itself is unchanged."""
    bridge, state, args = command
    original = bridge.sessions.terminal_app.catalog
    calls = {"n": 0}

    async def catalog():
        calls["n"] += 1
        rows = await original()
        if calls["n"] >= 2:
            for row in rows:
                row["ui_window_count"] = 5
                row["tab_selected"] = True
        return rows

    bridge.sessions.terminal_app.catalog = catalog
    value = request("terminal.visible", args, task_id="layout-change")
    async with bridge:
        bridge.prepare("local", value)
        task = await bridge.tasks.wait("local", value.task_id, 5)
    assert task["state"] == "completed", task


async def test_unsuitable_window_reports_its_real_reason(command):
    bridge, state, args = command
    state["row"]["miniaturized"] = True
    running = AsyncMock()
    with pytest.raises(BridgeError) as failure:
        await bridge.visible_terminal.execute(
            {"id": "minimized", "principal": "local"},
            VisibleTerminalInput.model_validate(args),
            running,
        )
    assert failure.value.code == "visible_target_minimized"
    assert not state["posts"]
    running.assert_not_awaited()


async def test_a_vanishing_candidate_does_not_stop_the_choice_of_another(command, monkeypatch):
    bridge, state, args = command
    transport = bridge.sessions.terminal_app
    rows = []
    for number in (3, 5):
        item = copy.deepcopy(state["row"])
        item.update(pane_id=f"terminal:1{number}:ttys00{number}", tty=f"/dev/ttys00{number}")
        rows.append(item)
    posts = []

    async def catalog():
        return copy.deepcopy(rows)

    async def read(pane):
        if pane == "terminal:13:ttys003":
            raise BridgeError("session_selection_changed", "window closed meanwhile")
        return "host project% "

    async def identity(pid):
        return "501 ttys005 Wed Nov 4 12:00:00 2026"

    async def send(selected, text, observed_identity):
        posts.append(selected["pane_id"])
        script = Path(shlex.split(text)[-1])
        nonce = re.search(r'"nonce": "([a-f0-9]+)"', script.read_text())[1]
        write_private(script.parent / "result.json", json.dumps({"nonce": nonce, "exit_code": 0}))

    for name, function in (
        ("catalog", catalog),
        ("read", read),
        ("process_identity", identity),
        ("send_confirmed", send),
    ):
        monkeypatch.setattr(transport, name, function)
    value = request(
        "terminal.visible", {**args, "pane_id": None, "expected_pid": None}, task_id="skip"
    )
    async with bridge:
        bridge.prepare("local", value)
        task = await bridge.tasks.wait("local", value.task_id, 5)
    assert task["state"] == "completed", task
    assert posts == ["terminal:15:ttys005"]


def test_old_command_folders_are_pruned_and_nothing_else(tmp_path):
    import os
    import time

    from kirabridge.visible_terminal import prune_command_folders

    old, fresh = "a" * 32, "b" * 32
    for name in (old, fresh, "not-a-token", "c" * 31):
        (tmp_path / name).mkdir()
        (tmp_path / name / "command.zsh").write_text("x")
    age = time.time() - 5 * 86400
    for name in (old, "not-a-token", "c" * 31):
        os.utime(tmp_path / name, (age, age))
    assert prune_command_folders(tmp_path) == 1
    assert not (tmp_path / old).exists()
    assert (tmp_path / fresh).exists()
    assert (tmp_path / "not-a-token").exists() and (tmp_path / ("c" * 31)).exists()


async def test_the_command_folder_is_removed_once_the_receipt_is_read(command):
    bridge, state, args = command
    value = request("terminal.visible", args, task_id="folder-cleanup")
    async with bridge:
        bridge.prepare("local", value)
        task = await bridge.tasks.wait("local", value.task_id, 5)
    assert task["state"] == "completed", task
    root = bridge.config.state_path / "visible-commands"
    assert not [child for child in root.iterdir() if child.is_dir()]


def _run_script(tmp_path, *, tty_override=None, cwd=None, argv=None, interrupt_after=None):
    """Run the generated script with the real /bin/zsh on a pseudo-terminal."""
    import os
    import pty
    import signal
    import subprocess
    import time

    from kirabridge.visible_terminal import build_command_script

    master, slave = pty.openpty()
    tty = os.ttyname(slave)
    folder = tmp_path / "run"
    folder.mkdir()
    result = folder / "result.json"
    script = build_command_script(
        tty_override or tty,
        cwd or str(tmp_path),
        argv or ["/usr/bin/true"],
        "n0nce",
        folder,
        result,
    )
    path = folder / "command.zsh"
    path.write_text(script)
    process = subprocess.Popen(
        [ZSH, "-f", str(path)],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
    )
    if interrupt_after is not None:
        time.sleep(interrupt_after)
        # A terminal signals the whole foreground group (Ctrl-C, window closed).
        os.killpg(process.pid, signal.SIGTERM)
    process.wait(timeout=20)
    os.close(master)
    os.close(slave)
    return process.returncode, (json.loads(result.read_text()) if result.exists() else None)


needs_zsh = pytest.mark.skipif(ZSH is None, reason="the generated command script requires zsh")


@needs_zsh
def test_script_receipts_the_exit_code_atomically(tmp_path):
    code, receipt = _run_script(tmp_path, argv=["/bin/sh", "-c", "exit 3"])
    assert receipt == {"nonce": "n0nce", "exit_code": 3} and code == 0
    assert not list((tmp_path / "run").glob("result.tmp"))


@needs_zsh
def test_script_receipts_a_wrong_terminal_immediately(tmp_path):
    code, receipt = _run_script(tmp_path, tty_override="/dev/ttys999")
    assert code == 125
    assert receipt == {"nonce": "n0nce", "exit_code": 125, "phase": "setup"}


@needs_zsh
def test_script_receipts_an_unusable_directory_immediately(tmp_path):
    code, receipt = _run_script(tmp_path, cwd=str(tmp_path / "missing"))
    assert code == 125 and receipt["phase"] == "setup"


@needs_zsh
def test_script_receipts_an_interrupt(tmp_path):
    code, receipt = _run_script(tmp_path, argv=["/bin/sleep", "30"], interrupt_after=1.0)
    assert code == 130
    assert receipt == {"nonce": "n0nce", "exit_code": 130, "phase": "interrupted"}


@pytest.mark.parametrize(
    ("phase", "code"),
    [("setup", "visible_target_changed"), ("interrupted", "visible_command_interrupted")],
)
async def test_setup_and_interrupt_receipts_fail_at_once(command, monkeypatch, phase, code):
    bridge, state, args = command
    transport = bridge.sessions.terminal_app

    async def send(selected, text, observed_identity):
        script = Path(shlex.split(text)[-1])
        nonce = re.search(r'"nonce": "([a-f0-9]+)"', script.read_text())[1]
        receipt = {"nonce": nonce, "exit_code": 125 if phase == "setup" else 130, "phase": phase}
        write_private(script.parent / "result.json", json.dumps(receipt))

    monkeypatch.setattr(transport, "send_confirmed", send)
    started = __import__("time").monotonic()
    with pytest.raises(BridgeError) as failure:
        await bridge.visible_terminal.execute(
            {"id": f"receipt-{phase}", "principal": "local"},
            VisibleTerminalInput.model_validate({**args, "timeout": 30}),
            AsyncMock(),
        )
    assert failure.value.code == code
    assert __import__("time").monotonic() - started < 5  # no waiting for the timeout
