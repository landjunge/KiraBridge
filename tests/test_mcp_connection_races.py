"""Connection teardown and catalog invalidation remain generation-local."""

import asyncio
from types import SimpleNamespace

import pytest
from mcp.shared.exceptions import McpError
from mcp.types import CONNECTION_CLOSED, CallToolResult, ErrorData, Tool

from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool


def attach_connection(pool, peer_id="peer", session=None):
    stop, release = asyncio.Event(), asyncio.Event()

    async def owner():
        try:
            await stop.wait()
            await release.wait()
        finally:
            pool.sessions.pop(peer_id, None)

    owner_task = asyncio.create_task(owner())
    pool.owners[peer_id] = owner_task
    pool.stops[peer_id] = stop
    pool.sessions[peer_id] = session or SimpleNamespace()
    pool.connection_ids[peer_id] = "first-connection"
    return owner_task, stop, release


async def test_two_concurrent_disconnects_share_one_cleanup():
    pool = MCPClientPool()
    owner, stop, release = attach_connection(pool)
    first = asyncio.create_task(pool.disconnect("peer"))
    second = asyncio.create_task(pool.disconnect("peer"))
    await stop.wait()
    release.set()

    outcomes = await asyncio.gather(first, second, return_exceptions=True)

    assert outcomes == [None, None]
    assert owner.done()
    assert not pool.owners and not pool.stops and not pool.connection_ids
    assert pool.previous_ids == {"peer": "first-connection"}


async def test_cancelling_one_disconnect_observer_does_not_abandon_teardown():
    pool = MCPClientPool()
    owner, stop, release = attach_connection(pool)
    observer = asyncio.create_task(pool.disconnect("peer"))
    await stop.wait()
    observer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await observer
    assert not owner.done()

    second = asyncio.create_task(pool.disconnect("peer"))
    release.set()
    await second

    assert owner.done() and not pool.owners and not pool.connection_ids
    assert pool.previous_ids == {"peer": "first-connection"}


async def test_already_cancelled_connection_owner_still_releases_capacity():
    pool = MCPClientPool()
    owner, _, _ = attach_connection(pool)
    owner.cancel()
    await asyncio.gather(owner, return_exceptions=True)

    await pool.disconnect("peer")

    assert not pool.owners and not pool.stops and not pool.connection_ids


async def test_parallel_remote_eofs_keep_each_write_unknown_without_replay():
    pool = MCPClientPool()
    calls, both_called = [], asyncio.Event()

    async def closed(tool, arguments):
        calls.append(arguments["id"])
        if len(calls) == 2:
            both_called.set()
        await both_called.wait()
        raise McpError(ErrorData(code=CONNECTION_CLOSED, message="Closed"))

    _, stop, release = attach_connection(pool, session=SimpleNamespace(call_tool=closed))
    first = asyncio.create_task(pool.call("peer", "write_once", {"id": "first"}))
    second = asyncio.create_task(pool.call("peer", "write_once", {"id": "second"}))
    await stop.wait()
    release.set()
    results = await asyncio.gather(first, second, return_exceptions=True)

    assert calls == ["first", "second"]
    assert all(isinstance(error, BridgeError) and error.code == "peer_unknown" for error in results)
    assert all(error.diagnostic["automatic_retry"] is False for error in results)
    assert not pool.owners and not pool.connection_ids


async def test_old_disconnect_observers_do_not_remove_a_replacement_connection():
    pool = MCPClientPool()
    _, stop, release = attach_connection(pool)
    first = asyncio.create_task(pool.disconnect("peer"))
    second = asyncio.create_task(pool.disconnect("peer"))
    await stop.wait()
    release.set()
    await first
    replacement, _, replacement_release = attach_connection(pool)
    pool.connection_ids["peer"] = "replacement-connection"
    try:
        await second
        assert pool.owners["peer"] is replacement
        assert pool.connection_ids["peer"] == "replacement-connection"
        assert not replacement.done()
    finally:
        replacement_release.set()
        await pool.disconnect("peer")


