from unittest.mock import AsyncMock

import pytest

from kirabridge.bridge_core.models import BridgeError


@pytest.mark.parametrize(
    "operation,arguments,expected",
    [
        ("session.catalog", {}, None),
        ("platform.status", {}, None),
        ("clipboard.info", {}, None),
        ("file.read", {"path": "/private-fixture"}, "file.read"),
        ("session.read", {"pane_id": "%4"}, None),
        ("session.read", {"pane_id": "terminal:12:ttys005"}, "session.read"),
        ("terminal.execute", {"background": True}, None),
    ],
)
def test_routing_uses_host_facts_without_discovery_io(
    bridge, monkeypatch, operation, arguments, expected
):
    bridge.macos.capability_probe.facts["platform"] = "darwin"

    def forbidden_snapshot():
        raise AssertionError("Routing must not read/hash the native app or perform discovery")

    monkeypatch.setattr(bridge.macos, "snapshot", forbidden_snapshot)
    assert bridge.platform_operation(operation, arguments, "local") == expected


async def test_fast_routing_still_requires_fresh_provider_check(bridge, monkeypatch):
    bridge.macos.capability_probe.facts["platform"] = "darwin"
    denied = BridgeError("macos_permission_denied", "isolated fresh provider denial")
    checks = []

    def require(operation, **kwargs):
        checks.append(operation)
        raise denied

    monkeypatch.setattr(bridge.macos, "require", require)
    leaf = AsyncMock()
    monkeypatch.setattr(bridge, "_execute_operation", leaf)
    task = {"operation": "file.read", "args": {"path": "/private-fixture"}, "principal": "local"}
    with pytest.raises(BridgeError) as error:
        await bridge.execute(task, AsyncMock(), AsyncMock())
    assert error.value is denied
    assert checks == ["file.read"]
    leaf.assert_not_awaited()


def test_invalid_token_in_one_principal_does_not_break_valid_authentication(bridge, monkeypatch):
    bridge.config.principals["local"].token_env = "KB_REVIEW_INVALID_TOKEN"
    bridge.config.principals["other"].token_env = "KB_REVIEW_VALID_TOKEN"
    monkeypatch.setenv("KB_REVIEW_INVALID_TOKEN", "é" * 40)
    monkeypatch.setenv("KB_REVIEW_VALID_TOKEN", "v" * 40)
    assert bridge.security.authenticate("v" * 40) == "other"


def test_network_validation_rejects_non_ascii_bearer_configuration(config, monkeypatch):
    config.principals["local"].token_env = "KB_REVIEW_INVALID_TOKEN"
    monkeypatch.setenv("KB_REVIEW_INVALID_TOKEN", "é" * 40)
    with pytest.raises(BridgeError) as error:
        config.validate_network()
    assert error.value.code == "auth_config"


def test_non_ascii_direct_authentication_is_a_typed_denial(bridge, monkeypatch):
    bridge.config.principals["local"].token_env = "KB_REVIEW_VALID_TOKEN"
    monkeypatch.setenv("KB_REVIEW_VALID_TOKEN", "v" * 40)
    with pytest.raises(BridgeError) as error:
        bridge.security.authenticate("é" * 40)
    assert error.value.code == "unauthorized"
