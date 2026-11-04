"""New Windows contracts over real authenticated HTTP; backend effects are injected."""

import pytest
from test_mcp import http_bridge  # noqa: F401 -- authenticated local protocol fixture
from test_windows_keyboard_manager import TARGET as KEYBOARD_TARGET
from test_windows_keyboard_manager import Backend as KeyboardBackend
from test_windows_window_manager import TARGET as WINDOW_TARGET
from test_windows_window_manager import Backend as WindowBackend

from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.windows_keyboard import WindowsKeyboardManager
from kirabridge.windows_windows import WindowsWindowManager


@pytest.mark.parametrize(
    "operation,dependency,arguments",
    [
        (
            "windows.keyboard.shortcut",
            "windows.keyboard.inspect",
            {"target": KEYBOARD_TARGET.to_wire(), "key": "a", "modifiers": ["control"]},
        ),
        (
            "windows.window.control",
            "windows.window.list",
            {"target": WINDOW_TARGET.to_wire(), "action": "maximize"},
        ),
    ],
)
async def test_windows_contract_http_dispatch_and_authorization_before_persistence(
    http_bridge,  # noqa: F811 -- pytest fixture injection
    operation,
    dependency,
    arguments,
):
    bridge, endpoint = http_bridge
    keyboard, windows = KeyboardBackend(), WindowBackend()
    bridge.windows_keyboard = WindowsKeyboardManager(
        bridge.security.authorize,
        bridge.desktop_input,
        backend_factory=lambda: keyboard,
        host="win32",
    )
    bridge.windows_windows = WindowsWindowManager(
        bridge.security.authorize,
        bridge.desktop_input,
        backend_factory=lambda: windows,
        host="win32",
    )
    policy = bridge.config.principals["local"]
    policy.approval_mode = "automatic"
    requested = ["windows.keyboard.shortcut", "windows.window.list", "windows.window.control"]
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        catalog = (
            await clients.call("local", "operation_catalog", {"operations": requested})
        ).structuredContent
        assert set(catalog["operations"]) == set(requested)
        assert all(row["platform"]["available"] for row in catalog["operations"].values())
        assert not windows.effects and not keyboard.sent  # discovery never causes native effects
        request = {
            "task_id": "desktop-http-once",
            "idempotency_key": "desktop-http-once",
            "operation": operation,
            "arguments": arguments,
        }
        task = (await clients.call("local", "task_request", {"request": request})).structuredContent
        assert task["state"] == "completed", task
        again = (
            await clients.call("local", "task_request", {"request": request})
        ).structuredContent
        assert again["id"] == task["id"]
        assert len(windows.effects) + len(keyboard.sent) == 1
        count = bridge.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        policy.capabilities.remove(dependency)
        request["task_id"] = request["idempotency_key"] = "desktop-http-refused"
        refused = (
            await clients.call("local", "task_request", {"request": request})
        ).structuredContent
        assert refused["error"]["code"] == "forbidden", refused
        assert bridge.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == count
        assert len(windows.effects) + len(keyboard.sent) == 1
