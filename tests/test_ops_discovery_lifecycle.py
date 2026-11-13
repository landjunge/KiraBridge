"""Discovery recovery preserves dispatched writes and isolates short catalog reuse."""

import asyncio
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult, Tool

from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool
from kirabridge.threaddesk_manager import ThreadDeskManager


def attach(pool, session, peer="peer", connection="first"):
    stop = asyncio.Event()

    async def run():
        try:
            await stop.wait()
        finally:
            if pool.sessions.get(peer) is session:
                pool.sessions.pop(peer, None)

    owner = asyncio.create_task(run())
    pool.sessions[peer] = session
    pool.owners[peer] = owner
    pool.stops[peer] = stop
    pool.connection_ids[peer] = connection
    return owner, stop


def hanging_write_session():
    started, finish = asyncio.Event(), asyncio.Event()
    calls = []

    async def write(tool, arguments):
        calls.append((tool, arguments))
        started.set()
        await finish.wait()
        return CallToolResult(content=[], structuredContent={"operation_id": "write-one"})

    async def list_tools(**_):
        await asyncio.Event().wait()

    return SimpleNamespace(call_tool=write, list_tools=list_tools), started, finish, calls


async def test_catalog_timeout_does_not_interrupt_or_replay_a_dispatched_write():
    pool = MCPClientPool(call_timeout=1)
    session, started, finish, calls = hanging_write_session()
    owner, stop = attach(pool, session)
    write = asyncio.create_task(pool.call("peer", "write", {"id": "write-one"}))
    await started.wait()
    pool.call_timeout = 0.02
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(pool.list_tools("peer"), 0.2)
        assert not write.done() and not stop.is_set()
        with pytest.raises(BridgeError) as blocked:
            await asyncio.wait_for(pool.call("peer", "write", {"id": "write-two"}), 0.1)
        assert blocked.value.code == "peer_recovering"
        assert blocked.value.diagnostic["accepted"] == "no"
        assert blocked.value.diagnostic["automatic_retry"] is False
        finish.set()
        result = await asyncio.wait_for(write, 0.2)
        assert result.structuredContent == {"operation_id": "write-one"}
        assert owner.done() and not pool.owners
        assert calls == [("write", {"id": "write-one"})]
    finally:
        finish.set()
        await asyncio.gather(write, return_exceptions=True)
        await pool.close()


async def test_retirement_drains_on_existing_call_deadline_without_waiting_forever():
    pool = MCPClientPool(call_timeout=0.08)
    session, started, finish, calls = hanging_write_session()
    owner, stop = attach(pool, session)
    write = asyncio.create_task(pool.call("peer", "write", {}))
    await started.wait()
    pool.call_timeout = 0.01
    with pytest.raises(TimeoutError):
        await pool.list_tools("peer")
    with pytest.raises(BridgeError) as unknown:
        await asyncio.wait_for(write, 0.3)
    assert unknown.value.code == "peer_unknown"
    assert owner.done() and stop.is_set() and len(calls) == 1
    assert not pool._active_calls and not pool._catalog_retirements


async def test_last_old_write_cannot_retire_a_replacement_generation():
    pool = MCPClientPool(call_timeout=1)
    session, started, finish, _ = hanging_write_session()
    old_owner, old_stop = attach(pool, session)
    write = asyncio.create_task(pool.call("peer", "write", {}))
    await started.wait()
    pool.call_timeout = 0.01
    with pytest.raises(TimeoutError):
        await pool.list_tools("peer")
    generation = pool._generation("peer")
    replacement = SimpleNamespace()
    new_owner, new_stop = attach(pool, replacement, connection="replacement")
    try:
        assert not await pool.retire_catalog_connection("peer", generation=generation)
        finish.set()
        await write
        assert pool.sessions["peer"] is replacement and not new_stop.is_set()
        assert not pool.catalog_recovery_pending("peer")
    finally:
        old_stop.set()
        await old_owner
        await pool.close()
        assert new_owner.done()


async def test_catalog_timeout_without_dispatched_calls_closes_the_generation():
    pool = MCPClientPool(call_timeout=0.01)
    session, _, _, _ = hanging_write_session()
    owner, _ = attach(pool, session)
    with pytest.raises(TimeoutError):
        await pool.list_tools("peer")
    assert owner.done() and not pool.owners and not pool.sessions


