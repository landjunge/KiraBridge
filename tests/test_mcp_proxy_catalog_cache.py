"""Bounded schema reuse never caches effects, permissions or failed refreshes."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import request
from mcp.types import CallToolResult, Tool
from test_mcp import http_bridge  # noqa: F401

from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.proxy import DaemonConnection


def proxy(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(
        "kirabridge.mcp_gateway.proxy.time", SimpleNamespace(monotonic=lambda: now[0])
    )
    pool = MCPClientPool()
    tool = Tool(
        name="write_once",
        inputSchema={"type": "object"},
        _meta={"kirabridge": {"revision": "first", "principal": "local"}},
    )
    session = SimpleNamespace(
        list_tools=AsyncMock(return_value=SimpleNamespace(tools=[tool], nextCursor=None)),
        call_tool=AsyncMock(return_value=CallToolResult(content=[], structuredContent={})),
    )
    pool.sessions["daemon"] = session
    pool.connection_ids["daemon"] = "first-generation"
    connection = DaemonConnection(pool, Peer("daemon", url="http://127.0.0.1:1/mcp"))
    return connection, session, now


async def test_warm_calls_reuse_only_schemas_and_explicit_discovery_is_fresh(monkeypatch):
    connection, session, now = proxy(monkeypatch)
    await connection.call_tool("write_once", {"text": "A"})
    now[0] += 5.3
    await connection.call_tool("write_once", {"text": "B"})
    assert session.list_tools.await_count == 1
    assert session.call_tool.await_args_list[0].args == ("write_once", {"text": "A"})
    assert session.call_tool.await_args_list[1].args == ("write_once", {"text": "B"})
    await connection.list_tools()
    assert session.list_tools.await_count == 2
    now[0] += 30.1
    await connection.call_tool("write_once", {"text": "C"})
    assert session.list_tools.await_count == 3


@pytest.mark.parametrize("change", ["notification", "generation", "external_refresh", "epoch"])
async def test_catalog_invalidation_expires_a_warm_entry(monkeypatch, change):
    connection, session, _ = proxy(monkeypatch)
    await connection.call_tool("write_once", {})
    if change == "notification":
        connection.pool.catalog_dirty.add("daemon")
    elif change == "generation":
        connection.pool.connection_ids["daemon"] = "replacement"
    elif change == "external_refresh":
        await connection.pool.list_tools("daemon")
    else:
        session.call_tool.return_value = CallToolResult(
            content=[], structuredContent={"discovery": {"revision": "changed"}}
        )
        await connection.call_tool("write_once", {})
    previous = session.list_tools.await_count
    await connection.call_tool("write_once", {})
    assert session.list_tools.await_count == previous + 1


async def test_dirty_refresh_failure_never_dispatches_with_cached_schemas(monkeypatch):
    connection, session, _ = proxy(monkeypatch)
    await connection.call_tool("write_once", {})
    connection.pool.catalog_dirty.add("daemon")
    session.list_tools.side_effect = TimeoutError
    with pytest.raises(TimeoutError):
        await connection.call_tool("write_once", {})
    assert session.call_tool.await_count == 1
    assert connection._catalog is None
    assert "daemon" in connection.pool.catalog_dirty


async def test_concurrent_misses_share_one_refresh_without_coalescing_writes(monkeypatch):
    connection, session, _ = proxy(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    result = session.list_tools.return_value

    async def listing(cursor=None):
        entered.set()
        await release.wait()
        return result

    session.list_tools.side_effect = listing
    first = asyncio.create_task(connection.call_tool("write_once", {"value": 1}))
    await entered.wait()
    second = asyncio.create_task(connection.call_tool("write_once", {"value": 2}))
    release.set()
    await asyncio.gather(first, second)
    assert session.list_tools.await_count == 1
    assert session.call_tool.await_count == 2


async def test_removed_tool_during_invalidation_is_not_dispatched(monkeypatch):
    connection, session, _ = proxy(monkeypatch)
    await connection.call_tool("write_once", {})
    connection.pool.catalog_dirty.add("daemon")
    session.list_tools.return_value = SimpleNamespace(tools=[], nextCursor=None)
    with pytest.raises(BridgeError) as error:
        await connection.call_tool("write_once", {})
    assert error.value.code == "tool_unavailable"
    assert session.call_tool.await_count == 1


async def test_remote_rechecks_a_warm_tool_and_no_write_is_retried(monkeypatch):
    connection, session, _ = proxy(monkeypatch)
    await connection.call_tool("write_once", {})
    session.call_tool.return_value = CallToolResult(
        content=[], isError=True, structuredContent={"error": {"code": "forbidden"}}
    )
    denied = await connection.call_tool("write_once", {})
    assert denied.isError and denied.structuredContent["error"]["code"] == "forbidden"
    assert session.list_tools.await_count == 1
    assert session.call_tool.await_count == 2


async def test_real_http_permission_revocation_is_enforced_with_warm_schema(
    http_bridge,  # noqa: F811 - imported pytest fixture
    monkeypatch,
):
    bridge, endpoint = http_bridge
    policy = bridge.config.principals["local"]
    policy.approval_mode = "automatic"
    root = policy.roots[0]
    # Freeze only the schema-cache clock, preserving asyncio's real deadlines.
    monkeypatch.setattr(
        "kirabridge.mcp_gateway.proxy.time", SimpleNamespace(monotonic=lambda: 10.0)
    )
    first = request("file.write", {"path": root + "/first", "text": "once"})
    second = request("file.write", {"path": root + "/second", "text": "denied"}, task_id="second")
    async with MCPClientPool() as pool:
        listing = AsyncMock(wraps=pool.list_tools)
        monkeypatch.setattr(pool, "list_tools", listing)
        connection = DaemonConnection(
            pool, Peer("daemon", url=endpoint, token="local-test-" + "a" * 40)
        )
        await connection.call_tool("task_request", {"request": first.model_dump()})
        assert (await bridge.tasks.wait("local", first.task_id))["state"] == "completed"
        policy.capabilities.remove("file.write")
        denied = await connection.call_tool("task_request", {"request": second.model_dump()})
        assert denied.structuredContent["error"]["code"] == "forbidden"
        listing.assert_awaited_once()
        assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
