"""Clipboard MCP routing tests use only a fake executor, never the real clipboard."""

import asyncio

import pytest
from test_mcp import http_bridge  # noqa: F401

from kirabridge.bridge_core.models import TaskRequest
from kirabridge.mcp_gateway.client import MCPClientPool, Peer


def tool_arguments(tool, task_id="clipboard-inline"):
    return {
        "task_id": task_id,
        "idempotency_key": task_id,
        **({"max_bytes": 123} if tool == "clipboard_read" else {"text": "fake clipboard text"}),
    }


def request_for(tool, arguments):
    return TaskRequest(
        task_id=arguments["task_id"],
        idempotency_key=arguments["idempotency_key"],
        operation=tool.replace("_", "."),
        arguments={
            key: value
            for key, value in arguments.items()
            if key not in {"task_id", "idempotency_key"}
        },
    )


@pytest.mark.parametrize("tool", ["clipboard_read", "clipboard_write"])
@pytest.mark.parametrize("manual", [False, True])
async def test_clipboard_wrappers_return_inline_and_preserve_approval_args_and_idempotency(
    http_bridge,  # noqa: F811
    config,
    monkeypatch,
    tool,
    manual,
):
    bridge, endpoint = http_bridge
    config.principals["local"].approval_mode = "manual" if manual else "automatic"
    calls = []

    async def fake_executor(task, running, progress):
        calls.append((task["id"], task["operation"], task["args"]))
        await running({"evidence_type": "mock_clipboard_only"})
        await asyncio.sleep(0.02)
        return {"text": "mock result", "scope": "test fake executor"}

    monkeypatch.setattr(bridge.tasks, "executor", fake_executor)
    monkeypatch.setattr(bridge.tasks, "preflight", None)
    arguments = tool_arguments(tool)
    expected = request_for(tool, arguments)
    if manual:
        arguments["approval"] = bridge.security.grant("local", expected)
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        first = (await clients.call("local", tool, arguments)).structuredContent
        duplicate = (
            await clients.call("local", tool, {**arguments, "approval": ""})
        ).structuredContent
    assert first["state"] == duplicate["state"] == "completed"
    assert first["id"] == duplicate["id"] == expected.task_id
    assert first["result"]["text"] == "mock result"
    assert calls == [(expected.task_id, expected.operation, expected.arguments)]
    assert not {"lease_owner", "lease_until", "idem"} & first.keys()
    assert bridge.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


@pytest.mark.parametrize("tool", ["clipboard_read", "clipboard_write"])
async def test_clipboard_write_only_identity_is_refused_before_admission(
    http_bridge,  # noqa: F811
    config,
    monkeypatch,
    tool,
):
    bridge, endpoint = http_bridge
    config.principals["local"].approval_mode = "automatic"
    config.principals["local"].capabilities.remove("task.read")
    calls = []

    async def forbidden_executor(*args):
        calls.append(True)
        raise AssertionError("A refused task must never reach any clipboard executor")

    monkeypatch.setattr(bridge.tasks, "executor", forbidden_executor)
    monkeypatch.setattr(bridge.tasks, "preflight", None)
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        result = (await clients.call("local", tool, tool_arguments(tool))).structuredContent
    assert result["error"]["code"] == "forbidden"
    assert not calls and bridge.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


@pytest.mark.parametrize("tool", ["clipboard_read", "clipboard_write"])
async def test_clipboard_wrappers_preserve_validation_error_envelope(
    http_bridge,  # noqa: F811
    config,
    monkeypatch,
    tool,
):
    bridge, endpoint = http_bridge
    config.principals["local"].approval_mode = "automatic"

    async def forbidden_executor(*args):
        raise AssertionError("Invalid task IDs must never reach a clipboard executor")

    monkeypatch.setattr(bridge.tasks, "executor", forbidden_executor)
    monkeypatch.setattr(bridge.tasks, "preflight", None)
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        result = (
            await clients.call("local", tool, tool_arguments(tool, task_id="invalid task id"))
        ).structuredContent
    assert result == {"error": {"code": "invalid_arguments", "message": "Invalid tool arguments"}}
    assert bridge.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
