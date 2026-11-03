"""Shortcut schema and authorized read dispatch; no GUI, scans or events."""

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from kirabridge.bridge_core.models import BridgeError
from kirabridge.keyboard_models import KeyboardShortcutsInput
from kirabridge.operations import OPERATIONS
from kirabridge.system_operations import SYSTEM_READ_OPERATIONS

TARGET = {"pid": 321, "expected_started_at": 1700000000.125}


@pytest.mark.parametrize(
    "change",
    [
        {"offset": 1},
        {"limit": 251},
        {"offset": 2001},
        {"limit": True},
        {"expected_revision": "wrong"},
        {"open_menus": True},
    ],
)
def test_shortcut_pages_require_bounded_observed_context(change):
    with pytest.raises(ValidationError):
        KeyboardShortcutsInput(**{**TARGET, **change})


async def test_shortcut_discovery_uses_authorized_native_read_without_desktop_lease(bridge):
    operation = "keyboard.shortcuts.discover"
    bridge.config.principals["local"].capabilities.append("keyboard.shortcuts.read")
    bridge.macos.capability_probe.facts.update(platform="darwin", os_version="15.7.4")
    bridge.macos.capability_probe.native_metadata = lambda: {
        "available": True,
        "keyboard_protocol": 1,
    }

    async def read(name, arguments, *, principal, before_send):
        assert name == operation and principal == "local"
        assert arguments == {**TARGET, "limit": 100, "offset": 0}
        assert not bridge.sessions.lock.locked()
        before_send()
        return {"coverage": "partial", "effect": "none"}

    bridge.system_modules.transport.request = AsyncMock(side_effect=read)
    result = await bridge.execute(
        {"id": "menu-read", "principal": "local", "operation": operation, "args": TARGET},
        AsyncMock(),
        AsyncMock(),
    )
    assert result["effect"] == "none"
    assert operation in SYSTEM_READ_OPERATIONS
    assert OPERATIONS[operation].capability == "keyboard.shortcuts.read"
    assert OPERATIONS[operation].effect == "read"


async def test_keyboard_execution_grant_does_not_authorize_shortcut_discovery(bridge):
    policy = bridge.config.principals["local"]
    policy.capabilities = ["keyboard.execute", "keyboard.inspect"]
    policy.permission_level = "full"
    bridge.macos.capability_probe.facts.update(platform="darwin", os_version="15.7.4")
    bridge.macos.capability_probe.native_metadata = lambda: {
        "available": True,
        "keyboard_protocol": 1,
    }
    bridge.system_modules.transport.request = AsyncMock()
    with pytest.raises(BridgeError, match="Capability not granted") as denied:
        await bridge.execute(
            {
                "id": "menu-denied",
                "principal": "local",
                "operation": "keyboard.shortcuts.discover",
                "args": TARGET,
            },
            AsyncMock(),
            AsyncMock(),
        )
    assert denied.value.code == "forbidden"
    bridge.system_modules.transport.request.assert_not_awaited()
