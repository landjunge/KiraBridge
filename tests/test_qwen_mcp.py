"""Real KiraBridge HTTP + stdio connect, using a private task and fixture provider."""

import asyncio
import json
import os
import sys
from pathlib import Path

from conftest import request, submit
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from test_mcp import http_bridge  # noqa: F401

from kirabridge.agent_manager.qwen_mcp import task_server
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import AgentInput
from kirabridge.private_files import write_private


async def test_task_scoped_real_connect_filters_and_denies(
    http_bridge,  # noqa: F811
    config,
    tmp_path,
):
    bridge, _ = http_bridge
    entered, finish = asyncio.Event(), asyncio.Event()

    class Hold:
        async def execute(self, *args, **kwargs):
            entered.set()
            await finish.wait()
            return {"success": True, "text": "fixture turn ended"}

    bridge.agents.adapters["qwen_acp"] = Hold()
    config.agents["qwen"] = AgentConfig(
        kind="qwen_acp", executable=sys.executable, qwen_mcp_tools=["bridge_epoch"]
    )
    config.principals["local"].agents.append("qwen")
    root = config.principals["local"].roots[0]
    value = request(
        "agent.execute",
        {
            "agent": "qwen",
            "cwd": root,
            "prompt": "private fixture",
            "timeout": 15,
            "mcp_grants": [{"tool": "bridge_epoch", "arguments": {}, "calls": 1}],
        },
    )
    submit(bridge, value)
    await asyncio.wait_for(entered.wait(), 5)
    credentials = tmp_path / "test-credentials.json"
    write_private(credentials, json.dumps({"local": os.environ["BRIDGE_TEST_TOKEN"]}))
    path = tmp_path / "connect.toml"
    path.write_text(
        f"data_dir = {json.dumps(str(tmp_path / 'unused'))}\nport = {config.port}\n"
        f"credentials_file = {json.dumps(str(credentials))}\n[principals.local]\n"
        'capabilities = ["bridge.health", "task.read"]\n'
    )
    path.chmod(0o600)
    config._source_path = str(path)
    task = bridge.store.get(value.task_id, "local")
    args = AgentInput.model_validate(task["args"])
    try:
        with task_server(config, task, args, 15) as spec:
            policy_path = Path(spec["args"][-1])
            assert policy_path.stat().st_mode & 0o777 == 0o600
            assert "private fixture" not in policy_path.read_text()
            assert os.environ["BRIDGE_TEST_TOKEN"] not in json.dumps(spec)
            params = StdioServerParameters(
                command=spec["command"],
                args=spec["args"],
                env={item["name"]: item["value"] for item in spec["env"]},
            )
            async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
                await session.initialize()
                catalog = await session.list_tools()
                assert [tool.name for tool in catalog.tools] == ["bridge_epoch"]
                denied = await session.call_tool("task_request", {"request": value.model_dump()})
                assert denied.isError
                assert denied.structuredContent["error"]["code"] == "agent_task_denied"
                result = await session.call_tool("bridge_epoch", {})
                assert (
                    not result.isError
                    and result.structuredContent["discovery"]["principal"] == "local"
                )
                assert (await session.call_tool("bridge_epoch", {})).isError
            assert not (tmp_path / "unused").exists()
        assert not policy_path.exists()
    finally:
        finish.set()
        await bridge.tasks.wait("local", value.task_id)


async def test_real_mcp_coding_child_is_scoped_and_idempotent(
    http_bridge,  # noqa: F811
    config,
    tmp_path,
):
    bridge, _ = http_bridge
    entered, finish = asyncio.Event(), asyncio.Event()

    class Hold:
        async def execute(self, *args, **kwargs):
            entered.set()
            await finish.wait()
            return {"success": True}

    bridge.agents.adapters["qwen_acp"] = Hold()
    config.agents["qwen"] = AgentConfig(
        kind="qwen_acp",
        executable=sys.executable,
        sandbox_mode="workspace-write",
        allow_local_tools=True,
        bridge_tools=True,
        qwen_mcp_tools=["task_request", "task_get"],
        qwen_mcp_operations=["file.write"],
    )
    policy = config.principals["local"]
    policy.agents.append("qwen")
    policy.capabilities.append("agent.local_tools")
    policy.approval_mode = "automatic"
    cwd = policy.roots[0]
    value = request(
        "agent.execute",
        {
            "agent": "qwen",
            "cwd": cwd,
            "prompt": "fixture coding",
            "timeout": 20,
            "local_tools": True,
            "mcp_operations": ["file.write"],
        },
    )
    submit(bridge, value)
    await asyncio.wait_for(entered.wait(), 5)
    credentials = tmp_path / "coding-creds.json"
    write_private(credentials, json.dumps({"local": os.environ["BRIDGE_TEST_TOKEN"]}))
    cfg = tmp_path / "coding-connect.toml"
    write_private(
        cfg,
        f"data_dir = {json.dumps(str(tmp_path / 'unused-coding'))}\n"
        f"port = {config.port}\ncredentials_file = {json.dumps(str(credentials))}\n"
        '[principals.local]\ncapabilities = ["bridge.health", "task.read", "file.write"]\n',
    )
    config._source_path = str(cfg)
    task = bridge.store.get(value.task_id, "local")
    args = AgentInput.model_validate(task["args"])
    try:
        with task_server(config, task, args, 20) as spec:
            params = StdioServerParameters(
                command=spec["command"],
                args=spec["args"],
                env={x["name"]: x["value"] for x in spec["env"]},
            )
            async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
                await session.initialize()
                assert {t.name for t in (await session.list_tools()).tools} == {
                    "task_request",
                    "task_get",
                }
                target = str(Path(cwd) / "qwen-coding-marker")
                child = {
                    "task_id": "qwen-coding-child",
                    "idempotency_key": "qwen-coding-child",
                    "parent_id": value.task_id,
                    "operation": "file.write",
                    "arguments": {"path": target, "text": "PRIVATE_FIXTURE_MCP_WRITE"},
                }
                foreign = {
                    **child,
                    "task_id": "foreign",
                    "arguments": {"path": str(tmp_path / "escape"), "text": "x"},
                }
                assert (await session.call_tool("task_request", {"request": foreign})).isError
                assert not (await session.call_tool("task_request", {"request": child})).isError
                done = await bridge.tasks.wait("local", "qwen-coding-child")
                assert done["state"] == "completed"
                assert Path(target).read_text() == "PRIVATE_FIXTURE_MCP_WRITE"
                assert (await session.call_tool("task_request", {"request": child})).isError
                assert not (
                    await session.call_tool("task_get", {"task_id": "qwen-coding-child"})
                ).isError
                assert (await session.call_tool("task_get", {"task_id": value.task_id})).isError
                assert not (tmp_path / "escape").exists()
    finally:
        finish.set()
        await bridge.tasks.wait("local", value.task_id)
