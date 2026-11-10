"""Durable dynamic-tool outcomes and fresh catalogs survive isolated restarts.

Only synthetic peer transports and temporary SQLite/configuration are used.
No operator ThreadDesk workspace, CLI, GUI or production service is contacted.
"""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.types import CallToolResult

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import ThreadDeskConfig
from kirabridge.bridge_core.models import BridgeError
from kirabridge.threaddesk_dynamic import call, catalog


def declared(name, *, readonly=False, revision=False):
    properties = {"id": {"type": "string"}}
    if revision:
        properties["revision"] = {"type": "integer"}
    return SimpleNamespace(
        name=name,
        description="Synthetic peer contract",
        annotations=SimpleNamespace(
            readOnlyHint=readonly, destructiveHint=False, openWorldHint=False
        ),
        inputSchema={
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": list(properties),
        },
    )


def configured(config):
    config.threaddesk.enabled = True
    config.threaddesk.command = sys.executable
    config.threaddesk.dynamic_read_proxy = False
    config.threaddesk.dynamic_tool_proxy = True
    config.threaddesk.workspace = config.principals["local"].roots[0]
    config.threaddesk.timeout = 2
    for policy in config.principals.values():
        policy.permission_level = "full"
    return config


def fake_peer(bridge, tools, effect):
    bridge.threaddesk.connect = AsyncMock()
    bridge.threaddesk.pool.list_tools = AsyncMock(side_effect=lambda *_: list(tools))
    bridge.threaddesk.pool.call = AsyncMock(side_effect=effect)
    return bridge.threaddesk.pool


def result(value):
    return CallToolResult(content=[], structuredContent=value)


def test_full_proxy_opt_in_survives_config_serialization_without_enabling_legacy_reads():
    initial = ThreadDeskConfig(enabled=True, dynamic_tool_proxy=True)
    reloaded = ThreadDeskConfig.model_validate_json(initial.model_dump_json())
    assert reloaded.enabled and reloaded.dynamic_tool_proxy
    assert not reloaded.dynamic_read_proxy
    assert not ThreadDeskConfig().dynamic_tool_proxy


async def test_completed_mutation_and_changed_payload_after_restart_never_reexecute(config):
    configured(config)
    tools = [declared("new_writer")]
    effects = []

    async def effect(peer, name, arguments, **kwargs):
        effects.append((name, dict(arguments)))
        return result({"receipt": "synthetic", "number": len(effects)})

    async with Bridge(config) as first:
        fake_peer(first, tools, effect)
        original = await call(first, "local", "new_writer", {"id": "one"}, "stable-operation")
        assert original["success"] and original["task"]["attempt"] == 1
        original_task = original["task"]["id"]
    # Simulate an updated peer adding a tool while KiraBridge is restarted.
    tools.append(declared("newly_installed_reader", readonly=True))
    async with Bridge(config) as reopened:
        fake_peer(reopened, tools, effect)
        names = {item["name"] for item in (await catalog(reopened, "local"))["tools"]}
        assert names == {"new_writer", "newly_installed_reader"}
        duplicate = await call(reopened, "local", "new_writer", {"id": "one"}, "stable-operation")
        assert duplicate["task"] == original["task"]
        assert duplicate["value"] == original["value"]
        with pytest.raises(BridgeError):
            await call(reopened, "local", "new_writer", {"id": "changed"}, "stable-operation")
        assert reopened.task("local", original_task)["state"] == "completed"
    assert effects == [("new_writer", {"id": "one"})]


@pytest.mark.parametrize("failure", ["transport", "peer_error"])
async def test_lost_mutation_reply_remains_unknown_across_restart(config, failure):
    configured(config)
    tools = [declared("new_writer")]
    effects = []

    async def lost_reply(peer, name, arguments, **kwargs):
        effects.append(dict(arguments))
        if failure == "peer_error":
            # A generic remote error can follow a partial effect; it is not a
            # transactional no-effect receipt from a typed adapter.
            return CallToolResult(
                content=[],
                structuredContent={"code": "revision_conflict", "details": {}},
                isError=True,
            )
        # Real MCPClientPool reports a timed-out/lost response as BridgeError.
        raise BridgeError("peer_unknown", "Synthetic lost response after effect")

    async with Bridge(config) as first:
        fake_peer(first, tools, lost_reply)
        uncertain = await call(first, "local", "new_writer", {"id": "one"}, "lost-response")
        assert not uncertain["success"] and uncertain["task"]["state"] == "unknown"
        assert uncertain["task"]["attempt"] == 1
    async with Bridge(config) as reopened:
        pool = fake_peer(reopened, tools, lost_reply)
        same = await call(reopened, "local", "new_writer", {"id": "one"}, "lost-response")
        assert same["task"] == uncertain["task"]
        pool.call.assert_not_awaited()
    assert effects == [{"id": "one"}]


