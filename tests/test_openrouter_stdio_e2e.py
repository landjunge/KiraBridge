"""Fake OpenRouter HTTP over the real, task-scoped KiraBridge stdio proxy."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
from conftest import request, submit
from test_mcp import http_bridge  # noqa: F401

from kirabridge.agent_manager.openrouter import OpenRouterAdapter
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.private_files import write_private


@pytest.mark.parametrize(
    ("change_binding", "expected_state", "expected_requests"),
    [(False, "completed", 2), (True, "unknown", 1)],
)
async def test_openrouter_stdio_proxy_shares_task_database_and_binds_parent(
    http_bridge,  # noqa: F811
    config,
    tmp_path,
    monkeypatch,
    change_binding,
    expected_state,
    expected_requests,
):
    bridge, _endpoint = http_bridge
    workspace = Path(config.principals["local"].roots[0])
    config.principals["local"].agents.append("openrouter")
    config.principals["local"].capabilities.append("agent.local_tools")
    config.agents["openrouter"] = AgentConfig(
        kind="openrouter_api",
        bridge_tools=True,
        allow_local_tools=True,
        sandbox_mode="workspace-write",
        openrouter_mcp_tools=["bridge_health"],
        openrouter_max_tool_calls=1,
    )

    credentials = tmp_path / "proxy-credentials.json"
    write_private(credentials, json.dumps({"local": os.environ["BRIDGE_TEST_TOKEN"]}))
    connect_config = tmp_path / "proxy.toml"
    write_private(
        connect_config,
        f"data_dir = {json.dumps(bridge.config.data_dir)}\n"
        f"port = {bridge.config.port}\n"
        f"credentials_file = {json.dumps(str(credentials))}\n"
        "[principals.local]\n"
        f"roots = [{json.dumps(str(workspace))}]\n"
        'capabilities = ["bridge.health", "task.read"]\n',
    )
    bridge.config._source_path = str(connect_config)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-no-network-key")
    task_id = "openrouter-stdio-bound-task"
    provider_requests = []

    def provider_response(request_):
        body = json.loads(request_.content)
        provider_requests.append(body)
        if len(provider_requests) == 1:
            assert [item["function"]["name"] for item in body["tools"]] == ["bridge_health"]
            if change_binding:
                args = bridge.store.get(task_id, "local")["args"]
                args["prompt"] = "changed after task policy creation"
                bridge.store.db.execute(
                    "UPDATE tasks SET args=? WHERE id=?", (json.dumps(args), task_id)
                )
            return httpx.Response(
                200,
                json={
                    "id": "synthetic-tool-call",
                    "model": "particle-ai/particle-1:free",
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_once",
                                        "type": "function",
                                        "function": {
                                            "name": "bridge_health",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                },
            )
        assert body["messages"][-1]["role"] == "tool"
        return httpx.Response(
            200,
            json={
                "id": "synthetic-final",
                "model": "particle-ai/particle-1:free",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Done."},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    original_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(provider_response)
        return original_client(*args, **kwargs)

    bridge.agents.adapters["openrouter_api"] = OpenRouterAdapter(
        bridge.config, client_factory=fake_client
    )
    value = request(
        "agent.execute",
        {
            "agent": "openrouter",
            "cwd": str(workspace),
            "prompt": "Inspect bridge health.",
            "timeout": 20,
            "mcp_grants": [{"tool": "bridge_health", "arguments": {}, "calls": 1}],
        },
        task_id=task_id,
    )
    submit(bridge, value)
    parent = await bridge.tasks.wait("local", task_id, timeout=20)
    assert parent["state"] == expected_state, {
        "state": parent["state"],
        "error": parent["error"],
        "evidence": parent["evidence"],
    }
    assert len(provider_requests) == expected_requests
