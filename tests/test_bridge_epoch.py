"""The passive monitor keeps fresh authorization/epochs with a small response."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.types import CallToolResult, Tool
from test_health_poll_audit import observed_pool
from test_mcp import http_bridge  # noqa: F401

from kirabridge.discovery import epoch, snapshot
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.proxy import DaemonConnection
from kirabridge.permissions import permission_revision


def test_light_epoch_matches_full_discovery_and_permissions_stay_fresh(bridge):
    full, light = snapshot(bridge, "local"), epoch(bridge, "local")
    for field in ("version", "instance_id", "revision", "principal", "permission_revision"):
        assert light[field] == full[field]
    assert light["platform_revision"] == full["platform"]["revision"]
    bridge.config.principals["local"].capabilities.remove("file.write")
    assert epoch(bridge, "local")["revision"] != light["revision"]
    assert epoch(bridge, "local")["revision"] == snapshot(bridge, "local")["revision"]


@pytest.mark.parametrize("change", ["instance", "platform", "sessions"])
def test_epoch_tracks_the_same_nonpermission_invalidations_as_full_snapshot(bridge, change):
    policy = bridge.config.principals["local"]
    policy.capabilities.append("session.inspect")
    policy.permission_level = "full"
    bridge.discovery_observations = {
        "local": {
            "revision": "first-session-epoch",
            "permission_revision": permission_revision(bridge.config),
            "status": "available",
            "sessions": [],
        }
    }
    before = epoch(bridge, "local")
    if change == "instance":
        bridge.runtime["instance_id"] = "changed-instance"
    elif change == "platform":
        bridge.macos.capability_probe.facts["os_version"] = "12.6"
    else:
        bridge.discovery_observations["local"]["revision"] = "new-session-epoch"
    after = epoch(bridge, "local")
    assert before["revision"] != after["revision"]
    assert after["revision"] == snapshot(bridge, "local")["revision"]


@pytest.mark.parametrize("advertise_epoch", [True, False])
async def test_proxy_monitor_prefers_epoch_and_falls_back_for_older_daemons(advertise_epoch):
    pool = MCPClientPool()
    names = ["bridge_health"] + (["bridge_epoch"] if advertise_epoch else [])
    session = SimpleNamespace(
        list_tools=AsyncMock(
            return_value=SimpleNamespace(
                tools=[Tool(name=name, inputSchema={"type": "object"}) for name in names],
                nextCursor=None,
            )
        ),
        call_tool=AsyncMock(return_value=CallToolResult(content=[], structuredContent={})),
    )
    pool.sessions["test"] = session
    pool.connection_ids["test"] = "generation"
    connection = DaemonConnection(pool, Peer("test"))
    await connection.poll_health()
    expected = "bridge_epoch" if advertise_epoch else "bridge_health"
    session.call_tool.assert_awaited_once_with(expected, {})
    if not advertise_epoch:
        session.list_tools.return_value.tools.append(
            Tool(name="bridge_epoch", inputSchema={"type": "object"})
        )
        pool.catalog_dirty.add("test")
        await connection.poll_health()
        assert session.call_tool.await_args.args == ("bridge_epoch", {})


async def test_epoch_stable_noise_and_changed_generation_keep_existing_audit_semantics():
    pool, session, records = observed_pool()
    await pool.call("daemon", "bridge_epoch", {}, routine_health=True)
    await pool.call("daemon", "bridge_epoch", {}, routine_health=True)
    assert len(records) == 2
    session.data["discovery"]["revision"] = "changed-grant"
    await pool.call("daemon", "bridge_epoch", {}, routine_health=True)
    assert len(records) == 4
    session.is_error = True
    await pool.call("daemon", "bridge_epoch", {}, routine_health=True)
    session.is_error = False
    await pool.call("daemon", "bridge_epoch", {}, routine_health=True)
    assert len(records) == 8


async def test_real_http_epoch_is_small_fresh_and_requires_health_permission(
    http_bridge,  # noqa: F811
):
    bridge, endpoint = http_bridge
    async with MCPClientPool() as pool:
        await pool.connect(Peer("test", url=endpoint, token="local-test-" + "a" * 40))
        health = await pool.call("test", "bridge_health", {})
        light = await pool.call("test", "bridge_epoch", {})
        assert light.structuredContent["dispatcher_active"]
        assert (
            health.structuredContent["discovery"]["revision"]
            == light.structuredContent["discovery"]["revision"]
        )
        assert len(light.model_dump_json()) < len(health.model_dump_json()) / 10
        old_epoch = light.structuredContent["discovery"]["revision"]
        bridge.config.principals["local"].capabilities.remove("file.write")
        changed = await pool.call("test", "bridge_epoch", {})
        assert changed.structuredContent["discovery"]["revision"] != old_epoch
        bridge.config.principals["local"].capabilities.remove("bridge.health")
        refused = await pool.call("test", "bridge_epoch", {})
        assert refused.structuredContent["error"]["code"] == "forbidden"
        assert "capabilities" not in json.dumps(refused.structuredContent)
