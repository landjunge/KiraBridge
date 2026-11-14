"""A newly returned TTY is not authority to choose an arbitrary native view."""

import asyncio
import sys
import time
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.session_manager import SessionManager, SessionOpen
from kirabridge.session_ports import SessionPorts


def manager_for_open(tmp_path, rows):
    policy = SimpleNamespace(
        roots=[str(tmp_path)],
        terminal_roots=[str(tmp_path)],
        executables=[sys.executable],
        allow_any_executable=False,
    )
    authorization = SimpleNamespace(
        principal=Mock(return_value=policy),
        validate_window=Mock(),
        check_window=Mock(),
        window_outcome=Mock(),
    )
    native = SimpleNamespace(
        desktop=object(),
        open=AsyncMock(return_value={"tty": "/dev/ttys004", "opened": True}),
        catalog=AsyncMock(return_value=deepcopy(rows)),
        process_identity=AsyncMock(return_value="501 ttys004 Sun Nov 1 12:00:00 2026 344 /bin/zsh"),
        process_working_directory=AsyncMock(return_value=str(tmp_path)),
        verify_opened=AsyncMock(),
        send_confirmed=AsyncMock(),
    )
    ports = SessionPorts(
        authorization=authorization,
        input_release=None,
        audit=None,
        environment={"PATH": "/usr/bin:/bin"},
        agent_registry=lambda: ({}, {}),
        clipboard_lock=asyncio.Lock(),
        visible_required=lambda _: True,
    )
    manager = SessionManager(ports, terminal_app=native)
    from kirabridge.desktop_input import DesktopInput

    desktop = DesktopInput(manager.lock)

    def bind(principal, task_id, turn, **options):
        desktop.require_turn(turn)
        assert principal == "chatgpt" and task_id and options["opening"] is True
        options["origin_guard"]()
        return SimpleNamespace(owner={"task_id": task_id, "principal": principal})

    # Manager ordering/ambiguity fixture only; actual authority is tested with
    # persisted tasks and the real adapter in the separate authority tests.
    manager.native_input = SimpleNamespace(desktop_input=desktop, bind_stored=bind)
    manager.read = AsyncMock(return_value={"text": "KiraBridge visible % "})
    return manager, native, authorization


def row(window=123, pid=345, **extra):
    return {
        "pane_id": f"terminal:{window}:ttys004",
        "expected_pid": pid,
        "tty": "/dev/ttys004",
        "busy": False,
        **extra,
    }


@pytest.mark.parametrize(
    "rows",
    [
        [row(), row(window=124)],
        [row(identity_ambiguous=True)],
    ],
)
@pytest.mark.parametrize("with_command", [False, True])
async def test_new_window_cannot_adopt_ambiguous_tty_view(
    tmp_path, rows, with_command, native_session_platform
):
    manager, native, authorization = manager_for_open(tmp_path, rows)
    args = SessionOpen(cwd=str(tmp_path), argv=[sys.executable] if with_command else [])

    with pytest.raises(BridgeError) as error:
        await manager.open("chatgpt", args, task_id="new-window")

    assert error.value.code == "visible_target_ambiguous"
    native.open.assert_awaited_once()
    native.catalog.assert_awaited_once()
    native.send_confirmed.assert_not_awaited()
    native.process_identity.assert_not_awaited()
    manager.read.assert_not_awaited()
    authorization.window_outcome.assert_called_once_with("chatgpt", "new-window", "opened")


async def test_unique_new_window_keeps_exact_handle_and_command(tmp_path, native_session_platform):
    selected = row()
    manager, native, authorization = manager_for_open(tmp_path, [selected])
    args = SessionOpen(cwd=str(tmp_path), argv=[sys.executable])

    result = await manager.open("chatgpt", args, task_id="new-window")

    assert result["pane_id"] == selected["pane_id"]
    assert result["expected_pid"] == selected["expected_pid"]
    assert result["opened"] is True
    native.open.assert_awaited_once()
    native.send_confirmed.assert_awaited_once()
    assert native.send_confirmed.await_args.args[0] == selected
    authorization.window_outcome.assert_called_once_with("chatgpt", "new-window", "opened")


