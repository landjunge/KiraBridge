"""Fresh authorization after the new native MCP observation boundary."""
# Imported fixtures are used by pytest.
# ruff: noqa: F811

import pytest
from test_mcp import http_bridge  # noqa: F401

from kirabridge.mcp_gateway.client import MCPClientPool, Peer


@pytest.mark.parametrize("tool", ["action_request", "action_submit"])
async def test_native_admission_rechecks_read_right_after_await(http_bridge, tool):
    bridge, endpoint = http_bridge
    bridge.config.visible_handoffs.enabled = True
    bridge.config.principals["local"].approval_mode = "automatic"
    bridge.tasks.preflight = None

    async def executor(task, running, progress):
        bridge.config.principals["local"].capabilities.remove("task.read")
        await running({"terminal_input_attempted": True})
        return {"success": True, "text": "PRIVATE RESULT MUST NOT LEAK"}

    bridge.tasks.executor = executor
    async with MCPClientPool() as pool:
        await pool.connect(Peer("caller", url=endpoint, token="local-test-" + "a" * 40))
        result = (
            await pool.call(
                "caller",
                tool,
                {
                    "request": {
                        "task_id": "revoked-native",
                        "idempotency_key": "revoked-native",
                        "operation": "terminal.visible",
                        "arguments": {
                            "argv": ["/usr/bin/true"],
                            "cwd": bridge.config.principals["local"].roots[0],
                        },
                    }
                },
            )
        ).structuredContent
        assert result["error"]["code"] == "forbidden"
        assert "PRIVATE" not in str(result)
        assert "args" not in result and "result" not in result
