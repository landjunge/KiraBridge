import asyncio
import json
import socket
import sys

import httpx
import pytest
import pytest_asyncio
import uvicorn
from conftest import request
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.http import create_http_app


@pytest_asyncio.fixture
async def http_bridge(bridge, monkeypatch):
    monkeypatch.setenv("BRIDGE_TEST_TOKEN", "local-test-" + "a" * 40)
    monkeypatch.setenv("OTHER_TEST_TOKEN", "other-test-" + "b" * 40)
    bridge.config.principals["local"].token_env = "BRIDGE_TEST_TOKEN"
    bridge.config.principals["other"].token_env = "OTHER_TEST_TOKEN"
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(64)
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(create_http_app(bridge), log_level="critical", access_log=False)
    )
    async with bridge:
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if task.done():
                        await task
                    await asyncio.sleep(0.01)
            yield bridge, f"http://127.0.0.1:{port}/mcp"
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 10)
            sock.close()


async def test_http_auth_origin_host_and_protocol_limits(http_bridge):
    _, endpoint = http_bridge
    async with httpx.AsyncClient(trust_env=False) as client:
        assert (await client.post(endpoint, json={})).status_code == 401
        assert (
            await client.post(endpoint, headers={"Authorization": "Bearer wrong"}, json={})
        ).status_code == 401
        headers = {
            "Authorization": "Bearer local-test-" + "a" * 40,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        response = await client.post(
            endpoint, headers={**headers, "Host": "attacker.example"}, json={}
        )
        assert response.status_code in {403, 421}
        response = await client.post(
            endpoint, headers={**headers, "Origin": "https://attacker.example"}, json={}
        )
        assert response.status_code == 403
        response = await client.post(endpoint, headers=headers, content=b"x" * 2300000)
        assert response.status_code == 413


async def test_multiple_real_http_clients_do_not_cross_principals(http_bridge, config):
    bridge, endpoint = http_bridge
    value = request(arguments={"path": config.principals["local"].roots[0]})
    approval = bridge.security.grant("local", value)
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        await clients.connect(Peer("other", url=endpoint, token="other-test-" + "b" * 40))
        health = await asyncio.gather(
            clients.call("local", "bridge_health", {}), clients.call("other", "bridge_health", {})
        )
        assert all(result.structuredContent["dispatcher_active"] for result in health)
        queued = await clients.call(
            "local", "task_submit", {"request": value.model_dump(), "approval": approval}
        )
        assert queued.structuredContent["id"] == value.task_id
        await bridge.tasks.wait("local", value.task_id)
        own, foreign = await asyncio.gather(
            clients.call("local", "task_get", {"task_id": value.task_id}),
            clients.call("other", "task_get", {"task_id": value.task_id}),
        )
        assert own.structuredContent["state"] == "completed"
        assert foreign.structuredContent["error"]["code"] == "not_found"
        duplicate = await clients.call(
            "local", "task_submit", {"request": value.model_dump(), "approval": ""}
        )
        assert duplicate.structuredContent["id"] == value.task_id
        info = await clients.call("local", "clipboard_info", {})
        assert info.structuredContent["content_read"] is False
        with pytest.raises(BridgeError):
            await clients.connect(Peer("local", url=endpoint))


async def test_http_automatic_mode_is_per_identity_and_requires_authentication(http_bridge, config):
    bridge, endpoint = http_bridge
    config.principals["local"].approval_mode = "automatic"
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        await clients.connect(Peer("other", url=endpoint, token="other-test-" + "b" * 40))
        for principal in ["local", "other"]:
            automatic = principal == "local"
            health = (await clients.call(principal, "bridge_health", {})).structuredContent
            assert health["approval_required"] is not automatic
            catalog = (await clients.call(principal, "operation_catalog", {})).structuredContent
            assert catalog["operations"]["file.list"]["approval_required"] is not automatic
            value = request(
                arguments={"path": config.principals[principal].roots[0]}, task_id=principal
            )
            result = (
                await clients.call(principal, "task_request", {"request": value.model_dump()})
            ).structuredContent
            assert result["approval_required"] is not automatic
            if automatic:
                assert (await bridge.tasks.wait(principal, value.task_id))["state"] == "completed"
            else:
                assert result["state"] == "created" and result["started"] is None
        async with httpx.AsyncClient(trust_env=False) as client:
            assert (await client.post(endpoint, json={})).status_code == 401


async def test_real_stdio_roundtrip(tmp_path):
    config = tmp_path / "bridge.toml"
    config.write_text("data_dir = " + json.dumps(str(tmp_path / "stdio-state")) + "\n")
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "kirabridge.cli", "--config", str(config), "serve"]
    )
    async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
        initialized = await session.initialize()
        assert initialized.protocolVersion
        tools = await session.list_tools()
        assert {"clipboard_read", "clipboard_write", "clipboard_info", "task_submit"} <= {
            tool.name for tool in tools.tools
        }
        health = await session.call_tool("bridge_health", {})
        assert health.structuredContent["dispatcher_active"]
        denied = await session.call_tool("clipboard_info", {})
        assert denied.structuredContent["error"]["code"] == "forbidden"


async def test_client_pool_real_stdio_owner_lifecycle(tmp_path):
    config = tmp_path / "bridge.toml"
    config.write_text("data_dir = " + json.dumps(str(tmp_path / "pool-state")) + "\n")
    async with MCPClientPool() as clients:
        await clients.connect(
            Peer(
                "stdio",
                command=sys.executable,
                args=("-m", "kirabridge.cli", "--config", str(config), "serve"),
            )
        )
        result = await clients.call("stdio", "bridge_health", {})
        assert result.structuredContent["api_version"] == "1"
    assert not clients.owners and not clients.sessions


async def test_client_refuses_insecure_remote_transport():
    async with MCPClientPool() as clients:
        for url in (
            "http://remote.example/mcp",
            "https://user:secret@host/mcp",
            "file:///tmp/peer",
            "https://host/mcp?token=secret",
        ):
            with pytest.raises(BridgeError):
                await clients.connect(Peer("bad", url=url))
