"""Exact session selection cannot depend on another transport's health."""

import asyncio
import sys
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_native_send_identity import wire_submit

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport
from kirabridge.platform_adapters.tmux import TmuxTransport
from kirabridge.session_manager import SessionInput, SessionManager


def native_row(**updates):
    return {
        "pane_id": "terminal:123:ttys004",
        "expected_pid": 345,
        "tty": "/dev/ttys004",
        "window_id": 123,
        "transport": "terminal_app",
        "busy": False,
        "processes": [{"pid": 345, "ppid": 1, "name": "zsh", "image": "/bin/zsh"}],
        **updates,
    }


def manager_with_transports(bridge, config, rows, *, incomplete=False):
    config.principals["local"].capabilities += ["session.inspect", "session.input"]
    native = SimpleNamespace(
        available=True,
        desktop=object(),
        last_catalog_incomplete=incomplete,
        catalog=AsyncMock(return_value=deepcopy(rows)),
        send=AsyncMock(),
        insert=AsyncMock(),
        press_return=AsyncMock(),
    )
    tmux = SimpleNamespace(
        catalog=AsyncMock(side_effect=TimeoutError("unrelated tmux observation")),
        send=AsyncMock(),
        insert=AsyncMock(),
        press_return=AsyncMock(),
        last_catalog_truncated=False,
    )
    manager = SessionManager(bridge.sessions.ports, terminal_app=native, tmux=tmux)
    wire_submit(bridge, manager)
    return manager


async def test_exact_native_selection_never_observes_unrelated_timed_out_tmux(bridge, config):
    row = native_row()
    manager = manager_with_transports(bridge, config, [row])

    selected = await manager.selected("local", row["pane_id"], row["expected_pid"])
    assert {key: selected[key] for key in row} == row
    manager.terminal_app.catalog.assert_awaited_once_with()
    manager.tmux.catalog.assert_not_awaited()
    manager.terminal_app.send.assert_not_awaited()
    manager.terminal_app.press_return.assert_not_awaited()


@pytest.mark.parametrize(
    "rows,pid,code",
    [
        ([native_row()], 346, "session_selection_changed"),
        ([], 345, "session_selection_changed"),
        ([native_row(identity_ambiguous=True)], 345, "visible_target_ambiguous"),
        ([native_row(), native_row()], 345, "session_selection_changed"),
    ],
)
async def test_exact_native_isolation_preserves_target_guards(bridge, config, rows, pid, code):
    manager = manager_with_transports(bridge, config, rows)

    with pytest.raises(BridgeError) as error:
        await manager.selected("local", "terminal:123:ttys004", pid)

    assert error.value.code == code
    manager.tmux.catalog.assert_not_awaited()
    manager.terminal_app.send.assert_not_awaited()
    manager.terminal_app.press_return.assert_not_awaited()


async def test_native_busy_refusal_survives_tmux_isolation(bridge, config):
    row = native_row(busy=True)
    manager = manager_with_transports(bridge, config, [row])

    with pytest.raises(BridgeError) as error:
        await manager.send(
            "local",
            SessionInput(pane_id=row["pane_id"], expected_pid=345, text="safe", require_idle=True),
        )

    assert error.value.code == "session_busy"
    manager.tmux.catalog.assert_not_awaited()
    manager.terminal_app.send.assert_not_awaited()
    manager.terminal_app.insert.assert_not_awaited()
    manager.terminal_app.press_return.assert_not_awaited()


async def test_native_selection_does_not_inherit_unrelated_tmux_truncation(bridge, config):
    manager = manager_with_transports(bridge, config, [native_row()])
    manager.tmux.last_catalog_truncated = True
    result = await manager.catalog("local", transport="terminal_app")
    assert result["truncated"] is False
    manager.tmux.catalog.assert_not_awaited()


async def test_native_catalog_keeps_its_incomplete_observation(bridge, config):
    manager = manager_with_transports(bridge, config, [], incomplete=True)
    result = await manager.catalog("local", transport="terminal_app")
    assert result["truncated"] is True
    assert result["sessions"] == []
    with pytest.raises(BridgeError) as error:
        await manager.selected("local", "terminal:123:ttys004", 345)
    assert error.value.code == "session_selection_changed"
    manager.tmux.catalog.assert_not_awaited()


