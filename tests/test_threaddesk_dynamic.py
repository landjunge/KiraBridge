"""Security and compatibility boundaries for opt-in dynamic ThreadDesk tools."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.types import Tool, ToolAnnotations

from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool
from kirabridge.threaddesk_dynamic import _read_tool, catalog, read


def tool(name, *, readonly=True, destructive=False, schema=None):
    return Tool(
        name=name,
        description="Example read",
        annotations=ToolAnnotations(readOnlyHint=readonly, destructiveHint=destructive),
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


@pytest.mark.parametrize("route", ["read", "catalog"])
@pytest.mark.parametrize("phase", ["discovery", "lock"])
@pytest.mark.parametrize(
    "revocation,code",
    [
        ("proxy", "threaddesk_proxy_disabled"),
        ("capability", "forbidden"),
        ("permission", "approval_required"),
    ],
)
async def test_dynamic_reads_recheck_revocation_after_wait(
    monkeypatch, config, route, phase, revocation, code
):
    bridge, listing = bridge_fixture(monkeypatch, config)

    def revoke():
        if revocation == "proxy":
            config.threaddesk.dynamic_read_proxy = False
        elif revocation == "capability":
            config.principals["local"].capabilities.remove("threaddesk.read")
        else:
            config.principals["local"].permission_level = "ask"

    async def invoke():
        if route == "read":
            return await read(bridge, "local", "new_read", {"id": "abc"})
        return await catalog(bridge, "local")

    if phase == "discovery":

        async def revoked_listing(*args, **kwargs):
            revoke()
            return listing

        bridge.threaddesk.pool.sessions["threaddesk"].list_tools.side_effect = revoked_listing
        pending = asyncio.create_task(invoke())
    else:
        async with bridge.threaddesk.lock:
            pending = asyncio.create_task(invoke())
            await asyncio.sleep(0)  # Let the request wait behind the existing lock owner.
            assert not pending.done()
            revoke()
    try:
        with pytest.raises(BridgeError) as exc:
            await asyncio.wait_for(pending, 1)
        assert exc.value.code == code
        bridge.threaddesk.pool.call.assert_not_awaited()
        if phase == "lock":
            bridge.threaddesk.connect.assert_not_awaited()
        else:
            bridge.threaddesk.connect.assert_awaited_once()
    finally:
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


async def test_full_proxy_discovers_all_authorized_effect_classes(monkeypatch, config):
    bridge, listing = bridge_fixture(monkeypatch, config, enabled=False)
    config.threaddesk.dynamic_tool_proxy = True
    unannotated = tool("future_capability")
    unannotated.annotations = None
    listing.tools.append(unannotated)
    discovered = await catalog(bridge, "local")
    assert discovered["mode"] == "authorized_tools"
    items = {item["name"]: item for item in discovered["tools"]}
    assert set(items) == {"new_read", "writer", "future_capability"}
    assert items["new_read"]["annotations"]["readOnlyHint"] is True
    for name in ("writer", "future_capability"):
        assert items[name]["annotations"]["readOnlyHint"] is False
        assert items[name]["requires_operation_id"] is True
    assert items["future_capability"]["annotations"]["destructiveHint"] is True
    bridge.threaddesk.pool.call.assert_not_awaited()


@pytest.mark.parametrize("removed", ["threaddesk.manage", "threaddesk.knowledge"])
async def test_generic_writes_cannot_bypass_existing_write_capabilities(
    monkeypatch, config, removed
):
    from kirabridge.threaddesk_dynamic import call

    bridge, _ = bridge_fixture(monkeypatch, config)
    config.threaddesk.dynamic_tool_proxy = True
    config.principals["local"].capabilities.remove(removed)
    assert {x["name"] for x in (await catalog(bridge, "local"))["tools"]} == {"new_read"}
    with pytest.raises(BridgeError) as failure:
        await call(bridge, "local", "writer", {"id": "abc"}, "stable-id")
    assert failure.value.code == "forbidden"
    bridge.threaddesk.pool.call.assert_not_awaited()


@pytest.mark.parametrize("identifier", [None, "", "unsafe identifier", "x" * 129])
async def test_generic_mutations_require_stable_id_before_submit(monkeypatch, config, identifier):
    from kirabridge.threaddesk_dynamic import call

    bridge, _ = bridge_fixture(monkeypatch, config)
    config.threaddesk.dynamic_tool_proxy = True
    with pytest.raises(BridgeError) as failure:
        await call(bridge, "local", "writer", {"id": "abc"}, identifier)
    assert failure.value.code == "invalid_arguments"
    bridge.threaddesk.pool.call.assert_not_awaited()


def test_proxy_mutation_envelope_preserves_peer_operation_id_schema():
    from kirabridge.mcp_gateway.proxy import dynamic_call_arguments, dynamic_input_schema

    schema = {"type": "object", "properties": {"operation_id": {"type": "integer"}}}
    item = {"name": "future_write", "inputSchema": schema, "requires_operation_id": True}
    wrapped = dynamic_input_schema(item)
    assert wrapped["properties"]["arguments"] is schema
    assert wrapped["properties"]["operation_id"]["type"] == "string"
    args = {"operation_id": "kb-owned-id", "arguments": {"operation_id": 17}}
    assert dynamic_call_arguments(item, args) == {"name": "future_write", **args}
    with pytest.raises(BridgeError):
        dynamic_call_arguments(item, {"operation_id": 17})


@pytest.mark.parametrize("arguments", [{"id": float("nan")}, {"id": float("inf")}])
async def test_dynamic_arguments_reject_non_json_numbers_before_peer(
    monkeypatch, config, arguments
):
    from kirabridge.threaddesk_dynamic import call

    bridge, _ = bridge_fixture(monkeypatch, config)
    with pytest.raises(BridgeError) as failure:
        await call(bridge, "local", "new_read", arguments)
    assert failure.value.code == "invalid_arguments"
    bridge.threaddesk.connect.assert_not_awaited()


async def test_generic_read_uses_one_fresh_catalog_and_retains_read_semantics(monkeypatch, config):
    from kirabridge.threaddesk_dynamic import call

    bridge, _ = bridge_fixture(monkeypatch, config)
    result = await call(bridge, "local", "new_read", {"id": "abc"})
    assert result["success"] and result["scope"] == "threaddesk_dynamic_read"
    assert result["value"] == {"id": "abc"}
    bridge.threaddesk.connect.assert_awaited_once()
    bridge.threaddesk.pool.sessions["threaddesk"].list_tools.assert_awaited_once()
    bridge.threaddesk.pool.call.assert_awaited_once_with("threaddesk", "new_read", {"id": "abc"})
