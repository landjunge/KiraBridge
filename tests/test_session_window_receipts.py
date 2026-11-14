"""Creation receipts survive a later uncertain physical-window result."""

import sys
from unittest.mock import AsyncMock

import pytest
from conftest import request, submit

from kirabridge.bridge_core.models import UncertainExecution


@pytest.mark.parametrize("operation", ["session.open", "terminal.visible"])
@pytest.mark.parametrize("full_binding", [False, True])
async def test_window_creation_receipt_is_durable_before_unknown_without_replay(
    bridge, config, monkeypatch, operation, full_binding
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
    bound = {
        **receipt,
        "physical_window": {"proof": "synthetic native peer"},
        "separate_window": True,
    }
    calls = []

    async def opened_then_unknown(principal, args, *, task_id, on_created, on_bound):
        calls.append(task_id)
        assert callable(on_bound)
        await on_created(receipt)
        if full_binding:
            await on_bound(bound)
            # Exercise the actual injected Core callback, not merely its shape.
            observed = bridge.store.get(task_id, principal, resolve_output=False)
            assert observed["state"] == (
                "accepted" if operation == "terminal.visible" else "running"
            )
            assert observed["evidence"] == {
                "evidence_type": "session_window_bound",
                "creation_receipt": bound,
                "automatic_retry": False,
            }
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
        bindings = [
            event["evidence"]
            for event in events
            if event["evidence"].get("evidence_type") == "session_window_bound"
        ]
        assert bindings == (
            [
                {
                    "evidence_type": "session_window_bound",
                    "creation_receipt": bound,
                    "automatic_retry": False,
                }
            ]
            if full_binding
            else []
        )
        assert bridge.submit("local", value, "already-consumed")["state"] == "unknown"
        assert calls == [value.task_id]
    finally:
        await bridge.tasks.stop()


async def test_pending_session_handle_is_unknown_not_completed(bridge, config, monkeypatch):
    monkeypatch.setattr(bridge, "platform_operation", lambda *args: None)
    bridge.tasks.preflight = None
    config.principals["local"].capabilities.append("session.inspect")
    pending = {"tty": "/dev/ttys099", "session_handle_pending": True, "agent_processed": False}
    calls = []

    async def pending_open(principal, args, *, task_id, on_created, on_bound):
        calls.append(task_id)
        return pending

    monkeypatch.setattr(bridge.sessions, "open", pending_open)
    value = request("session.open", {"cwd": config.principals["local"].roots[0]})
    submit(bridge, value)
    await bridge.tasks.start()
    try:
        final = await bridge.tasks.wait("local", value.task_id)
        assert final["state"] == "unknown"
        assert final["error"]["code"] == "session_handle_pending"
        assert final["result"]["session_handle_pending"] is True
        assert final["evidence"] == {
            "reason": "session_handle_pending",
            "side_effect_possible": True,
            "automatic_retry": False,
        }
        states = [event["state"] for event in bridge.events("local", value.task_id)["events"]]
        assert states[-1] == "unknown" and "completed" not in states
        assert calls == [value.task_id]
    finally:
        await bridge.tasks.stop()
