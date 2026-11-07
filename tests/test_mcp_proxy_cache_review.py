"""Independent race checks for bounded proxy metadata reuse."""

from types import SimpleNamespace

import pytest
from test_mcp_proxy_catalog_cache import proxy

from kirabridge.bridge_core.models import BridgeError


async def test_notification_during_catalog_refresh_is_not_swallowed(monkeypatch):
    connection, session, _ = proxy(monkeypatch)
    result = session.list_tools.return_value
    notified = False

    async def listing(cursor=None):
        nonlocal notified
        if not notified:
            notified = True
            connection.pool.catalog_dirty.add("daemon")
        return result

    session.list_tools.side_effect = listing
    await connection.call_tool("write_once", {"value": "one"})
    assert session.list_tools.await_count == 2
    assert session.call_tool.await_count == 1
    assert "daemon" not in connection.pool.catalog_dirty
    await connection.call_tool("write_once", {"value": "two"})
    assert session.list_tools.await_count == 3
    assert session.call_tool.await_count == 2


async def test_replaced_session_during_discovery_never_dispatches(monkeypatch):
    connection, session, _ = proxy(monkeypatch)
    result = session.list_tools.return_value

    async def listing(cursor=None):
        connection.pool.sessions["daemon"] = SimpleNamespace()
        connection.pool.connection_ids["daemon"] = "replacement"
        return result

    session.list_tools.side_effect = listing
    with pytest.raises(BridgeError) as error:
        await connection.call_tool("write_once", {})
    assert error.value.code == "peer_disconnected"
    assert session.call_tool.await_count == 0
    assert connection._catalog is None
