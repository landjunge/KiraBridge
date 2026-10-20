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
from kirabridge.mcp_gateway.proxy import DaemonConnection


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
    bridge.config.port = port
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


async def test_cached_tools_expose_existing_terminal_targets_over_real_http(
    http_bridge, config, monkeypatch
):
    bridge, endpoint = http_bridge
    policy = config.principals["local"]
    policy.capabilities += ["session.inspect"]
    policy.permission_level = "full"
    target = {
        "pane_id": "terminal:123:ttys004",
        "expected_pid": 345,
        "window_id": 123,
        "tty": "/dev/ttys004",
        "busy": True,
    }
    reads = []

    async def catalog(principal):
        bridge.security.principal(principal, "session.inspect")
        return {"status": "available", "sessions": [target]}

    async def native(source, *, mutation=False):
        assert not mutation
        reads.append(source)
        return "READ_FROM_EXACT_WINDOW"

    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    monkeypatch.setattr(bridge.sessions.terminal_app, "native", native)
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        result = (await clients.call("local", "agent_status", {})).structuredContent
        assert result["interactive_terminal_sessions"] == [target] and not reads
        permissions = (await clients.call("local", "operation_catalog", {})).structuredContent
        assert permissions["terminal_access"]["policy_authorized"]
        assert not permissions["terminal_access"]["input_approval_required"]
        assert not permissions["terminal_access"]["additional_input_buffer_enabled"]
        result = (
            await clients.call("local", "read_query", {"query": {"operation": "session.catalog"}})
        ).structuredContent
        assert result["sessions"] == [target]
        result = (
            await clients.call(
                "local",
                "read_query",
                {
                    "query": {
                        "operation": "session.read",
                        "pane_id": target["pane_id"],
                        "expected_pid": 346,
                    }
                },
            )
        ).structuredContent
        assert result["error"]["code"] == "session_selection_changed" and not reads
        result = (
            await clients.call(
                "local",
                "read_query",
                {
                    "query": {
                        "operation": "session.read",
                        "pane_id": target["pane_id"],
                        "expected_pid": 345,
                    }
                },
            )
        ).structuredContent
        assert result["text"] == "READ_FROM_EXACT_WINDOW"
        assert len(reads) == 1
        for operation, arguments in [
            ("session.catalog", {}),
            ("session.read", {"pane_id": target["pane_id"], "expected_pid": 345}),
        ]:
            value = request(operation, arguments, task_id="cached-" + operation.replace(".", "-"))
            await clients.call("local", "task_request", {"request": value.model_dump()})
            completed = await bridge.tasks.wait("local", value.task_id, timeout=5)
            assert completed["state"] == "completed", completed
            assert (
                completed["result"].get("sessions") == [target]
                if operation == "session.catalog"
                else completed["result"]["text"] == "READ_FROM_EXACT_WINDOW"
            )


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


async def test_reconnect_reconciles_accepted_task_without_replaying_uncertain_call(
    http_bridge, monkeypatch
):
    bridge, endpoint = http_bridge
    bridge.config.principals["local"].approval_mode = "automatic"
    root = bridge.config.principals["local"].roots[0]
    value = request("file.write", {"path": root + "/one-write", "text": "once"})
    async with MCPClientPool() as clients:
        proxy = DaemonConnection(
            clients, Peer("daemon", url=endpoint, token="local-test-" + "a" * 40)
        )
        await proxy.ensure_connection()
        original = clients.call
        calls = []

        async def lose_response(*args):
            calls.append(args[1])
            await original(*args)  # The request has actually been persisted before response loss.
            raise BridgeError("peer_unknown", "Response lost after acceptance")

        monkeypatch.setattr(clients, "call", lose_response)
        with pytest.raises(BridgeError, match="Response lost"):
            await proxy.call_tool("task_request", {"request": value.model_dump()})
        assert calls == ["task_request"]
        monkeypatch.setattr(clients, "call", original)
        await bridge.tasks.wait("local", value.task_id)
        await clients.disconnect("daemon")
        # New owner/initialize, then read the original task ID. Never mint a retry ID.
        result = await proxy.call_tool("task_get", {"task_id": value.task_id})
        assert result.structuredContent["state"] == "completed"
        await proxy.call_tool("task_request", {"request": value.model_dump()})
        assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
        events = bridge.events("local", value.task_id)["events"]
        assert sum(x["state"] == "running" for x in events) == 1
        assert sum(x["state"] == "completed" for x in events) == 1
        assert {tool.name for tool in await proxy.list_tools()} >= {"bridge_readiness"}


