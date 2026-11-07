"""Connection admission is bounded before catalog or tool dispatch."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.types import CallToolResult, Tool

from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.proxy import DaemonConnection


def connected_proxy():
    pool = MCPClientPool(call_timeout=0.03)
    session = SimpleNamespace(
        list_tools=AsyncMock(
            return_value=SimpleNamespace(
                tools=[Tool(name="write_once", inputSchema={})], nextCursor=None
            )
        ),
        call_tool=AsyncMock(return_value=CallToolResult(content=[])),
    )
    pool.sessions["daemon"] = session
    pool.connection_ids["daemon"] = "original"
    connection = DaemonConnection(pool, Peer("daemon", url="http://127.0.0.1:1/mcp"))
    return connection, session


@pytest.mark.parametrize("through_call", [False, True])
async def test_connection_lock_wait_uses_own_deadline_before_any_dispatch(through_call):
    connection, session = connected_proxy()
    await connection.lock.acquire()
    observer = asyncio.timeout(0.3)
    try:
        with pytest.raises(BridgeError) as error:
            async with observer:
                if through_call:
                    await connection.call_tool("write_once", {})
                else:
                    await connection.list_tools()
        assert not observer.expired(), "The connection step must enforce its own deadline"
        assert error.value.code == "peer_connection_timeout"
        diagnostic = error.value.diagnostic
        assert diagnostic["operation"] == "mcp.connect"
        assert diagnostic["connection_id"] == "original"
        assert diagnostic["tool_dispatch"] == "no"
        assert diagnostic["evidence_scope"] == "this_client_tool_dispatch"
        assert diagnostic["automatic_retry"] is False
        assert connection.lock.locked(), "An expired waiter must not release another owner's lock"
        session.list_tools.assert_not_awaited()
        session.call_tool.assert_not_awaited()
    finally:
        connection.lock.release()
    await asyncio.sleep(0)
    session.list_tools.assert_not_awaited()
    session.call_tool.assert_not_awaited()


async def test_connection_wait_cancellation_stays_cancellation_and_never_dispatches():
    connection, session = connected_proxy()
    await connection.lock.acquire()
    pending = asyncio.create_task(connection.call_tool("write_once", {}))
    try:
        await asyncio.sleep(0)  # The call is queued behind this exact owner.
        assert not pending.done()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert connection.lock.locked()
    finally:
        connection.lock.release()
        await asyncio.gather(pending, return_exceptions=True)
    await asyncio.sleep(0)
    session.list_tools.assert_not_awaited()
    session.call_tool.assert_not_awaited()


async def test_connection_step_timeout_cancels_one_connect_without_replay(monkeypatch):
    connection, session = connected_proxy()
    connection.pool.sessions.clear()
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def held_connect(endpoint):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    connect = AsyncMock(side_effect=held_connect)
    monkeypatch.setattr(connection.pool, "connect", connect)
    observer = asyncio.timeout(0.3)
    with pytest.raises(BridgeError) as error:
        async with observer:
            await connection.call_tool("write_once", {})
    assert not observer.expired() and entered.is_set() and cancelled.is_set()
    assert error.value.code == "peer_connection_timeout"
    assert error.value.diagnostic["tool_dispatch"] == "no"
    # A connection attempt is not proof of no control-plane activity.
    for field in ("accepted", "started", "completed"):
        assert error.value.diagnostic[field] == "unknown"
    connect.assert_awaited_once_with(connection.endpoint)
    assert not connection.lock.locked()
    await asyncio.sleep(0)
    connect.assert_awaited_once()
    session.list_tools.assert_not_awaited()
    session.call_tool.assert_not_awaited()
