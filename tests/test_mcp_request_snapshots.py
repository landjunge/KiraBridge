"""Common tools reuse request facts while refreshing permissions on every request."""

from unittest.mock import AsyncMock

from test_mcp import http_bridge  # noqa: F401 -- real authenticated HTTP fixture

from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool, Peer


def observed_metadata(bridge, monkeypatch):
    calls = []

    def metadata():
        calls.append(True)
        return {"available": True, "keyboard_protocol": 1, "revision": "test-native"}

    bridge.macos.capability_probe.facts.update(platform="darwin", os_version="15.7.4")
    monkeypatch.setattr(bridge.macos.capability_probe, "native_metadata", metadata)
    terminal = AsyncMock(return_value={"status": "available", "sessions": []})
    monkeypatch.setattr(bridge.terminal_queries, "execute", terminal)
    return calls, terminal


async def test_health_uses_one_snapshot_and_only_explicit_terminal_observation(
    http_bridge,  # noqa: F811 -- imported fixture
    monkeypatch,
):
    bridge, endpoint = http_bridge
    policy = bridge.config.principals["local"]
    policy.capabilities += ["session.inspect"]
    policy.approval_mode = "automatic"
    calls, terminal = observed_metadata(bridge, monkeypatch)
    async with MCPClientPool() as pool:
        await pool.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        await pool.list_tools("local")  # Warm SDK validation, outside the measured request.
        calls.clear()
        health = (await pool.call("local", "bridge_health", {})).structuredContent
        assert len(calls) == 1 and health["discovery"]["principal"] == "local"
        terminal.assert_not_awaited()
        calls.clear()
        live = (
            await pool.call("local", "bridge_health", {"observe_terminals": True})
        ).structuredContent
        assert len(calls) == 2
        terminal.assert_awaited_once_with("local", "session.catalog", {})
        assert live["discovery"]["terminal_observation"]["freshness"] == "fresh"
        assert not bridge.store.db.execute("SELECT 1 FROM tasks").fetchone()


async def test_operation_catalog_snapshot_count_is_constant_and_rights_stay_fresh(
    http_bridge,  # noqa: F811 -- imported fixture
    monkeypatch,
):
    bridge, endpoint = http_bridge
    policy = bridge.config.principals["local"]
    policy.capabilities += ["session.inspect", "keyboard.execute"]
    policy.approval_mode = "automatic"
    calls, terminal = observed_metadata(bridge, monkeypatch)
    async with MCPClientPool() as pool:
        await pool.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        await pool.list_tools("local")
        calls.clear()
        first = (await pool.call("local", "operation_catalog", {})).structuredContent
        assert len(first["operations"]) > 30
        assert "file.write" in first["operations"] and "keyboard.key" in first["operations"]
        assert len(calls) == 2  # One platform inventory and one final discovery snapshot.
        terminal.assert_not_awaited()
        assert first["discovery"]["terminal_observation"]["freshness"] == "not_probed"
        old_revision = first["discovery"]["permission_revision"]
        policy.capabilities.remove("file.write")
        policy.capabilities.remove("keyboard.execute")
        calls.clear()
        changed = (await pool.call("local", "operation_catalog", {})).structuredContent
        assert "file.write" not in changed["operations"]
        assert "keyboard.key" not in changed["operations"]
        assert changed["discovery"]["permission_revision"] != old_revision
        assert len(calls) == 2
        terminal.assert_not_awaited()
        assert not bridge.store.db.execute("SELECT 1 FROM tasks").fetchone()


async def test_operation_catalog_explicit_terminal_observation_preserves_failures(
    http_bridge,  # noqa: F811 -- imported fixture
    monkeypatch,
):
    bridge, endpoint = http_bridge
    policy = bridge.config.principals["local"]
    policy.capabilities += ["session.inspect"]
    policy.approval_mode = "automatic"
    _, terminal = observed_metadata(bridge, monkeypatch)
    async with MCPClientPool() as pool:
        await pool.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        fresh = (
            await pool.call("local", "operation_catalog", {"observe_terminals": True})
        ).structuredContent
        terminal.assert_awaited_once_with("local", "session.catalog", {})
        assert fresh["discovery"]["terminal_observation"]["freshness"] == "fresh"
        cached = (await pool.call("local", "operation_catalog", {})).structuredContent
        assert cached["discovery"]["terminal_observation"]["freshness"] == "cached"
        assert not cached["discovery"]["terminal_observation"]["usable_for_input"]
        assert terminal.await_count == 1
        terminal.side_effect = BridgeError("terminal_read_busy", "Owned test refusal")
        refused = (
            await pool.call("local", "operation_catalog", {"observe_terminals": True})
        ).structuredContent
        observation = refused["discovery"]["terminal_observation"]
        assert observation["freshness"] == "fresh"
        assert observation["status"] == observation["error"]["code"] == "terminal_read_busy"
        assert not observation["usable_for_input"]
