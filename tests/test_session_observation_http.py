"""Persist native pre-input observation failures through the authenticated API."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import request
from test_mcp import http_bridge  # noqa: F401 -- existing private HTTP Core fixture

from kirabridge.mcp_gateway.client import MCPClientPool, Peer


@pytest.mark.parametrize("phase", ["native_process_catalog", "native_process_identity"])
async def test_http_native_timeout_is_durable_failed_without_input_or_replay(
    http_bridge,  # noqa: F811 -- existing private HTTP Core fixture
    monkeypatch,
    phase,
):
    import kirabridge.platform_adapters.terminal_app as module

    bridge, endpoint = http_bridge
    policy = bridge.config.principals["local"]
    policy.capabilities += ["session.inspect"]
    policy.permission_level = "full"
    bridge.macos.capability_probe.facts.update(platform="darwin", os_version="15.7.4")
    bridge.macos.capability_probe.executable = lambda path: True
    bridge.macos.permission_probe.reader = lambda resource: {
        "state": "unknown",
        "method": "isolated_test",
    }
    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="darwin", exc_info=sys.exc_info))
    transport = bridge.sessions.terminal_app
    transport.native = AsyncMock(return_value=[])
    if phase == "native_process_identity":
        transport.catalog = AsyncMock(
            return_value=[
                {
                    "pane_id": "terminal:123:ttys004",
                    "expected_pid": 345,
                    "tty": "/dev/ttys004",
                    "window_id": 123,
                    "transport": "terminal_app",
                    "busy": False,
                    "processes": [{"pid": 345, "ppid": 1, "name": "zsh", "image": "/bin/zsh"}],
                }
            ]
        )
    monkeypatch.setattr(bridge.sessions, "direct", lambda principal: True)
    transport.send_confirmed = AsyncMock()
    transport.send = AsyncMock()
    transport.insert = AsyncMock()
    transport.press_return = AsyncMock()
    bridge.sessions.tmux.catalog = AsyncMock(side_effect=AssertionError("unrelated transport"))
    process = SimpleNamespace(communicate=AsyncMock(side_effect=TimeoutError()), returncode=None)
    if phase == "native_process_catalog":
        process.stdout = SimpleNamespace(read=AsyncMock(side_effect=TimeoutError()))
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(module, "reap_process", AsyncMock())
    value = request(
        "session.input",
        {
            "pane_id": "terminal:123:ttys004",
            "expected_pid": 345,
            "text": "harmless literal",
            "require_idle": True,
        },
        task_id="native-observation-timeout",
    )

    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        response = (
            await clients.call("local", "action_request", {"request": value.model_dump()})
        ).structuredContent
        assert response.get("id") == value.task_id, response
        task = (
            await clients.call("local", "task_get", {"task_id": value.task_id})
        ).structuredContent

    assert task["state"] == "failed", task
    assert task["error"]["code"] == "session_observation_timeout"
    provider_error = {"phase": phase, "reason": "timeout"}
    if phase == "native_process_catalog":
        provider_error.update(
            stage="stdout_read", stdout_bytes=0, stdout_eof=False, exit_status=None
        )
        actual_provider_error = task["evidence"]["provider_error"]
        assert actual_provider_error.keys() == provider_error.keys() | {"elapsed_ms", "cleanup_ms"}
        for field in ("elapsed_ms", "cleanup_ms"):
            assert type(actual_provider_error[field]) is int and actual_provider_error[field] >= 0
        actual_without_timings = {
            key: value
            for key, value in actual_provider_error.items()
            if key not in {"elapsed_ms", "cleanup_ms"}
        }
        assert actual_without_timings == provider_error
    else:
        assert task["evidence"]["provider_error"] == provider_error
    assert task["evidence"]["terminal_input_attempted"] is False
    assert task["evidence"]["automatic_retry"] is False
    assert task["evidence"]["safe_to_retry"] is False
    assert task["result"] is None
    events = bridge.store.db.execute(
        "SELECT state FROM events WHERE task_id=? ORDER BY seq", (value.task_id,)
    ).fetchall()
    assert "completed" not in [row[0] for row in events]
    assert bridge.store.claim(bridge.tasks.owner, bridge.config.lease_seconds) is None
    spawn.assert_awaited_once()
    transport.send_confirmed.assert_not_awaited()
    transport.send.assert_not_awaited()
    transport.insert.assert_not_awaited()
    transport.press_return.assert_not_awaited()
    bridge.sessions.tmux.catalog.assert_not_awaited()
