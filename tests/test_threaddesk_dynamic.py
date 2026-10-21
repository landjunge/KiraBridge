"""Security and compatibility boundaries for opt-in dynamic ThreadDesk tools."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
import json

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.threaddesk_dynamic import _read_tool, catalog, read


def tool(name, *, readonly=True, destructive=False, schema=None):
    return SimpleNamespace(
        name=name,
        description="Example read",
        annotations=SimpleNamespace(readOnlyHint=readonly, destructiveHint=destructive),
        inputSchema=schema or {
            "type": "object",
            "additionalProperties": False,
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    )


def bridge_fixture(monkeypatch, *, enabled=True, automatic=True):
    from kirabridge import permissions

    monkeypatch.setattr(
        permissions, "decision", lambda config, principal, operation: {"automatic": automatic}
    )
    listing = SimpleNamespace(tools=[tool("new_read"), tool("writer", readonly=False)])
    manager = SimpleNamespace(
        lock=asyncio.Lock(),
        settings=SimpleNamespace(timeout=2, max_result_bytes=2048),
        connect=AsyncMock(),
        pool=SimpleNamespace(
            sessions={"threaddesk": SimpleNamespace(list_tools=AsyncMock(return_value=listing))},
            call=AsyncMock(return_value=SimpleNamespace(
                structuredContent=None, isError=False,
                content=[SimpleNamespace(type="text", text=json.dumps({"id": "abc"}))],
            )),
        ),
        decode=lambda response, mutation: (True, json.loads(response.content[0].text)),
    )
    bridge = SimpleNamespace(
        config=SimpleNamespace(threaddesk=SimpleNamespace(dynamic_read_proxy=enabled)),
        security=SimpleNamespace(principal=lambda *args: None),
        threaddesk=manager,
    )
    return bridge, listing


def test_readonly_annotation_must_be_explicit_and_schema_well_formed():
    assert _read_tool(tool("new_read"))["name"] == "new_read"
    assert _read_tool(tool("writer", readonly=False)) is None
    assert _read_tool(tool("ambiguous", destructive=True)) is None
    assert _read_tool(tool("bad", schema={"type": "array"})) is None
    assert _read_tool(tool("external", schema={
        "type": "object", "properties": {"id": {"$ref": "https://example.org/schema"}}
    })) is None


@pytest.mark.asyncio
async def test_discovery_and_call_use_live_catalog_and_validate_schema(monkeypatch):
    bridge, listing = bridge_fixture(monkeypatch)
    names = {x["name"] for x in (await catalog(bridge, "local"))["tools"]}
    assert names == {"new_read"}
    result = await read(bridge, "local", "new_read", {"id": "abc"})
    assert result["value"]["id"] == "abc"
    bridge.threaddesk.pool.call.assert_awaited_once_with(
        "threaddesk", "new_read", {"id": "abc"}
    )
    with pytest.raises(BridgeError, match="Arguments do not match"):
        await read(bridge, "local", "new_read", {"id": 12})
    assert bridge.threaddesk.pool.call.await_count == 1

    # The peer revokes the read annotation after the earlier tools/list.
    listing.tools[0] = tool("new_read", readonly=False)
    with pytest.raises(BridgeError, match="explicitly read-only"):
        await read(bridge, "local", "new_read", {"id": "abc"})
    assert bridge.threaddesk.pool.call.await_count == 1


@pytest.mark.asyncio
async def test_proxy_disabled_or_approval_required_means_no_peer_execution(monkeypatch):
    bridge, _ = bridge_fixture(monkeypatch, enabled=False)
    assert (await catalog(bridge, "local"))["tools"] == []
    with pytest.raises(BridgeError, match="disabled"):
        await read(bridge, "local", "new_read", {"id": "abc"})
    bridge.threaddesk.connect.assert_not_awaited()
    bridge, _ = bridge_fixture(monkeypatch, automatic=False)
    with pytest.raises(BridgeError, match="automatic"):
        await catalog(bridge, "local")
    bridge.threaddesk.connect.assert_not_awaited()
