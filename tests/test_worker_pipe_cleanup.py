"""Exact owned worker pipes; no GUI, productive config, daemon or foreign PIDs."""

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.platform_adapters import reap_process
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport


async def test_pid_only_reaper_drains_cancelled_paused_pipe_even_after_exit(monkeypatch):
    def no_group_signal(*args):
        pytest.fail("Worker cleanup must never signal its parent's group")

    monkeypatch.setattr(os, "killpg", no_group_signal)
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-c",
        "import os,time;time.sleep(.05);os.write(1,b'x'*262144);time.sleep(60)",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL,
        limit=1024,
    )
    waiter = None
    try:
        assert os.getpgid(child.pid) == os.getpgrp()  # Deliberately NOT a private group.
        reader = asyncio.create_task(child.communicate())
        await asyncio.sleep(0.01)
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
        async with asyncio.timeout(2):
            while not child.stdout._paused:
                await asyncio.sleep(0.001)
        waiter = asyncio.create_task(child.wait())
        await asyncio.sleep(0)
        child.kill()  # Exactly our created handle.
        # Some asyncio versions release wait() as soon as the child exits,
        # others wait for the paused pipes too. Neither behavior consumes the
        # cancelled reader's buffered output: cleanup must still drain it.
        try:
            await asyncio.wait_for(asyncio.shield(waiter), 0.1)
        except TimeoutError:
            pass
        assert child.returncode is not None
        assert not child.stdout.at_eof()
        async with asyncio.timeout(2):
            await reap_process(child, process_group=False)
            await waiter
        assert child.stdout.at_eof() and child.stderr.at_eof()
    finally:
        await reap_process(child, process_group=False)
        if waiter is not None and not waiter.done():
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)


async def test_pid_only_reaper_preserves_repeated_cancellation_and_finishes_owned_cleanup(
    monkeypatch,
):
    entered, finish = asyncio.Event(), asyncio.Event()
    events = []

    async def wait():
        entered.set()
        await finish.wait()
        child.returncode = -9
        events.append("reaped")

    def kill():
        events.append("exact-child-kill")

    child = SimpleNamespace(
        returncode=None, stdin=None, stdout=None, stderr=None, kill=kill, wait=wait
    )
    monkeypatch.setattr(os, "killpg", lambda *args: pytest.fail("No group signal"))
    task = asyncio.create_task(reap_process(child, process_group=False))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["exact-child-kill", "reaped"]


async def test_pid_cleanup_deadline_closes_only_own_pipes_and_reports_bridge_error(monkeypatch):
    real_timeout = asyncio.timeout
    monkeypatch.setattr(asyncio, "timeout", lambda seconds: real_timeout(0.01))
    closed = []
    child = SimpleNamespace(
        returncode=-9,
        stdin=None,
        stdout=None,
        stderr=None,
        wait=lambda: asyncio.Event().wait(),
        _transport=SimpleNamespace(close=lambda: closed.append(True)),
    )
    with pytest.raises(BridgeError) as exc:
        await reap_process(child, process_group=False)
    assert not isinstance(exc.value, UncertainExecution)
    assert exc.value.code == "process_cleanup_unknown" and closed == [True]


@pytest.mark.parametrize("mutation", [False, True])
async def test_native_cleanup_failure_distinguishes_read_from_possible_input(monkeypatch, mutation):
    child = SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(b"{}", b"")))
    monkeypatch.setattr("kirabridge.platform_adapters.terminal_app.sys.platform", "darwin")
    monkeypatch.setattr(
        "kirabridge.platform_adapters.terminal_app.asyncio.create_subprocess_exec",
        AsyncMock(return_value=child),
    )
    cleanup = AsyncMock(side_effect=BridgeError("process_cleanup_unknown", "cleanup unavailable"))
    monkeypatch.setattr("kirabridge.platform_adapters.terminal_app.reap_process", cleanup)
    transport = TerminalAppTransport(
        asyncio.Lock(), desktop=SimpleNamespace(require_interactive=AsyncMock())
    )
    with pytest.raises(BridgeError) as exc:
        await transport.native("fake source", mutation=mutation)
    assert isinstance(exc.value, UncertainExecution) is mutation
    assert exc.value.code == (
        "session_input_unknown" if mutation else "session_transport_unavailable"
    )
    cleanup.assert_awaited_once_with(child, process_group=False)


async def test_original_cancellation_is_preserved_after_worker_cleanup(monkeypatch):
    child = SimpleNamespace(returncode=-9, stdin=None, stdout=None, stderr=None, wait=AsyncMock())

    async def cancelled_operation():
        try:
            raise asyncio.CancelledError
        finally:
            await reap_process(child, process_group=False)

    with pytest.raises(asyncio.CancelledError):
        await cancelled_operation()
    child.wait.assert_awaited_once()


async def test_caller_cancellation_wins_over_cleanup_timeout_without_claiming_reaped(monkeypatch):
    real_timeout = asyncio.timeout
    monkeypatch.setattr(asyncio, "timeout", lambda seconds: real_timeout(0.01))
    closed = []
    child = SimpleNamespace(
        returncode=-9,
        stdin=None,
        stdout=None,
        stderr=None,
        wait=lambda: asyncio.Event().wait(),
        _transport=SimpleNamespace(close=lambda: closed.append(True)),
    )

    async def cancelled_operation():
        try:
            raise asyncio.CancelledError
        finally:
            await reap_process(child, process_group=False)

    with pytest.raises(asyncio.CancelledError):
        await cancelled_operation()
    assert closed == [True]


@pytest.mark.parametrize("locked", [False, True])
async def test_desktop_cleanup_failure_preserves_known_lock_else_unknown(monkeypatch, locked):
    import plistlib

    from kirabridge.platform_adapters.desktop import MacDesktop

    monkeypatch.setattr(
        "kirabridge.platform_adapters.desktop.sys", SimpleNamespace(platform="darwin")
    )
    raw = plistlib.dumps(
        {
            "IOConsoleUsers": [
                {
                    "kCGSSessionUserIDKey": os.getuid(),
                    "kCGSSessionOnConsoleKey": True,
                    "CGSSessionScreenIsLocked": locked,
                }
            ]
        }
    )
    child = SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(raw, b"")))
    monkeypatch.setattr(
        "kirabridge.platform_adapters.desktop.asyncio.create_subprocess_exec",
        AsyncMock(return_value=child),
    )
    monkeypatch.setattr(
        "kirabridge.platform_adapters.desktop.reap_process",
        AsyncMock(side_effect=BridgeError("process_cleanup_unknown", "cleanup")),
    )
    result = await MacDesktop().probe()
    assert result["state"] == ("desktop_locked" if locked else "unknown")


async def test_unconfirmed_pid_observation_cleanup_never_proves_absence(monkeypatch):
    monkeypatch.setattr(TerminalAppTransport, "available", property(lambda self: True))
    child = SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(b"1\n", b"")))
    monkeypatch.setattr(
        "kirabridge.platform_adapters.terminal_app.asyncio.create_subprocess_exec",
        AsyncMock(return_value=child),
    )
    monkeypatch.setattr(
        "kirabridge.platform_adapters.terminal_app.reap_process",
        AsyncMock(side_effect=BridgeError("process_cleanup_unknown", "cleanup")),
    )
    with pytest.raises(BridgeError) as exc:
        await TerminalAppTransport(asyncio.Lock()).process_ids()
    assert exc.value.code == "visible_absence_unproven" and not isinstance(
        exc.value, UncertainExecution
    )