async def test_dispatch_rejects_contract_update_before_remote_write(config):
    configured(config)
    old = declared("new_writer")
    updated = declared("new_writer", revision=True)
    async with Bridge(config) as instance:
        pool = fake_peer(instance, [old], AsyncMock())
        pool.list_tools.side_effect = [[old], [updated]]
        outcome = await call(instance, "local", "new_writer", {"id": "one"}, "contract-update")
        task = instance.task("local", outcome["task"]["id"])
        assert task["state"] == "failed"
        assert task["error"]["code"] == "threaddesk_contract_changed"
        pool.call.assert_not_awaited()


async def test_dispatcher_shutdown_after_remote_start_never_replays_on_restart(config):
    configured(config)
    tools = [declared("new_writer")]
    entered = asyncio.Event()
    effects = []

    async def waiting_peer(peer, name, arguments, **kwargs):
        effects.append(dict(arguments))
        entered.set()
        await asyncio.Future()

    caller = None
    async with Bridge(config) as first:
        fake_peer(first, tools, waiting_peer)
        caller = asyncio.create_task(
            call(first, "local", "new_writer", {"id": "one"}, "dispatcher-stop")
        )
        try:
            await asyncio.wait_for(entered.wait(), 1)
        finally:
            # Cancelling a client wait is not authority to replay the worker.
            caller.cancel()
            await asyncio.gather(caller, return_exceptions=True)
    async with Bridge(config) as reopened:
        pool = fake_peer(reopened, tools, waiting_peer)
        same = await call(reopened, "local", "new_writer", {"id": "one"}, "dispatcher-stop")
        assert same["task"]["state"] == "unknown" and same["task"]["attempt"] == 1
        pool.call.assert_not_awaited()
    assert effects == [{"id": "one"}]


def manage_contract():
    properties = {
        name: {"type": kind}
        for name, kind in (
            ("operation_id", "string"),
            ("action", "string"),
            ("id", "string"),
            ("expected_revision", "integer"),
            ("data", "object"),
        )
    }
    return [
        SimpleNamespace(
            name="thread_manage",
            description="Synthetic peer contract",
            annotations=SimpleNamespace(
                readOnlyHint=False, destructiveHint=False, openWorldHint=False
            ),
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": properties,
                "required": ["operation_id", "action", "expected_revision", "data"],
            },
        ),
        SimpleNamespace(
            name="thread_operation_status",
            description="Synthetic peer contract",
            annotations=SimpleNamespace(
                readOnlyHint=True, destructiveHint=False, openWorldHint=False
            ),
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"operation_id": {"type": "string"}},
                "required": ["operation_id"],
            },
        ),
    ]


@pytest.mark.parametrize("stored", [True, False])
async def test_lost_thread_manage_reply_is_reconciled_by_operation_id_not_resent(config, stored):
    configured(config)
    effects, reads = [], []
    arguments = {
        "operation_id": "note-1",
        "action": "set_note",
        "id": "t1",
        "expected_revision": 3,
        "data": {"text": "x"},
    }

    async def peer(_, name, values, **kwargs):
        if name == "thread_operation_status":
            reads.append(values)
            receipt = {"operation_id": "note-1", "thread_id": "t1", "revision": 4}
            return result({"found": stored, "result": receipt if stored else None})
        effects.append(values)
        raise BridgeError("peer_unknown", "Synthetic late reply after the effect")

    async with Bridge(config) as bridge:
        fake_peer(bridge, manage_contract(), peer)
        outcome = await call(bridge, "local", "thread_manage", arguments, "kb-note-1")
    assert effects == [arguments]
    assert reads == [{"operation_id": "note-1"}]
    if stored:
        assert outcome["success"] and outcome["task"]["state"] == "completed"
        assert outcome["value"]["reconciled"] and outcome["value"]["receipt"]["revision"] == 4
        assert outcome["effect_confirmed"] is True
    else:
        assert not outcome["success"] and outcome["task"]["state"] == "unknown"
