"""Routine liveness survives unavailable storage without promising admission."""

import sqlite3
from unittest.mock import AsyncMock, Mock

import pytest
from test_mcp import http_bridge  # noqa: F401 -- authenticated isolated HTTP fixture

from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool, Peer


class UnavailableDatabase:
    def __getattr__(self, name):
        raise sqlite3.OperationalError("test database unavailable")


def test_liveness_does_not_access_unavailable_storage(bridge, monkeypatch):
    def forbidden_detail():
        raise AssertionError("Routine liveness must not aggregate storage diagnostics")

    with monkeypatch.context() as patch:
        patch.setattr(bridge.store, "db", UnavailableDatabase())
        patch.setattr(bridge.outputs, "status", forbidden_detail)
        patch.setattr(bridge.diagnostics, "status", forbidden_detail)
        patch.setattr(bridge.autonext, "inspect", forbidden_detail)
        result = bridge.health("local", include_diagnostics=False)
        assert result["name"] == "KiraBridge" and result["runtime"]["instance_id"]
        assert result["dispatcher_active"] is False  # This fixture has no running workers.
        assert result["discovery"]["principal"] == "local"
        assert result["operations"] == {
            "protocol": 1,
            "status": "not_probed",
            "maintenance": None,
            "accepting_new_work": None,
        }
        assert result["output_history"]["status"] == "not_probed"
        assert result["diagnostics_storage"]["recording"] == "not_probed"
        assert result["autonext"]["state"] == "not_probed"
        assert result["health_detail"]["readiness"] == "not_checked"
        assert result["discovery"]["terminal_observation"]["freshness"] == "not_probed"
        with pytest.raises(sqlite3.OperationalError, match="test database unavailable"):
            bridge.health("local", include_diagnostics=True)


@pytest.mark.parametrize("include_diagnostics", [False, True])
@pytest.mark.parametrize("principal", ["unconfigured", "other"])
def test_liveness_and_details_require_current_health_grant(
    bridge, config, monkeypatch, principal, include_diagnostics
):
    config.principals["other"].capabilities.remove("bridge.health")
    maintenance = Mock(side_effect=AssertionError("Unauthorized storage access"))
    monkeypatch.setattr(bridge.store, "maintenance_state", maintenance)
    with pytest.raises(BridgeError) as denied:
        bridge.health(principal, include_diagnostics=include_diagnostics)
    assert denied.value.code == "forbidden"
    maintenance.assert_not_called()


def test_direct_health_keeps_explicit_storage_and_maintenance_details(bridge, monkeypatch):
    maintenance = Mock(return_value={"id": "test-maintenance", "state": "draining"})
    monkeypatch.setattr(bridge.store, "maintenance_state", maintenance)
    result = bridge.health("local")
    maintenance.assert_called_once_with()
    assert result["operations"]["maintenance"]["id"] == "test-maintenance"
    assert result["operations"]["accepting_new_work"] is False
    assert result["health_detail"]["included"] is True
    assert result["diagnostics_storage"]["recording"] == "available"
    assert result["output_history"].get("status") != "not_probed"
    assert result["autonext"].get("state") != "not_probed"


async def test_http_routine_health_skips_details_and_explicit_details_check_grant(
    http_bridge,  # noqa: F811 -- imported fixture
    monkeypatch,
):
    bridge, endpoint = http_bridge
    bridge.config.principals["local"].capabilities.append("session.inspect")
    bridge.config.principals["local"].approval_mode = "automatic"
    terminal = AsyncMock(return_value={"status": "available", "sessions": []})
    monkeypatch.setattr(bridge.terminal_queries, "execute", terminal)
    probes = {
        "maintenance": Mock(return_value={"id": "test-maintenance", "state": "draining"}),
        "output": Mock(return_value={"status": "test_output_detail"}),
        "diagnostics": Mock(return_value={"recording": "test_diagnostic_detail"}),
        "autonext": Mock(return_value={"state": "test_autonext_detail"}),
    }
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        await clients.list_tools("local")
        # Restrict the measured request; background workers retain their normal DB.
        with monkeypatch.context() as patch:
            patch.setattr(bridge.store, "maintenance_state", probes["maintenance"])
            patch.setattr(bridge.outputs, "status", probes["output"])
            patch.setattr(bridge.diagnostics, "status", probes["diagnostics"])
            patch.setattr(bridge.autonext, "inspect", probes["autonext"])
            health = (await clients.call("local", "bridge_health", {})).structuredContent
            assert health["dispatcher_active"] is True
            assert health["operations"]["accepting_new_work"] is None
            assert health["health_detail"]["included"] is False
            for probe in probes.values():
                probe.assert_not_called()

            details = (
                await clients.call("local", "bridge_health", {"include_diagnostics": True})
            ).structuredContent
            assert details["operations"]["accepting_new_work"] is False
            assert details["output_history"]["status"] == "test_output_detail"
            assert details["diagnostics_storage"]["recording"] == "test_diagnostic_detail"
            assert details["autonext"]["state"] == "test_autonext_detail"
            for probe in probes.values():
                probe.assert_called_once_with()
                probe.reset_mock()

            bridge.config.principals["local"].capabilities.remove("bridge.health")
            for arguments in (
                {},
                {"include_diagnostics": True},
                {"observe_terminals": True, "include_diagnostics": True},
            ):
                denied = (await clients.call("local", "bridge_health", arguments)).structuredContent
                assert denied["error"]["code"] == "forbidden"
            for probe in probes.values():
                probe.assert_not_called()
            terminal.assert_not_awaited()