@pytest.mark.parametrize(
    "error", [McpError(ErrorData(code=CONNECTION_CLOSED, message="Old EOF")), TimeoutError()]
)
async def test_delayed_old_call_failure_cannot_disconnect_or_relabel_replacement(error):
    pool = MCPClientPool()
    started, fail = asyncio.Event(), asyncio.Event()
    calls = []

    async def old_call(tool, arguments):
        calls.append((tool, arguments))
        started.set()
        await fail.wait()
        raise error

    _, _, release = attach_connection(pool, session=SimpleNamespace(call_tool=old_call))
    pending = asyncio.create_task(pool.call("peer", "write_once", {"id": "original"}))
    await started.wait()
    release.set()
    await pool.disconnect("peer")
    replacement, _, replacement_release = attach_connection(pool)
    pool.connection_ids["peer"] = "replacement-connection"
    pool.phases["peer"] = "connection.ready"
    try:
        fail.set()
        result = (await asyncio.gather(pending, return_exceptions=True))[0]
        assert isinstance(result, BridgeError) and result.code == "peer_unknown"
        assert calls == [("write_once", {"id": "original"})]
        assert result.diagnostic["connection_id"] == "first-connection"
        assert result.diagnostic["automatic_retry"] is False
        assert pool.owners.get("peer") is replacement
        assert pool.connection_ids.get("peer") == "replacement-connection"
        assert pool.phases.get("peer") == "connection.ready"
        assert not replacement.done()
    finally:
        replacement_release.set()
        await pool.disconnect("peer")


async def test_gate_waiter_stops_before_dispatch_to_old_session():
    waiting = asyncio.Event()
    calls = []

    def observe(kind, data, **metadata):
        if data.get("phase") == "call.started":
            waiting.set()

    async def old_write(name, arguments):
        calls.append((name, arguments))
        return CallToolResult(content=[])

    pool = MCPClientPool(observer=observe)
    pool.gate = asyncio.Semaphore(0)
    _, _, release = attach_connection(pool, session=SimpleNamespace(call_tool=old_write))
    pending = asyncio.create_task(pool.call("peer", "write_once", {"id": "original"}))
    await waiting.wait()
    release.set()
    await pool.disconnect("peer")
    replacement, _, replacement_release = attach_connection(pool)
    pool.connection_ids["peer"] = "replacement-connection"
    pool.phases["peer"] = "connection.ready"
    try:
        pool.gate.release()
        outcome = (await asyncio.gather(pending, return_exceptions=True))[0]
        assert calls == []
        assert isinstance(outcome, BridgeError) and outcome.code == "peer_disconnected"
        assert outcome.diagnostic["connection_id"] == "first-connection"
        assert outcome.diagnostic["accepted"] == "no"
        assert outcome.diagnostic["started"] == "no"
        assert outcome.diagnostic["completed"] == "no"
        assert outcome.diagnostic["evidence_scope"] == "this_client_request_dispatch"
        assert outcome.diagnostic["automatic_retry"] is False
        assert pool.owners.get("peer") is replacement and not replacement.done()
        assert pool.phases["peer"] == "connection.ready"
    finally:
        replacement_release.set()
        await pool.disconnect("peer")


async def test_refresh_waiter_reports_original_request_not_dispatched():
    entered, resume = asyncio.Event(), asyncio.Event()
    calls = []

    async def catalog(cursor=None):
        entered.set()
        await resume.wait()
        return SimpleNamespace(tools=[Tool(name="write_once", inputSchema={})], nextCursor=None)

    async def old_write(name, arguments):
        calls.append((name, arguments))
        return CallToolResult(content=[])

    pool = MCPClientPool()
    _, _, release = attach_connection(
        pool, session=SimpleNamespace(call_tool=old_write, list_tools=catalog)
    )
    pool.catalog_dirty.add("peer")
    pending = asyncio.create_task(pool.call("peer", "write_once", {"id": "original"}))
    await entered.wait()
    release.set()
    await pool.disconnect("peer")
    replacement, _, replacement_release = attach_connection(pool)
    pool.connection_ids["peer"] = "replacement-connection"
    pool.phases["peer"] = "connection.ready"
    try:
        resume.set()
        outcome = (await asyncio.gather(pending, return_exceptions=True))[0]
        assert calls == []
        assert isinstance(outcome, BridgeError) and outcome.code == "peer_disconnected"
        assert outcome.diagnostic["connection_id"] == "first-connection"
        assert outcome.diagnostic["accepted"] == "no"
        assert outcome.diagnostic["started"] == "no"
        assert outcome.diagnostic["completed"] == "no"
        assert outcome.diagnostic["evidence_scope"] == "this_client_request_dispatch"
        assert outcome.diagnostic["automatic_retry"] is False
        assert pool.owners.get("peer") is replacement and not replacement.done()
        assert pool.phases["peer"] == "connection.ready"
    finally:
        replacement_release.set()
        await pool.disconnect("peer")


