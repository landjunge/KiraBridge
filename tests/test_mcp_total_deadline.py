"""One client deadline covers catalog admission, queueing, and remote observation."""

import asyncio
from types import SimpleNamespace

import pytest
from mcp.shared.exceptions import McpError
from mcp.types import CONNECTION_CLOSED, CallToolResult, ErrorData, Tool
from test_mcp_connection_races import attach_connection

from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool


async def test_saturated_real_32_slot_gate_times_out_without_dispatch_or_replay():
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def held(name, arguments):
        calls.append(name)
        if len(calls) == 32:
            entered.set()
        await release.wait()
        return CallToolResult(content=[])

    pool = MCPClientPool(call_timeout=2)
    pool.sessions["peer"] = SimpleNamespace(call_tool=held)
    pool.connection_ids["peer"] = "original"
    busy = [asyncio.create_task(pool.call("peer", "held_read", {})) for _ in range(32)]
    await asyncio.wait_for(entered.wait(), 1)
    pool.call_timeout = 0.03  # Existing calls already own their original deadline.
    try:
        with pytest.raises(BridgeError) as error:
            await asyncio.wait_for(pool.call("peer", "write_once", {}), 0.3)
        assert error.value.code == "peer_timeout"
        assert error.value.diagnostic["accepted"] == "no"
        assert error.value.diagnostic["started"] == "no"
        assert error.value.diagnostic["completed"] == "no"
        assert error.value.diagnostic["connection_id"] == "original"
        assert error.value.diagnostic["evidence_scope"] == "this_client_request_dispatch"
        assert error.value.diagnostic["automatic_retry"] is False
        assert calls == ["held_read"] * 32
    finally:
        release.set()
        await asyncio.gather(*busy)


async def test_catalog_lock_queue_uses_the_same_predispatch_deadline():
    pool = MCPClientPool(call_timeout=0.03)
    calls = []

    async def write(name, arguments):
        calls.append(name)
        return CallToolResult(content=[])

    pool.sessions["peer"] = SimpleNamespace(call_tool=write)
    pool.connection_ids["peer"] = "original"
    pool.catalog_dirty.add("peer")
    lock = pool.catalog_locks["peer"] = asyncio.Lock()
    await lock.acquire()
    try:
        with pytest.raises(BridgeError) as error:
            await asyncio.wait_for(pool.call("peer", "write_once", {}), 0.3)
        assert error.value.code == "peer_timeout"
        assert error.value.diagnostic["accepted"] == "no"
        assert error.value.diagnostic["automatic_retry"] is False
        assert not calls and "peer" in pool.catalog_dirty
    finally:
        lock.release()


async def test_standalone_catalog_deadline_includes_lock_wait():
    pool = MCPClientPool(call_timeout=0.03)
    pool.sessions["peer"] = SimpleNamespace()
    pool.catalog_dirty.add("peer")
    lock = pool.catalog_locks["peer"] = asyncio.Lock()
    await lock.acquire()
    observer = asyncio.timeout(0.3)
    try:
        with pytest.raises(TimeoutError):
            async with observer:
                await pool.list_tools("peer")
        assert not observer.expired(), "The catalog must enforce its own deadline"
        assert "peer" in pool.catalog_dirty
    finally:
        lock.release()


@pytest.mark.parametrize("through_call", [False, True])
async def test_catalog_eof_closes_only_its_original_owner_without_tool_replay(through_call):
    pool = MCPClientPool()
    calls = []

    async def listing(cursor=None):
        raise McpError(ErrorData(code=CONNECTION_CLOSED, message="Catalog EOF"))

    async def write(name, arguments):
        calls.append(name)

    owner, _, release = attach_connection(
        pool, session=SimpleNamespace(list_tools=listing, call_tool=write)
    )
    release.set()
    pool.catalog_dirty.add("peer")
    try:
        if through_call:
            with pytest.raises(BridgeError) as error:
                await pool.call("peer", "write_once", {})
            assert error.value.code == "peer_disconnected"
            assert error.value.diagnostic["accepted"] == "no"
            assert error.value.diagnostic["connection_id"] == "first-connection"
            assert error.value.diagnostic["automatic_retry"] is False
        else:
            with pytest.raises(McpError) as error:
                await pool.list_tools("peer")
            assert error.value.error.code == CONNECTION_CLOSED
        assert owner.done() and not pool.owners and not pool.sessions
        assert not calls
    finally:
        await pool.close()