async def test_exact_tmux_selection_does_not_query_unrelated_native_failure(bridge, config):
    manager = manager_with_transports(bridge, config, [])
    manager.terminal_app.catalog.side_effect = AssertionError("native path must not be queried")
    manager.tmux.catalog.side_effect = None
    manager.tmux.catalog.return_value = [{"pane_id": "%7", "expected_pid": 456}]
    result = await manager.selected("local", "%7", 456)
    assert result["pane_id"] == "%7" and result["expected_pid"] == 456
    manager.terminal_app.catalog.assert_not_awaited()
    manager.tmux.catalog.assert_awaited_once_with()


async def test_native_selection_surfaces_its_own_timeout_without_fallback(bridge, config):
    manager = manager_with_transports(bridge, config, [])
    timeout = BridgeError("session_observation_timeout", "native read expired")
    timeout.provider_error = {"phase": "native_process_catalog", "reason": "timeout"}
    manager.terminal_app.catalog.side_effect = timeout
    manager.tmux.catalog.side_effect = None
    manager.tmux.catalog.return_value = [native_row()]
    with pytest.raises(BridgeError) as error:
        await manager.selected("local", "terminal:123:ttys004", 345)
    assert error.value.code == timeout.code
    assert error.value.provider_error == timeout.provider_error
    assert str(error.value) == str(timeout)
    manager.tmux.catalog.assert_not_awaited()


async def test_combined_discovery_retains_native_rows_and_typed_tmux_error(bridge, config):
    manager = manager_with_transports(bridge, config, [native_row()])
    timeout = BridgeError("session_observation_timeout", "tmux read expired")
    timeout.provider_error = {"phase": "tmux_read", "reason": "timeout"}
    manager.tmux.catalog.side_effect = timeout
    result = await manager.catalog("local")
    assert result["status"] == "available"
    assert [row["pane_id"] for row in result["sessions"]] == ["terminal:123:ttys004"]
    assert result["transport_errors"]["tmux"]["code"] == "session_observation_timeout"
    manager.terminal_app.catalog.assert_awaited_once_with()
    manager.tmux.catalog.assert_awaited_once_with()


async def test_selection_permission_refusal_never_queries_either_transport(bridge, config):
    manager = manager_with_transports(bridge, config, [native_row()])
    config.principals["local"].capabilities = []
    with pytest.raises(BridgeError):
        await manager.selected("local", "terminal:123:ttys004", 345)
    manager.terminal_app.catalog.assert_not_awaited()
    manager.tmux.catalog.assert_not_awaited()


@pytest.mark.parametrize("phase", ["catalog", "identity", "shell_snapshot"])
async def test_native_ps_timeout_is_typed_and_reaps_once_without_input(monkeypatch, phase):
    import kirabridge.platform_adapters.terminal_app as module

    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="darwin", exc_info=sys.exc_info))
    process = SimpleNamespace(communicate=AsyncMock(side_effect=TimeoutError()), returncode=None)
    if phase == "catalog":
        process.stdout = SimpleNamespace(read=AsyncMock(side_effect=TimeoutError()))
    spawn = AsyncMock(return_value=process)
    reap = AsyncMock()
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(module, "reap_process", reap)
    transport = TerminalAppTransport(asyncio.Lock())
    transport.native = AsyncMock(return_value=[])
    transport.insert = AsyncMock()
    transport.press_return = AsyncMock()
    transport.send_confirmed = AsyncMock()

    with pytest.raises(BridgeError) as error:
        if phase == "catalog":
            await transport.catalog()
        elif phase == "identity":
            await transport.process_identity(345, detailed=True)
        else:
            await transport.shell_process_snapshot("/dev/ttys004")

    assert error.value.code == "session_observation_timeout"
    assert error.value.provider_error == {
        "phase": {
            "catalog": "native_process_catalog",
            "identity": "native_process_identity",
            "shell_snapshot": "native_shell_snapshot",
        }[phase],
        "reason": "timeout",
    }
    spawn.assert_awaited_once()
    reap.assert_awaited_once_with(process, process_group=False)
    transport.insert.assert_not_awaited()
    transport.press_return.assert_not_awaited()
    transport.send_confirmed.assert_not_awaited()