async def test_interactive_agent_start_reports_bound_process_lifecycle(
    tmp_path, native_session_platform
):
    shell = row()
    agent = {
        **shell,
        "processes": [{"pid": 901, "ppid": shell["expected_pid"], "name": "codex"}],
    }
    manager, native, _ = manager_for_open(tmp_path, [shell])
    native.catalog = AsyncMock(side_effect=[[shell], [agent]])
    native.read = AsyncMock(return_value={"text": "Codex composer"})
    profile = SimpleNamespace(executable=sys.executable)

    async def bind_started(*_):
        # Longer agent lifecycle observation is outside the completed desktop turn.
        assert not manager.lock.locked()
        return {"state": "bound"}

    binding = AsyncMock(side_effect=bind_started)
    manager.ports = replace(
        manager.ports,
        agent_registry=lambda: ({"codex": profile}, {}),
        agent_started=binding,
    )
    manager.agent_registry = manager.ports.agent_registry

    result = await manager.open(
        "chatgpt",
        SessionOpen(cwd=str(tmp_path), argv=[sys.executable]),
        task_id="codex-start",
    )

    assert result["lifecycle"] == {
        "window": "confirmed",
        "command": "submitted",
        "agent_process": "started",
        "agent_pid": 901,
        "binding": "bound",
        "input_readiness": "unknown",
    }
    binding.assert_awaited_once_with("chatgpt", "codex", {**agent, "agent_pid": 901})
    native.send_confirmed.assert_awaited_once()


async def test_started_agent_only_matches_the_launch_executable(tmp_path, native_session_platform):
    manager, _, _ = manager_for_open(tmp_path, [])
    profile = SimpleNamespace(executable=sys.executable)
    manager.ports = replace(
        manager.ports,
        agent_registry=lambda: ({"codex": profile}, {}),
    )
    manager.agent_registry = manager.ports.agent_registry

    # The executable as a data argument (not argv[0]) must never start a CLI.
    assert manager._started_agent(["/bin/cat", sys.executable]) is None
    assert manager._started_agent([]) is None
    # The actual launch position is argv[0].
    assert manager._started_agent([sys.executable, "--some-arg"]) == "codex"


async def test_started_process_cannot_be_adopted_after_tty_identity_changes(
    tmp_path, native_session_platform
):
    manager, native, _ = manager_for_open(tmp_path, [])
    replacement = {
        **row(window=124, pid=346),
        "processes": [{"pid": 901, "ppid": 346, "name": "codex"}],
    }
    native.catalog = AsyncMock(return_value=[replacement])

    with pytest.raises(BridgeError) as error:
        await manager._confirm_started_agent(
            "/dev/ttys004",
            "codex",
            "terminal:123:ttys004",
            345,
            set(),
            time.monotonic() + 1,
        )

    assert error.value.code == "visible_target_changed"


async def test_started_process_catalog_timeout_remains_unknown(tmp_path, native_session_platform):
    manager, native, _ = manager_for_open(tmp_path, [])
    native.catalog = AsyncMock(side_effect=asyncio.Event().wait)

    started, process = await manager._confirm_started_agent(
        "/dev/ttys004",
        "codex",
        "terminal:123:ttys004",
        345,
        set(),
        time.monotonic() + 0.01,
    )

    assert started is None and process is None


async def test_interactive_agent_start_unknown_process_is_not_replayed(
    tmp_path, native_session_platform
):
    shell = row()
    manager, native, _ = manager_for_open(tmp_path, [shell])
    native.catalog = AsyncMock(return_value=[shell])
    native.read = AsyncMock(return_value={"text": "KiraBridge visible % "})
    manager.ports = replace(
        manager.ports,
        agent_registry=lambda: ({"codex": SimpleNamespace(executable=sys.executable)}, {}),
    )
    manager.agent_registry = manager.ports.agent_registry
    binding = AsyncMock()
    manager.ports = replace(manager.ports, agent_started=binding)
    manager._confirm_started_agent = AsyncMock(return_value=(None, None))
    with pytest.raises(UncertainExecution) as error:
        await manager.open(
            "chatgpt",
            SessionOpen(cwd=str(tmp_path), argv=[sys.executable]),
            task_id="codex-start-unknown",
        )

    assert getattr(error.value, "code", None) == "session_open_pending"
    assert error.value.provider_error["start_evidence"]["command_submitted"] is True
    assert error.value.provider_error["start_evidence"]["automatic_retry"] is False
    native.send_confirmed.assert_awaited_once()
    binding.assert_not_awaited()
