"""Real HTTP admission returns after an owned spawn, before process completion."""

import asyncio
import sys
from pathlib import Path

import pytest
from test_mcp import http_bridge  # noqa: F401

from kirabridge.mcp_gateway.client import MCPClientPool, Peer


@pytest.mark.parametrize("tool", ["action_request", "action_submit"])
async def test_managed_spawn_releases_http_call_but_not_execution(
    http_bridge,  # noqa: F811
    monkeypatch,
    tool,
):
    bridge, endpoint = http_bridge
    policy = bridge.config.principals["local"].model_copy(deep=True)
    policy.token_env = "MANAGED_HTTP_TEST_TOKEN"
    policy.permission_level = "full"
    policy.capabilities.append("session.inspect")
    bridge.config.principals["chatgpt"] = policy
    monkeypatch.setenv(policy.token_env, "managed-http-" + "c" * 40)
    bridge.tasks.native.timeout = 0.25
    workspace = policy.roots[0]
    release = Path(workspace) / "release-own-child"
    code = (
        "import time; from pathlib import Path; "
        f"release=Path({str(release)!r}); "
        "\nwhile not release.exists(): time.sleep(.01)"
        "\nprint('OWNED_HTTP_COMPLETE')"
    )
    task_id = "managed-http-" + tool
    request = {
        "task_id": task_id,
        "idempotency_key": task_id,
        "operation": "terminal.execute",
        "arguments": {
            "argv": [sys.executable, "-c", code],
            "cwd": workspace,
            "background": True,
            "timeout": 5,
        },
    }
    executions = []
    original = bridge.tasks.executor

    async def executor(task, running, progress):
        executions.append(task["id"])
        return await original(task, running, progress)

    bridge.tasks.executor = executor
    try:
        async with MCPClientPool(call_timeout=3) as clients:
            await clients.connect(Peer("caller", url=endpoint, token="managed-http-" + "c" * 40))
            async with asyncio.timeout(2):
                admission = await clients.call("caller", tool, {"request": request})
            assert not admission.isError
            admitted = admission.structuredContent
            assert "state" in admitted, admitted
            assert admitted["state"] == "running"
            assert admitted["delivery"]["status"] == "process_started"
            assert admitted["result"] is None
            assert "terminal_input_attempted" not in admitted["evidence"]
            await asyncio.sleep(0.35)
            observed = (
                await clients.call("caller", "task_get", {"task_id": task_id})
            ).structuredContent
            assert observed["state"] == "running" and observed["error"] is None
            assert bridge.terminal.sessions[task_id].process.returncode is None
            assert task_id in bridge.tasks.native.targets.values()
            release.touch()
            async with asyncio.timeout(3):
                while True:
                    final = (
                        await clients.call("caller", "task_get", {"task_id": task_id})
                    ).structuredContent
                    if final["state"] == "completed":
                        break
                    assert final["state"] == "running", final
                    await asyncio.sleep(0.01)
            assert final["result"]["exit_code"] == 0
            assert final["result"]["stdout"].strip() == "OWNED_HTTP_COMPLETE"
            repeated = await clients.call("caller", tool, {"request": request})
            assert repeated.structuredContent["state"] == "completed"
            assert executions == [task_id]
            assert task_id not in bridge.terminal.sessions
    finally:
        release.touch(exist_ok=True)