async def test_remote_bridge_error_is_still_unknown_after_dispatch():
    calls = []

    async def remote_failure(name, arguments):
        calls.append(name)
        raise BridgeError("peer_disconnected", "Error returned after sending the request")

    pool = MCPClientPool()
    pool.sessions["peer"] = SimpleNamespace(call_tool=remote_failure)
    pool.connection_ids["peer"] = "first-connection"
    with pytest.raises(BridgeError) as error:
        await pool.call("peer", "write_once", {})

    assert calls == ["write_once"]
    assert error.value.code == "peer_unknown"
    assert error.value.diagnostic["accepted"] == "unknown"
    assert error.value.diagnostic["started"] == "unknown"
    assert error.value.diagnostic["automatic_retry"] is False


class ChangingCatalogSession:
    def __init__(self, pool):
        self.pool = pool
        self.list_calls = 0
        self.tool_calls = []

    async def list_tools(self, cursor=None):
        self.list_calls += 1
        if self.list_calls == 1:
            # This is the same invalidation the SDK notification callback emits.
            self.pool.catalog_dirty.add("peer")
        return SimpleNamespace(
            tools=[Tool(name="safe_read", inputSchema={"type": "object"})], nextCursor=None
        )

    async def call_tool(self, tool, arguments):
        self.tool_calls.append((tool, arguments))
        return CallToolResult(content=[], structuredContent={"ok": True})


async def test_catalog_change_during_refresh_is_not_lost_before_next_call():
    pool = MCPClientPool()
    session = ChangingCatalogSession(pool)
    pool.sessions["peer"] = session
    pool.connection_ids["peer"] = "first-connection"
    await pool.list_tools("peer")

    await pool.call("peer", "safe_read", {})

    assert session.list_calls == 2
    assert session.tool_calls == [("safe_read", {})]
    assert "peer" not in pool.catalog_dirty


async def test_catalog_refresh_cannot_publish_from_an_old_connection_generation():
    pool = MCPClientPool()
    replacement = SimpleNamespace()

    async def list_tools(cursor=None):
        pool.sessions["peer"] = replacement
        pool.connection_ids["peer"] = "replacement-connection"
        pool.catalogs["peer"] = ["replacement-catalog"]
        return SimpleNamespace(
            tools=[Tool(name="old_read", inputSchema={"type": "object"})], nextCursor=None
        )

    pool.sessions["peer"] = SimpleNamespace(list_tools=list_tools)
    pool.connection_ids["peer"] = "first-connection"

    with pytest.raises(BridgeError) as error:
        await pool.list_tools("peer")

    assert error.value.code == "peer_disconnected"
    assert pool.catalogs["peer"] == ["replacement-catalog"]
    assert "peer" not in pool.catalog_dirty


async def test_failed_refresh_remains_dirty_and_never_calls_the_remote_tool():
    pool = MCPClientPool()
    session = ChangingCatalogSession(pool)
    pool.sessions["peer"] = session
    pool.connection_ids["peer"] = "first-connection"
    pool.catalogs["peer"] = ["old-catalog"]
    pool.catalog_dirty.add("peer")

    async def fail(cursor=None):
        raise TimeoutError

    session.list_tools = fail
    with pytest.raises(BridgeError) as error:
        await pool.call("peer", "safe_read", {})

    assert error.value.code == "peer_timeout"
    assert error.value.diagnostic["accepted"] == "no"
    assert pool.catalogs["peer"] == ["old-catalog"]
    assert "peer" in pool.catalog_dirty
    assert session.tool_calls == []


async def test_catalog_waiting_for_lock_cannot_clear_new_generation_invalidation():
    pool = MCPClientPool()
    session = ChangingCatalogSession(pool)
    pool.sessions["peer"] = session
    lock = pool.catalog_locks["peer"] = asyncio.Lock()
    await lock.acquire()
    pending = asyncio.create_task(pool.list_tools("peer"))
    await asyncio.sleep(0)  # Let this read pin the old generation before waiting.
    pool.sessions["peer"] = SimpleNamespace()
    pool.catalog_dirty.add("peer")
    lock.release()

    with pytest.raises(BridgeError) as error:
        await pending

    assert error.value.code == "peer_disconnected"
    assert "peer" in pool.catalog_dirty
    assert session.list_calls == 0
