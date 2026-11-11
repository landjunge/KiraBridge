import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from conftest import request, submit
from pydantic import ValidationError

from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import BridgeError


def fake_cli(tmp_path, body):
    path = tmp_path / "agent"
    path.write_text(f"#!{sys.executable}\n" + body)
    path.chmod(0o700)
    return str(path)


@pytest.mark.parametrize("mode", ["read-only", "workspace-write"])
async def test_codex_uses_explicit_bounded_mode_and_preserves_project_rules(
    bridge, config, tmp_path, mode
):
    body = """import json,sys
sys.stdin.read()
print(json.dumps({'type':'thread.started','thread_id':'bounded-test'}),flush=True)
print(json.dumps({'type':'turn.started'}),flush=True)
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps(sys.argv[1:])}}),flush=True)
print(json.dumps({'type':'turn.completed'}),flush=True)
"""
    config.agents["codex"] = AgentConfig(
        kind="codex", executable=fake_cli(tmp_path, body), sandbox_mode=mode
    )
    value = agent_request(config)
    submit(bridge, value)
    async with bridge:
        final = await bridge.tasks.wait("local", value.task_id)
    assert final["state"] == "completed"
    argv = json.loads(final["result"]["text"])
    assert argv[argv.index("--sandbox") + 1] == mode
    assert "--ignore-rules" not in argv and "--ignore-user-config" in argv
    assert 'approval_policy="never"' in argv and "mcp_servers={}" in argv
    assert "--add-dir" not in argv and "danger-full-access" not in argv
    assert final["result"]["evidence"]["sandbox_mode"] == mode
    assert not final["result"]["project_completion_verified"]
    assert bridge.agents.inventory(["codex"])["agents"][0]["sandbox_mode"] == mode


def test_codex_default_stays_read_only_and_global_bypass_is_rejected():
    assert AgentConfig(kind="codex").sandbox_mode == "read-only"
    with pytest.raises(ValidationError):
        AgentConfig(kind="codex", sandbox_mode="danger-full-access")


async def test_codex_write_mode_does_not_grant_a_foreign_working_directory(
    bridge, config, tmp_path
):
    config.agents["codex"] = AgentConfig(
        kind="codex",
        executable=fake_cli(tmp_path, "raise RuntimeError('must not start')"),
        sandbox_mode="workspace-write",
    )
    value = agent_request(config)
    value.arguments["cwd"] = str(tmp_path.parent)
    submit(bridge, value)
    async with bridge:
        final = await bridge.tasks.wait("local", value.task_id)
    assert final["state"] == "failed" and final["started"] is None
    assert final["error"]["code"] == "path_denied"


def agent_request(config, name="codex", task_id="agent-task"):
    return request(
        "agent.execute",
        {
            "agent": name,
            "prompt": "Test prompt; no real provider",
            "cwd": config.principals["local"].roots[0],
            "timeout": 3.0,
        },
        task_id=task_id,
    )


