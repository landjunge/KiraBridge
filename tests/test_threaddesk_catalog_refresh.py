"""A connected peer's fresh declared tools govern reads and mutations without replay."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.types import CallToolResult

from kirabridge.bridge_core.models import (
    BridgeError,
    ThreadDeskKnowledgeInput,
    ThreadDeskManageInput,
    ThreadDeskReadInput,
    UncertainExecution,
)
from kirabridge.threaddesk_manager import ThreadDeskManager

BASE = {"list_threads", "get_thread", "thread_manage"}


def declared(name):
    return SimpleNamespace(name=name, inputSchema={})


def peer(config, names, stale):
    config.threaddesk.enabled = True
    config.threaddesk.command = sys.executable
    config.threaddesk.workspace = config.principals["local"].roots[0]
    manager = ThreadDeskManager(config)
    manager.available_tools = set(stale)
    ordered = sorted(names)
    session = SimpleNamespace(
        list_tools=AsyncMock(
            side_effect=[
                SimpleNamespace(tools=[declared(name) for name in ordered[:1]], nextCursor="two"),
                SimpleNamespace(tools=[declared(name) for name in ordered[1:]], nextCursor=None),
            ]
        )
    )
    manager.pool.sessions["threaddesk"] = session
    manager.pool.call = AsyncMock(
        return_value=CallToolResult(content=[], structuredContent={"ok": True})
    )
    return manager, session


def arguments(kind):
    if kind == "knowledge":
        return ThreadDeskKnowledgeInput(
            operation_id="original", action="record", id="thread", expected_revision=1, data={}
        )
    return ThreadDeskReadInput(tool="list_snapshots", arguments={"id": "thread"})


@pytest.mark.parametrize(
    "kind,name", [("read", "list_snapshots"), ("knowledge", "knowledge_manage")]
)
async def test_added_tool_on_existing_connection_is_discovered_before_dispatch(config, kind, name):
    manager, session = peer(config, BASE | {name}, BASE)
    args = arguments(kind)
    if kind == "knowledge":
        manager.pool.call.return_value = CallToolResult(
            content=[],
            structuredContent={
                "operation_id": manager.operation_id("local", "original"),
                "action": "record",
                "thread_id": "thread",
                "revision": 2,
                "deleted": False,
                "duplicate": False,
                "thread": {"id": "thread", "revision": 2},
            },
        )
    result = await manager.execute({"id": "task", "principal": "local"}, args, AsyncMock())
    assert result["success"]
    assert name in manager.available_tools
    assert manager.pool.call.await_count == 1
    assert session.list_tools.await_args_list[1].kwargs == {"cursor": "two"}


@pytest.mark.parametrize(
    "kind,name", [("read", "list_snapshots"), ("knowledge", "knowledge_manage")]
)
async def test_removed_tool_on_existing_connection_is_not_sent(config, kind, name):
    manager, _ = peer(config, BASE, BASE | {name})
    running = AsyncMock()
    with pytest.raises(BridgeError) as exc:
        await manager.execute({"id": "task", "principal": "local"}, arguments(kind), running)
    assert exc.value.code == "threaddesk_version"
    manager.pool.call.assert_not_awaited()
    running.assert_not_awaited()
    assert name not in manager.available_tools


async def test_refresh_does_not_retry_a_mutation_with_unknown_reply(config):
    manager, _ = peer(config, BASE | {"knowledge_manage"}, BASE)
    manager.pool.call.side_effect = BridgeError("peer_unknown", "Lost reply")
    with pytest.raises(UncertainExecution) as exc:
        await manager.execute(
            {"id": "task", "principal": "local"}, arguments("knowledge"), AsyncMock()
        )
    assert exc.value.code == "threaddesk_unknown"
    manager.pool.call.assert_awaited_once()


async def test_fresh_management_schema_still_rejects_before_mutation(config):
    manager, session = peer(config, BASE, BASE)
    session.list_tools.side_effect = None
    session.list_tools.return_value = SimpleNamespace(
        tools=[
            SimpleNamespace(
                name="thread_manage",
                inputSchema={
                    "oneOf": [
                        {
                            "properties": {
                                "action": {"const": "set_note"},
                                "data": {
                                    "type": "object",
                                    "properties": {"text": {"type": "string", "maxLength": 3}},
                                },
                            }
                        }
                    ]
                },
            )
        ],
        nextCursor=None,
    )
    running = AsyncMock()
    result = await manager.execute(
        {"id": "task", "principal": "local"},
        ThreadDeskManageInput(
            operation_id="original",
            action="set_note",
            id="thread",
            expected_revision=1,
            data={"text": "four"},
        ),
        running,
    )
    assert not result["success"] and result["evidence"]["request_sent"] is False
    assert result["value"]["error"]["details"]["limit"] == 3
    manager.pool.call.assert_not_awaited()
    running.assert_not_awaited()