async def test_http_readiness_checks_authenticated_identity_and_loaded_snapshot(http_bridge):
    bridge, endpoint = http_bridge
    root = bridge.config.principals["local"].roots[0]
    async with MCPClientPool() as clients:
        await clients.connect(Peer("daemon", url=endpoint, token="local-test-" + "a" * 40))
        result = (
            await clients.call(
                "daemon",
                "bridge_readiness",
                {
                    "read_paths": [root + "/not-created"],
                    "executables": ["/bin/cat"],
                },
            )
        ).structuredContent
        assert result["principal"] == "local"
        assert result["runtime"]["source_tree_sha256"] == bridge.runtime["source_tree_sha256"]
        assert result["read_path_checks"][0]["code"] == "path_missing"
        assert result["executable_checks"][0]["code"] == "executable_denied"
        assert result["requested_prerequisites_ready"] is False
        excessive = (
            await clients.call(
                "daemon",
                "bridge_readiness",
                {
                    "read_paths": [root + "/not-created"] * 17,
                },
            )
        ).structuredContent
        assert excessive["error"]["code"] == "invalid_arguments"


async def test_task_contract_does_not_require_events_subscription(http_bridge):
    _, endpoint = http_bridge
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        listing = await clients.sessions["local"].list_tools()
        for name in ["task_request", "task_submit"]:
            tool = next(tool for tool in listing.tools if tool.name == name)
            assert "completion_subscription" not in tool.inputSchema["properties"]
            assert set(tool.inputSchema["required"]) == {"request"}
            assert "completion_target" not in tool.inputSchema["required"]


async def test_direct_read_http_needs_no_task_or_subscription(http_bridge, config):
    from pathlib import Path

    bridge, endpoint = http_bridge
    path = Path(config.principals["local"].roots[0]) / "direct.log"
    path.write_text("ACTUAL_HTTP_READ\n")
    before = bridge.store.db.execute("select count(*) from tasks").fetchone()[0]
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        result = await clients.call(
            "local", "read_query", {"query": {"operation": "file.read", "path": str(path)}}
        )
        assert result.structuredContent["text"] == "ACTUAL_HTTP_READ\n"
        result = await clients.call(
            "local", "read_query", {"query": {"operation": "file.write", "path": str(path)}}
        )
        assert result.structuredContent["error"]["code"] == "invalid_arguments"
    assert bridge.store.db.execute("select count(*) from tasks").fetchone()[0] == before


async def test_action_aliases_without_events_preserve_execution_and_idempotency(
    http_bridge, config
):
    bridge, endpoint = http_bridge
    config.principals["local"].approval_mode = "automatic"
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        listing = {t.name: t for t in (await clients.sessions["local"].list_tools()).tools}
        for name in ("action_request", "action_submit", "task_request", "task_submit"):
            assert "completion_subscription" not in listing[name].inputSchema["properties"]
            assert listing[name].inputSchema["required"] == ["request"]
        for name in ("action_request", "action_submit"):
            value = request(
                "file.write",
                {"path": config.principals["local"].roots[0] + "/" + name, "text": "ALIAS_OK"},
                task_id=name,
            )
            result = await clients.call("local", name, {"request": value.model_dump()})
            assert result.structuredContent["state"] == "queued"
            assert (await bridge.tasks.wait("local", value.task_id))["state"] == "completed"
            duplicate = await clients.call("local", name, {"request": value.model_dump()})
            assert duplicate.structuredContent["id"] == value.task_id
