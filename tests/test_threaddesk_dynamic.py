"""Security and compatibility boundaries for opt-in dynamic ThreadDesk tools."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool
from kirabridge.threaddesk_dynamic import _read_tool, catalog, read


def tool(name, *, readonly=True, destructive=False, schema=None):
    return SimpleNamespace(
        name=name,
        description="Example read",
        annotations=SimpleNamespace(readOnlyHint=readonly, destructiveHint=destructive),
        inputSchema=schema
        or {
            "type": "object",
            "additionalProperties": False,
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    )


def bridge_fixture(monkeypatch, config, *, enabled=True, automatic=True):
    listing = SimpleNamespace(
        tools=[tool("new_read"), tool("writer", readonly=False)], nextCursor=None
    )
    pool = MCPClientPool(call_timeout=2)
    manager = SimpleNamespace(
        lock=asyncio.Lock(),
        settings=SimpleNamespace(timeout=2, max_result_bytes=2048),
        connect=AsyncMock(),
        pool=pool,
        decode=lambda response, mutation: (True, json.loads(response.content[0].text)),
    )
    pool.sessions = {"threaddesk": SimpleNamespace(list_tools=AsyncMock(return_value=listing))}
    pool.call = AsyncMock(
        return_value=SimpleNamespace(
            structuredContent=None,
            isError=False,
            content=[SimpleNamespace(type="text", text=json.dumps({"id": "abc"}))],
        )
    )
    config.threaddesk.dynamic_read_proxy = enabled
    policy = config.principals["local"]
    policy.approval_mode = "automatic" if automatic else "manual"

    def principal(name, capability=None):
        if name not in config.principals or (capability and capability not in policy.capabilities):
            raise BridgeError("forbidden", "Capability not granted")
        return policy

    bridge = SimpleNamespace(
        config=config,
        security=SimpleNamespace(principal=principal),
        threaddesk=manager,
    )
    return bridge, listing


def test_readonly_annotation_must_be_explicit_and_schema_well_formed():
    assert _read_tool(tool("new_read"))["name"] == "new_read"
    assert _read_tool(tool("writer", readonly=False)) is None
    assert _read_tool(tool("ambiguous", destructive=True)) is None
    assert _read_tool(tool("bad", schema={"type": "array"})) is None
    assert (
        _read_tool(
            tool(
                "external",
                schema={
                    "type": "object",
                    "properties": {"id": {"$ref": "https://example.org/schema"}},
                },
            )
        )
        is None
    )


@pytest.mark.asyncio
async def test_discovery_and_call_use_live_catalog_and_validate_schema(monkeypatch, config):
    bridge, listing = bridge_fixture(monkeypatch, config)
    names = {x["name"] for x in (await catalog(bridge, "local"))["tools"]}
    assert names == {"new_read"}
    result = await read(bridge, "local", "new_read", {"id": "abc"})
    assert result["value"]["id"] == "abc"
    bridge.threaddesk.pool.call.assert_awaited_once_with("threaddesk", "new_read", {"id": "abc"})
    with pytest.raises(BridgeError, match="Arguments do not match"):
        await read(bridge, "local", "new_read", {"id": 12})
    assert bridge.threaddesk.pool.call.await_count == 1

    # The peer revokes the read annotation after the earlier tools/list.
    listing.tools[0] = tool("new_read", readonly=False)
    with pytest.raises(BridgeError, match="explicitly read-only"):
        await read(bridge, "local", "new_read", {"id": "abc"})
    assert bridge.threaddesk.pool.call.await_count == 1


@pytest.mark.asyncio
async def test_proxy_disabled_or_approval_required_means_no_peer_execution(monkeypatch, config):
    bridge, _ = bridge_fixture(monkeypatch, config, enabled=False)
    assert (await catalog(bridge, "local"))["tools"] == []
    with pytest.raises(BridgeError, match="disabled"):
        await read(bridge, "local", "new_read", {"id": "abc"})
    bridge.threaddesk.connect.assert_not_awaited()
    bridge, _ = bridge_fixture(monkeypatch, config, automatic=False)
    with pytest.raises(BridgeError, match="automatic"):
        await catalog(bridge, "local")
    bridge.threaddesk.connect.assert_not_awaited()


@pytest.mark.parametrize("level", ["full", "medium"])
async def test_effective_read_grant_overrides_legacy_manual_mode(monkeypatch, config, level):
    bridge, _ = bridge_fixture(monkeypatch, config, automatic=False)
    config.principals["local"].permission_level = level
    assert (await catalog(bridge, "local"))["tools"][0]["name"] == "new_read"
    assert (await read(bridge, "local", "new_read", {"id": "abc"}))["success"]


async def test_effective_ask_level_denies_legacy_automatic_mode(monkeypatch, config):
    bridge, _ = bridge_fixture(monkeypatch, config)
    config.principals["local"].permission_level = "ask"
    with pytest.raises(BridgeError) as exc:
        await catalog(bridge, "local")
    assert exc.value.code == "approval_required"
    bridge.threaddesk.connect.assert_not_awaited()


async def test_dynamic_discovery_includes_bounded_catalog_later_pages(monkeypatch, config):
    bridge, first = bridge_fixture(monkeypatch, config)
    first.nextCursor = "page-two"
    second = SimpleNamespace(tools=[tool("later_read")], nextCursor=None)
    session = bridge.threaddesk.pool.sessions["threaddesk"]
    session.list_tools.side_effect = [first, second, first, second]
    assert {entry["name"] for entry in (await catalog(bridge, "local"))["tools"]} == {
        "new_read",
        "later_read",
    }
    assert (await read(bridge, "local", "later_read", {"id": "abc"}))["success"]
    assert session.list_tools.await_args_list[1].kwargs == {"cursor": "page-two"}


async def test_full_level_does_not_invent_missing_read_capability(monkeypatch, config):
    bridge, _ = bridge_fixture(monkeypatch, config)
    policy = config.principals["local"]
    policy.permission_level = "full"
    policy.capabilities.remove("threaddesk.read")
    with pytest.raises(BridgeError) as exc:
        await catalog(bridge, "local")
    assert exc.value.code == "forbidden"
    bridge.threaddesk.connect.assert_not_awaited()
