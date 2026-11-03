"""Creation receipts survive a later uncertain physical-window result."""

import sys
from unittest.mock import AsyncMock

import pytest
from conftest import request, submit

from kirabridge.bridge_core.models import UncertainExecution


@pytest.mark.parametrize("operation", ["session.open", "terminal.visible"])
async def test_window_creation_receipt_is_durable_before_unknown_without_replay(
    bridge, config, monkeypatch, operation
):
    # Exercise the real dispatcher and durable event store, without any OS/UI.
    monkeypatch.setattr(bridge, "platform_operation", lambda *args: None)
    bridge.tasks.preflight = None
    config.principals["local"].capabilities.append("session.inspect")
    monkeypatch.setattr(bridge.sessions, "catalog", AsyncMock(return_value={"sessions": []}))
    receipt = {
        "opened": True,
        "tty": "/dev/ttys099",
        "script_window_id": 1001,
        "creation_nonce": "owned-window-fixture",
    }
    calls = []

    async def opened_then_unknown(principal, args, *, task_id, on_created):
        calls.append(task_id)
        await on_created(receipt)
        raise UncertainExecution("visible_window_unknown", "Created; physical proof unavailable")

    monkeypatch.setattr(bridge.sessions, "open", opened_then_unknown)
    arguments = {"cwd": config.principals["local"].roots[0]}
    if operation == "terminal.visible":
        arguments["argv"] = [sys.executable, "-c", "pass"]
    value = request(operation, arguments)
    submit(bridge, value)
    await bridge.tasks.start()
    try:
        final = await bridge.tasks.wait("local", value.task_id)
        assert final["state"] == "unknown"
        assert final["error"]["code"] == "visible_window_unknown"
        events = bridge.events("local", value.task_id)["events"]
        creations = [
            event["evidence"]
            for event in events
            if event["evidence"].get("evidence_type") == "session_window_created"
        ]
        assert creations == [
            {
                "evidence_type": "session_window_created",
                "creation_receipt": receipt,
                "automatic_retry": False,
            }
        ]
        assert bridge.submit("local", value, "already-consumed")["state"] == "unknown"
        assert calls == [value.task_id]
    finally:
        await bridge.tasks.stop()
