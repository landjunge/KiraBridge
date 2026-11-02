"""Force desktop contention and effect-boundary failures without UI or processes."""

import asyncio

import pytest

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.desktop_input import DesktopInput


async def test_same_session_lock_serializes_a_whole_text_return_transaction():
    lock = asyncio.Lock()
    input = DesktopInput(lock)
    entered, release = asyncio.Event(), asyncio.Event()
    trace = []

    async def text():
        async with input.transaction() as turn:
            turn.mark_attempted()
            trace.append("text")
            entered.set()
            await release.wait()
            trace.append("return")

    async def existing_session():
        async with lock:
            trace.append("session")

    first = asyncio.create_task(text())
    await entered.wait()
    second = asyncio.create_task(existing_session())
    await asyncio.sleep(0)
    assert trace == ["text"] and not second.done()
    release.set()
    await asyncio.gather(first, second)
    assert trace == ["text", "return", "session"]


async def test_waiting_deadline_proves_no_effect_and_keeps_foreign_lock():
    lock = asyncio.Lock()
    input = DesktopInput(lock, timeout=0.01)
    entered = False
    async with lock:
        with pytest.raises(BridgeError) as error:
            async with input.transaction():
                entered = True
        assert error.value.code == "desktop_input_busy"
        assert type(error.value) is BridgeError and not entered and lock.locked()
    assert not lock.locked()


async def test_deadline_after_attempt_is_unknown_and_releases_lock():
    input = DesktopInput(asyncio.Lock(), timeout=0.01)
    with pytest.raises(UncertainExecution) as error:
        async with input.transaction() as turn:
            turn.mark_attempted()
            await asyncio.Event().wait()
    assert error.value.code == "desktop_input_unknown" and not input.lock.locked()


async def test_inner_timeout_is_preserved_and_cancellation_releases_own_lock():
    input = DesktopInput(asyncio.Lock())
    with pytest.raises(TimeoutError, match="own observation"):
        async with input.transaction():
            raise TimeoutError("own observation")
    assert not input.lock.locked()
    entered = asyncio.Event()

    async def waiting():
        async with input.transaction():
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(waiting())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not input.lock.locked()