async def test_explicit_shutdown_does_not_wait_for_a_retiring_write():
    pool = MCPClientPool(call_timeout=1)
    session, started, finish, calls = hanging_write_session()
    owner, _ = attach(pool, session)
    write = asyncio.create_task(pool.call("peer", "write", {}))
    await started.wait()
    pool.call_timeout = 0.01
    with pytest.raises(TimeoutError):
        await pool.list_tools("peer")
    try:
        await asyncio.wait_for(pool.close(), 0.2)
        assert owner.done() and not write.done()
        finish.set()
        await write
        assert len(calls) == 1 and not pool._catalog_retirements
    finally:
        finish.set()
        await asyncio.gather(write, return_exceptions=True)
        await pool.close()


class CatalogSession:
    def __init__(self):
        self.reads = 0
        self.tool = Tool(
            name="write", inputSchema={"type": "object", "properties": {"id": {"type": "string"}}}
        )

    async def list_tools(self, **_):
        self.reads += 1
        return SimpleNamespace(tools=[self.tool], nextCursor=None)


async def test_operation_catalog_is_short_lived_but_explicit_discovery_is_fresh(config):
    manager = ThreadDeskManager(config)
    session = CatalogSession()
    attach(manager.pool, session, "threaddesk")
    try:
        first = await manager.read_operation_catalog()
        first[0].inputSchema["properties"]["id"]["type"] = "integer"
        second = await manager.read_operation_catalog()
        second[0].inputSchema["properties"]["id"]["type"] = "boolean"
        assert (await manager.read_operation_catalog())[0].inputSchema["properties"]["id"] == {
            "type": "string"
        }
        assert session.reads == 1
        await manager.read_catalog()
        assert session.reads == 2
    finally:
        await manager.pool.close()


@pytest.mark.parametrize(
    "change", ["dirty", "session", "owner", "connection", "epoch", "age", "catalog"]
)
async def test_operation_catalog_does_not_reuse_invalidated_observations(config, change):
    manager = ThreadDeskManager(config)
    session = CatalogSession()
    pool = manager.pool
    pool.sessions["threaddesk"] = session
    pool.connection_ids["threaddesk"] = "first"
    await manager.read_operation_catalog()
    if change == "dirty":
        pool.catalog_dirty.add("threaddesk")
    elif change == "session":
        session = pool.sessions["threaddesk"] = CatalogSession()
    elif change == "owner":
        # Identity alone must suffice; no real process or connection is started.
        pool.owners["threaddesk"] = object()
    elif change == "connection":
        pool.connection_ids["threaddesk"] = "second"
    elif change == "epoch":
        pool.health_epochs["threaddesk"] = "new-version-or-discovery-revision"
    elif change == "age":
        observation = pool._catalog_observations["threaddesk"]
        pool._catalog_observations["threaddesk"] = (
            *observation[:3],
            observation[3] - 2,
            observation[4],
        )
    elif change == "catalog":
        pool.catalogs["threaddesk"] = []
    await manager.read_operation_catalog()
    assert session.reads == (1 if change == "session" else 2)


async def test_explicit_health_version_change_invalidates_catalog_reuse():
    pool, session = MCPClientPool(), CatalogSession()
    pool.sessions["peer"] = session
    pool.connection_ids["peer"] = "first"

    async def health(*_):
        return CallToolResult(
            content=[],
            structuredContent={
                "version": "new-version",
                "dispatcher_active": True,
                "discovery": {"instance_id": "one", "revision": "new-revision"},
            },
        )

    session.call_tool = health
    await pool.list_tools("peer")
    assert pool.cached_catalog("peer", max_age=1)
    await pool.call("peer", "bridge_epoch", {})
    assert pool.cached_catalog("peer", max_age=1) is None


async def test_manager_backstop_preserves_write_and_reports_no_reset(config, monkeypatch):
    config.threaddesk.timeout = 0.01
    manager = ThreadDeskManager(config)
    manager.pool.call_timeout = 1
    monkeypatch.setattr("kirabridge.threaddesk_manager.CATALOG_BACKSTOP_SECONDS", 0.01)
    session, started, finish, calls = hanging_write_session()
    owner, stop = attach(manager.pool, session, "threaddesk")
    write = asyncio.create_task(manager.pool.call("threaddesk", "write", {}))
    await started.wait()

    async def stuck(_):
        await asyncio.Event().wait()

    monkeypatch.setattr(manager.pool, "list_tools", stuck)
    try:
        with pytest.raises(BridgeError) as timeout:
            await asyncio.wait_for(manager.read_catalog(), 0.2)
        assert timeout.value.code == "threaddesk_catalog_timeout"
        assert timeout.value.diagnostic["peer_reset"] is False
        assert not stop.is_set() and not write.done()
        finish.set()
        await write
        assert owner.done() and len(calls) == 1
    finally:
        finish.set()
        await asyncio.gather(write, return_exceptions=True)
        await manager.pool.close()