async def test_old_catalog_eof_cannot_close_or_relabel_replacement():
    pool = MCPClientPool()
    entered, closed = asyncio.Event(), asyncio.Event()

    async def listing(cursor=None):
        entered.set()
        await closed.wait()
        raise McpError(ErrorData(code=CONNECTION_CLOSED, message="Old catalog EOF"))

    _, _, release = attach_connection(pool, session=SimpleNamespace(list_tools=listing))
    pool.catalog_dirty.add("peer")
    pending = asyncio.create_task(pool.call("peer", "write_once", {}))
    await entered.wait()
    release.set()
    await pool.disconnect("peer")
    replacement, _, replacement_release = attach_connection(pool)
    pool.connection_ids["peer"] = "replacement"
    pool.phases["peer"] = "connection.ready"
    try:
        closed.set()
        outcome = (await asyncio.gather(pending, return_exceptions=True))[0]
        assert isinstance(outcome, BridgeError) and outcome.code == "peer_disconnected"
        assert outcome.diagnostic["connection_id"] == "first-connection"
        assert outcome.diagnostic["accepted"] == "no"
        assert pool.owners["peer"] is replacement and not replacement.done()
        assert pool.phases["peer"] == "connection.ready"
    finally:
        replacement_release.set()
        await pool.close()


async def test_sdk_catalog_timeout_is_typed_before_any_tool_dispatch():
    pool = MCPClientPool(call_timeout=1)
    calls = []

    async def listing(cursor=None):
        raise TimeoutError("SDK read deadline")

    async def write(name, arguments):
        calls.append(name)

    pool.sessions["peer"] = SimpleNamespace(list_tools=listing, call_tool=write)
    pool.connection_ids["peer"] = "original"
    pool.catalogs["peer"] = ["previous catalog"]
    pool.catalog_dirty.add("peer")
    with pytest.raises(BridgeError) as error:
        await pool.call("peer", "write_once", {})
    assert error.value.code == "peer_timeout"
    assert error.value.diagnostic["connection_id"] == "original"
    assert error.value.diagnostic["accepted"] == "no"
    assert error.value.diagnostic["evidence_scope"] == "this_client_request_dispatch"
    assert error.value.diagnostic["automatic_retry"] is False
    assert not calls and pool.catalogs["peer"] == ["previous catalog"]
    assert "peer" in pool.catalog_dirty


async def test_timeout_after_remote_dispatch_stays_unknown_without_retry():
    pool = MCPClientPool(call_timeout=0.03)
    calls = []

    async def write(name, arguments):
        calls.append(name)
        await asyncio.Event().wait()

    pool.sessions["peer"] = SimpleNamespace(call_tool=write)
    pool.connection_ids["peer"] = "original"
    with pytest.raises(BridgeError) as error:
        await pool.call("peer", "write_once", {})
    assert calls == ["write_once"]
    assert error.value.code == "peer_unknown"
    assert error.value.diagnostic["accepted"] == "unknown"
    assert error.value.diagnostic["automatic_retry"] is False


async def test_catalog_time_is_not_reset_when_remote_dispatch_begins():
    pool = MCPClientPool(call_timeout=0.2)
    calls = []

    async def listing(cursor=None):
        await asyncio.sleep(0.12)
        return SimpleNamespace(tools=[Tool(name="write_once", inputSchema={})], nextCursor=None)

    async def write(name, arguments):
        calls.append(name)
        await asyncio.sleep(0.12)
        return CallToolResult(content=[])

    pool.sessions["peer"] = SimpleNamespace(list_tools=listing, call_tool=write)
    pool.connection_ids["peer"] = "original"
    pool.catalog_dirty.add("peer")
    with pytest.raises(BridgeError) as error:
        await pool.call("peer", "write_once", {})
    assert calls == ["write_once"]
    assert error.value.code == "peer_unknown"
    assert error.value.diagnostic["automatic_retry"] is False
