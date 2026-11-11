"""A newly returned TTY is not authority to choose an arbitrary native view."""

import asyncio
import sys
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from kirabridge.bridge_core.models import BridgeError
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