@pytest.mark.parametrize(
    "ending,expected",
    [
        ('{"type":"turn.completed","usage":{}}', "completed"),
        ('{"type":"turn.failed","error":{"message":"secret must not enter audit"}}', "failed"),
        ("", "unknown"),
    ],
)
async def test_codex_requires_completion_event(bridge, config, tmp_path, ending, expected):
    events = [
        {"type": "thread.started", "thread_id": "codex-session-1"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Done"}},
    ]
    body = "import json,sys\nsys.stdin.read()\n"
    body += "\n".join("print(" + repr(json.dumps(event)) + ",flush=True)" for event in events)
    if ending:
        body += "\nprint(" + repr(ending) + ",flush=True)\n"
    config.agents["codex"] = AgentConfig(kind="codex", executable=fake_cli(tmp_path, body))
    value = agent_request(config)
    submit(bridge, value)
    async with bridge:
        final = await bridge.tasks.wait("local", value.task_id)
        assert final["state"] == expected
        assert final["agent"] == "codex"
        states = bridge.events("local", value.task_id)["events"]
        assert any(e["evidence"].get("session_id") == "codex-session-1" for e in states)
        if expected == "completed":
            assert final["result"]["text"] == "Done"
            assert not final["result"]["project_completion_verified"]


async def test_codex_rejects_session_identity_change(bridge, config, tmp_path):
    body = "import json,sys\nsys.stdin.read()\n"
    for event in [
        {"type": "thread.started", "thread_id": "one"},
        {"type": "thread.started", "thread_id": "two"},
    ]:
        body += f"print({json.dumps(json.dumps(event))},flush=True)\n"
    config.agents["codex"] = AgentConfig(kind="codex", executable=fake_cli(tmp_path, body))
    value = agent_request(config)
    submit(bridge, value)
    async with bridge:
        final = await bridge.tasks.wait("local", value.task_id)
        assert final["state"] == "unknown"
        assert final["error"]["code"] == "agent_identity"


async def test_agent_identity_permission_is_independent(bridge, config):
    config.principals["local"].agents = ["codex"]
    value = agent_request(config, name="grok")
    submit(bridge, value)
    async with bridge:
        final = await bridge.tasks.wait("local", value.task_id)
        assert final["state"] == "failed" and final["started"] is None
        assert final["error"]["code"] == "agent_denied"


def test_executable_presence_does_not_imply_work(bridge, config, tmp_path):
    config.agents["grok"] = AgentConfig(kind="grok_acp", executable=fake_cli(tmp_path, "pass\n"))
    agent = bridge.agents.inventory(["grok"])["agents"][0]
    assert agent["executable_present"]
    assert agent["daemon_status"] == agent["session_status"] == agent["task_status"] == "unknown"


async def test_grok_acp_session_and_completion(bridge, config, tmp_path):
    body = """import json,sys
for line in sys.stdin:
    msg=json.loads(line)
    method=msg.get('method')
    if method=='initialize': result={'protocolVersion':1,'authMethods':[{'id':'cached_token'}]}
    elif method=='authenticate': result={}
    elif method=='session/new': result={'sessionId':'grok-session-1'}
    elif method=='session/prompt':
        content={'type':'text','text':'Grok result'}
        update={'sessionUpdate':'agent_message_chunk','content':content}
        params={'sessionId':'grok-session-1','update':update}
        print(json.dumps({'jsonrpc':'2.0','method':'session/update','params':params}),flush=True)
        result={'stopReason':'end_turn'}
    else: continue
    print(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':result}),flush=True)
"""
    config.agents["grok"] = AgentConfig(kind="grok_acp", executable=fake_cli(tmp_path, body))
    value = agent_request(config, "grok")
    submit(bridge, value)
    async with bridge:
        final = await bridge.tasks.wait("local", value.task_id)
        assert final["state"] == "completed"
        assert final["result"]["text"] == "Grok result"
        assert final["result"]["evidence"]["session_id"] == "grok-session-1"
        assert final["agent"] == "grok"


@pytest.mark.parametrize(
    "finish,expected", [("stop", "completed"), (None, "unknown"), ("length", "failed")]
)
async def test_grok_api_requires_server_completion(bridge, config, monkeypatch, finish, expected):
    original = httpx.AsyncClient
    monkeypatch.setenv("XAI_TEST_KEY", "test-only")
    config.agents["grok"] = AgentConfig(
        kind="grok_api", model="test-model", api_key_env="XAI_TEST_KEY"
    )
    calls = []

    def handler(req):
        calls.append(req)
        event = {
            "id": "grok-response-1",
            "choices": [{"delta": {"content": "Hello"}, "finish_reason": finish}],
        }
        return httpx.Response(200, text="data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n")

    def client(**kwargs):
        return original(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr("kirabridge.agent_manager.httpx.AsyncClient", client)
    value = agent_request(config, "grok")
    submit(bridge, value)
    async with bridge:
        final = await bridge.tasks.wait("local", value.task_id)
        assert final["state"] == expected
        assert len(calls) == 1
        if expected == "completed":
            assert final["result"]["text"] == "Hello"
            assert final["result"]["evidence"]["response_id"] == "grok-response-1"


async def test_grok_transport_failure_is_never_retried(bridge, config, monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setenv("XAI_TEST_KEY", "test-only")
    config.agents["grok"] = AgentConfig(
        kind="grok_api", model="test-model", api_key_env="XAI_TEST_KEY"
    )
    count = 0

    def handler(req):
        nonlocal count
        count += 1
        raise httpx.ReadError("sensitive header not for logs")

    monkeypatch.setattr(
        "kirabridge.agent_manager.httpx.AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )
    value = agent_request(config, "grok")
    submit(bridge, value)
    async with bridge:
        final = await bridge.tasks.wait("local", value.task_id)
        assert final["state"] == "unknown"
        assert count == 1
        assert "sensitive" not in json.dumps(final["error"])


async def test_outer_agent_timeout_leaves_cleanup_margin(tmp_path):
    from kirabridge.agent_manager import AgentManager
    from kirabridge.bridge_core.config import Config
    from kirabridge.bridge_core.models import AgentInput
    from kirabridge.terminal_manager import TerminalManager

    manager = AgentManager(Config(), TerminalManager())
    manager.config.visible_handoffs.enabled = False

    class SlowAdapter:
        interface_version = "1"

        async def execute(self, task, args, config, roots, running, progress):
            await asyncio.sleep(args.timeout + 0.05)
            return {"success": True, "text": "adapter deadline won"}

    manager.register("slow-cleanup", SlowAdapter())
    manager.config.agents["slow"] = AgentConfig(kind="slow-cleanup")
    principal = SimpleNamespace(
        agents=["slow"], permission_level=None, roots=[str(tmp_path)], capabilities=[]
    )
    result = await manager.execute(
        {"id": "task-1", "principal": "local"},
        AgentInput(agent="slow", prompt="test", cwd=str(tmp_path), timeout=0.05),
        principal,
        AsyncMock(),
        AsyncMock(),
    )
    assert result["text"] == "adapter deadline won"


def test_extension_requires_version_and_unique_kind(bridge):
    class BadAdapter:
        interface_version = "999"

    with pytest.raises(BridgeError):
        bridge.agents.register("claude", BadAdapter())
