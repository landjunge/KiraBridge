"""Catalog retention has a UTF-8 byte bound in addition to count/page bounds."""

import copy
from types import SimpleNamespace

import pytest
from mcp.types import Tool

from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool


def pool_with_pages(pages, budget):
    pool = MCPClientPool()
    pool.max_catalog_bytes = budget
    calls = []

    async def listing(cursor=None):
        calls.append(cursor)
        return pages[min(len(calls) - 1, len(pages) - 1)]

    pool.sessions["peer"] = SimpleNamespace(list_tools=listing)
    pool.connection_ids["peer"] = "original"
    return pool, calls


async def test_oversized_schema_never_replaces_last_catalog_and_stays_dirty():
    tool = Tool(name="large", inputSchema={"type": "object", "description": "ä" * 500})
    pool, calls = pool_with_pages([SimpleNamespace(tools=[tool], nextCursor=None)], 128)
    pool.catalogs["peer"] = ["previous catalog"]
    with pytest.raises(BridgeError) as error:
        await pool.list_tools("peer")
    assert error.value.code == "tool_catalog_invalid"
    assert pool.catalogs["peer"] == ["previous catalog"]
    assert "peer" in pool.catalog_dirty and calls == [None]


async def test_oversized_refresh_never_dispatches_tool_from_old_catalog():
    tool = Tool(name="write_once", inputSchema={}, outputSchema={"description": "x" * 500})
    pool, _ = pool_with_pages([SimpleNamespace(tools=[tool], nextCursor=None)], 128)
    dispatched = []

    async def write(name, arguments):
        dispatched.append(name)

    pool.sessions["peer"].call_tool = write
    pool.catalogs["peer"] = ["previous catalog"]
    pool.catalog_dirty.add("peer")
    with pytest.raises(BridgeError) as error:
        await pool.call("peer", "write_once", {})
    assert error.value.code == "tool_catalog_invalid"
    assert not dispatched and pool.catalogs["peer"] == ["previous catalog"]


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), "\ud800"])
async def test_non_json_catalog_fails_with_typed_error_without_partial_cache(invalid):
    tool = Tool(name="invalid", inputSchema={"default": invalid})
    pool, _ = pool_with_pages([SimpleNamespace(tools=[tool], nextCursor=None)], 1024)
    with pytest.raises(BridgeError) as error:
        await pool.list_tools("peer")
    assert error.value.code == "tool_catalog_invalid"
    assert not pool.catalogs and "peer" in pool.catalog_dirty


async def test_exact_utf8_budget_preserves_complete_schemas_and_metadata():
    tool = Tool(
        name="original",
        inputSchema={"type": "object", "description": "ä" * 60},
        outputSchema={"type": "object", "properties": {"result": {"type": "integer"}}},
        _meta={"peer_note": "unchanged"},
    )
    original = copy.deepcopy(tool.model_dump(by_alias=True))
    encoded = tool.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8")
    pool, _ = pool_with_pages([SimpleNamespace(tools=[tool], nextCursor=None)], len(encoded) + 2)
    result = await pool.list_tools("peer")
    assert result == [tool] and result[0] is tool
    assert tool.model_dump(by_alias=True) == original
    pool.max_catalog_bytes -= 1
    with pytest.raises(BridgeError) as error:
        await pool.list_tools("peer")
    assert error.value.code == "tool_catalog_invalid"


async def test_byte_budget_spans_all_pages_including_description_and_metadata():
    first = Tool(name="first", inputSchema={}, description="x" * 100)
    second = Tool(name="second", inputSchema={}, _meta={"note": "x" * 100})
    # Each page fits independently; retaining both does not.
    budget = (
        max(
            len(tool.model_dump_json(by_alias=True, exclude_none=True).encode())
            for tool in (first, second)
        )
        + 2
    )
    pool, calls = pool_with_pages(
        [
            SimpleNamespace(tools=[first], nextCursor="second"),
            SimpleNamespace(tools=[second], nextCursor=None),
        ],
        budget,
    )
    with pytest.raises(BridgeError) as error:
        await pool.list_tools("peer")
    assert error.value.code == "tool_catalog_invalid"
    assert calls == [None, "second"] and not pool.catalogs


@pytest.mark.parametrize("count,pages", [(513, 1), (0, 9)])
async def test_byte_headroom_does_not_relax_count_or_page_budget(count, pages):
    results = [
        SimpleNamespace(
            tools=[Tool(name=f"tool-{index}", inputSchema={}) for index in range(count)],
            nextCursor=f"page-{page}" if page < pages - 1 else None,
        )
        for page in range(pages)
    ]
    pool, calls = pool_with_pages(results, 8 * 1024 * 1024)
    with pytest.raises(BridgeError) as error:
        await pool.list_tools("peer")
    assert error.value.code == "tool_catalog_invalid"
    assert len(calls) <= 8 and not pool.catalogs
