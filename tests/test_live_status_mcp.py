"""KiraBridge Live is the same projection over the authorized MCP read."""

from test_mcp import http_bridge  # noqa: F401

from kirabridge.live_status import project
from kirabridge.mcp_gateway.client import MCPClientPool, Peer


async def test_mcp_live_status_returns_the_same_projection_and_no_raw_text(
    http_bridge,  # noqa: F811
    bridge,
    monkeypatch,
):
    monkeypatch.setenv("BRIDGE_TEST_TOKEN", "local-test-" + "a" * 40)
    bridge.config.principals["local"].capabilities.append("logs.live")
    bridge.live_logs.open("t1", "local", operation="agent.execute", agent="opencode")
    bridge.live_logs.append("t1", "local", "stdout", "SECRET-STDOUT")
    bridge.live_logs.feed(
        "t1", "local", {"event": "session_busy", "agent": "opencode", "prompt": "SECRET-PROMPT"}
    )
    _, endpoint = http_bridge
    async with MCPClientPool() as pool:
        await pool.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        result = (await pool.call("local", "live_status", {})).structuredContent
    direct = project(bridge, "local")
    stable = ("task_id", "family", "state", "step", "source", "unknown")
    assert result["ok"] is True
    assert [{k: a[k] for k in stable} for a in result["agents"]] == [
        {k: a[k] for k in stable} for a in direct["agents"]
    ]
    assert result["agents"][0]["state"] == "working"
    assert "SECRET-STDOUT" not in str(result)
    assert "SECRET-PROMPT" not in str(result)


async def test_mcp_live_status_rejects_a_principal_without_the_capability(
    http_bridge,  # noqa: F811
    bridge,
    monkeypatch,
):
    monkeypatch.setenv("OTHER_TEST_TOKEN", "other-test-" + "b" * 40)
    bridge.config.principals["other"].capabilities.remove("logs.live")
    _, endpoint = http_bridge
    async with MCPClientPool() as pool:
        await pool.connect(Peer("other", url=endpoint, token="other-test-" + "b" * 40))
        result = (await pool.call("other", "live_status", {})).structuredContent
    assert result["error"]["code"] == "forbidden"