@pytest.mark.parametrize("phase", ["catalog", "identity", "shell_snapshot"])
async def test_native_ps_cancellation_propagates_without_retry(monkeypatch, phase):
    import kirabridge.platform_adapters.terminal_app as module

    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="darwin", exc_info=sys.exc_info))
    process = SimpleNamespace(
        communicate=AsyncMock(side_effect=asyncio.CancelledError()), returncode=None
    )
    if phase == "catalog":
        process.stdout = SimpleNamespace(read=AsyncMock(side_effect=asyncio.CancelledError()))
    spawn, reap = AsyncMock(return_value=process), AsyncMock()
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(module, "reap_process", reap)
    transport = TerminalAppTransport(asyncio.Lock())
    transport.native = AsyncMock(return_value=[])
    with pytest.raises(asyncio.CancelledError):
        if phase == "catalog":
            await transport.catalog()
        elif phase == "identity":
            await transport.process_identity(345)
        else:
            await transport.shell_process_snapshot("/dev/ttys004")
    spawn.assert_awaited_once()
    reap.assert_awaited_once_with(process, process_group=False)


async def test_identity_read_timeout_prevents_all_input_and_return(bridge, config, monkeypatch):
    import kirabridge.platform_adapters.terminal_app as module

    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="darwin", exc_info=sys.exc_info))
    process = SimpleNamespace(communicate=AsyncMock(side_effect=TimeoutError()), returncode=None)
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    monkeypatch.setattr(module, "reap_process", AsyncMock())
    manager = manager_with_transports(bridge, config, [native_row()])
    transport = TerminalAppTransport(asyncio.Lock())
    manager.terminal_app.process_identity = transport.process_identity
    manager.terminal_app.send_confirmed = AsyncMock()
    monkeypatch.setattr(manager, "direct", lambda principal: True)
    before = AsyncMock()
    with pytest.raises(BridgeError) as error:
        await manager.send(
            "local",
            SessionInput(pane_id="terminal:123:ttys004", expected_pid=345, text="safe"),
            before_transport=before,
        )
    assert error.value.code == "session_observation_timeout"
    before.assert_not_awaited()
    manager.terminal_app.send_confirmed.assert_not_awaited()
    manager.terminal_app.insert.assert_not_awaited()
    manager.terminal_app.press_return.assert_not_awaited()


@pytest.mark.parametrize("mutation", [False, True])
async def test_tmux_timeout_preserves_read_vs_possible_mutation_outcome(monkeypatch, mutation):
    import kirabridge.platform_adapters.tmux as module

    process = SimpleNamespace(
        stdout=SimpleNamespace(read=AsyncMock(side_effect=TimeoutError("private details"))),
        returncode=None,
    )
    spawn, reap = AsyncMock(return_value=process), AsyncMock()
    monkeypatch.setattr(module.shutil, "which", lambda *args, **kwargs: "/isolated/fake/tmux")
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(module, "reap_process", reap)
    transport = TmuxTransport({"PATH": "/isolated/fake"})

    with pytest.raises(BridgeError) as error:
        await transport.command("list-panes" if not mutation else "send-keys", mutation=mutation)

    if mutation:
        assert isinstance(error.value, UncertainExecution)
        assert error.value.code == "session_input_unknown"
        assert getattr(error.value, "provider_error", None) is None
    else:
        assert not isinstance(error.value, UncertainExecution)
        assert error.value.code == "session_observation_timeout"
        assert error.value.provider_error == {"phase": "tmux_read", "reason": "timeout"}
    assert "private details" not in str(error.value)
    spawn.assert_awaited_once()
    process.stdout.read.assert_awaited_once()
    reap.assert_awaited_once_with(process, process_group=False)


@pytest.mark.parametrize("mutation", [False, True])
async def test_tmux_cancelled_observation_or_input_is_never_retried(monkeypatch, mutation):
    import kirabridge.platform_adapters.tmux as module

    process = SimpleNamespace(
        stdout=SimpleNamespace(read=AsyncMock(side_effect=asyncio.CancelledError())),
        returncode=None,
    )
    spawn, reap = AsyncMock(return_value=process), AsyncMock()
    monkeypatch.setattr(module.shutil, "which", lambda *args, **kwargs: "/isolated/fake/tmux")
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(module, "reap_process", reap)

    with pytest.raises(asyncio.CancelledError):
        await TmuxTransport({"PATH": "/isolated/fake"}).command("capture-pane", mutation=mutation)
    spawn.assert_awaited_once()
    reap.assert_awaited_once_with(process, process_group=False)
