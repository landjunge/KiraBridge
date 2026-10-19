"""Real MCP/child-process return path. These tests do not attest Grok audio."""

import sys

import pytest
from conftest import request
from test_mcp import http_bridge  # noqa: F401

from kirabridge.bridge_core.config import AgentConfig, GrokConnectorConfig, ReceiverConfig
from kirabridge.bridge_core.models import BridgeError, State
from kirabridge.grok_connector.conversation import result_for_conversation
from kirabridge.mcp_gateway.client import MCPClientPool, Peer


def configure(config, monkeypatch):
    monkeypatch.setenv("GROK_RETURN_TEST_TOKEN", "grok-return-" + "x" * 40)
    config.principals["grok_app"] = config.principals["local"].model_copy(deep=True)
    config.principals["grok_app"].approval_mode = "automatic"
    config.principals["grok_app"].token_env = "GROK_RETURN_TEST_TOKEN"
    config.grok_connector = GrokConnectorConfig(
        enabled=True, public_origin="https://grok-return.example"
    )


async def connect(clients, endpoint):
    await clients.connect(Peer("grok", url=endpoint, token="grok-return-" + "x" * 40))


@pytest.mark.parametrize("tool", ["task_request", "action_request", "task_submit", "action_submit"])
async def test_grok_submit_returns_actual_shell_result_in_same_tool_response(
    http_bridge,  # noqa: F811
    config,
    monkeypatch,
    tool,  # noqa: F811
):
    _, endpoint = http_bridge
    configure(config, monkeypatch)
    value = request(
        "terminal.execute",
        {
            "argv": [sys.executable, "-c", "import time;time.sleep(.08);print('REAL_RETURN_OK')"],
            "cwd": config.principals["local"].roots[0],
        },
    )
    async with MCPClientPool() as clients:
        await connect(clients, endpoint)
        result = (
            await clients.call("grok", tool, {"request": value.model_dump()})
        ).structuredContent
    assert result["state"] == "completed"
    assert result["result"]["stdout"].strip() == "REAL_RETURN_OK"
    assert result["conversation_return"]["text"].strip() == "REAL_RETURN_OK"
    assert result["conversation_return"]["final"]
    assert result["conversation_return"]["audio_playback"] == "not_observed_by_bridge"


async def test_long_grok_work_continues_same_task_without_second_execution(
    http_bridge,  # noqa: F811
    config,
    monkeypatch,
    tmp_path,  # noqa: F811
):
    bridge, endpoint = http_bridge
    configure(config, monkeypatch)
    monkeypatch.setattr("kirabridge.grok_connector.conversation.WAIT_SECONDS", 0.03)
    cwd = config.principals["local"].roots[0]
    value = request(
        "terminal.execute",
        {
            "argv": [
                sys.executable,
                "-c",
                "import time;open('invocations','a').write('once\\n');"
                "time.sleep(.2);print('LATE_REAL_REPLY')",
            ],
            "cwd": cwd,
        },
    )
    async with MCPClientPool() as clients:
        await connect(clients, endpoint)
        first = (
            await clients.call("grok", "action_request", {"request": value.model_dump()})
        ).structuredContent
        assert first["conversation_return"]["continue_required"]
        assert not first["conversation_return"]["final"]
        await bridge.tasks.wait("grok_app", value.task_id, timeout=3)
        final = (
            await clients.call("grok", "task_get", {"task_id": value.task_id})
        ).structuredContent
        duplicate = (
            await clients.call("grok", "action_request", {"request": value.model_dump()})
        ).structuredContent
        await clients.connect(Peer("other", url=endpoint, token="other-test-" + "b" * 40))
        foreign = (
            await clients.call("other", "task_get", {"task_id": value.task_id})
        ).structuredContent
    assert final["conversation_return"]["text"].strip() == "LATE_REAL_REPLY"
    assert final["conversation_return"]["final"]
    assert duplicate["id"] == first["id"] == final["id"]
    assert foreign["error"]["code"] == "not_found"
    assert (__import__("pathlib").Path(cwd) / "invocations").read_text() == "once\n"


async def test_transport_cancellation_leaves_grok_work_recoverable_once(
    http_bridge,  # noqa: F811
    config,
    monkeypatch,  # noqa: F811
):
    bridge, endpoint = http_bridge
    configure(config, monkeypatch)
    value = request(
        "terminal.execute",
        {
            "argv": [sys.executable, "-c", "import time;time.sleep(.25);print('AFTER_DISCONNECT')"],
            "cwd": config.principals["local"].roots[0],
        },
    )
    async with MCPClientPool() as clients:
        await connect(clients, endpoint)
        clients.call_timeout = 0.04
        with pytest.raises(BridgeError, match="unknown"):
            await clients.call("grok", "action_request", {"request": value.model_dump()})
        await bridge.tasks.wait("grok_app", value.task_id, timeout=3)
        clients.call_timeout = 5
        result = (
            await clients.call("grok", "task_get", {"task_id": value.task_id})
        ).structuredContent
    assert result["state"] == "completed" and result["attempt"] == 1
    assert result["conversation_return"]["text"].strip() == "AFTER_DISCONNECT"


async def test_grok_manual_approval_is_not_silently_skipped(http_bridge, config, monkeypatch):  # noqa: F811
    bridge, endpoint = http_bridge
    configure(config, monkeypatch)
    config.principals["grok_app"].approval_mode = "manual"
    value = request(arguments={"path": config.principals["local"].roots[0]})
    async with MCPClientPool() as clients:
        await connect(clients, endpoint)
        result = (
            await clients.call("grok", "task_request", {"request": value.model_dump()})
        ).structuredContent
    assert result["state"] == "created" and result["approval_required"]
    assert not result["conversation_return"]["continue_required"]
    assert not result["conversation_return"]["final"]
    assert not bridge.store.db.execute("SELECT 1 FROM events WHERE state='running'").fetchone()


async def test_terminal_input_delivery_never_claims_a_spoken_agent_reply(
    bridge, config, monkeypatch
):
    configure(config, monkeypatch)
    task = request("session.input", {"pane_id": "%1", "expected_pid": 1, "text": "hello"})
    bridge.prepare("grok_app", task)
    bridge.store.claim("test-worker", 30)
    bridge.store.transition(
        task.task_id, State.RUNNING, {"test": "input started"}, owner="test-worker"
    )
    bridge.store.transition(
        task.task_id,
        State.COMPLETED,
        {"test": "input delivered"},
        result={"sent": True},
        owner="test-worker",
    )
    result = await result_for_conversation(
        bridge, "grok_app", bridge.task("grok_app", task.task_id)
    )
    assert not result["conversation_return"]["final"]
    assert result["conversation_return"]["scope"] == "terminal_input_delivery"
    assert result["conversation_return"]["terminal_reply_tool"] == "session_read"
    assert result["conversation_return"]["continue_required"]
    assert result["conversation_return"]["next_call"] == {
        "tool": "session_read",
        "arguments": {"pane_id": "%1", "expected_pid": 1},
    }


async def test_chatgpt_submission_contract_is_unchanged(http_bridge, config, monkeypatch):  # noqa: F811
    _, endpoint = http_bridge
    configure(config, monkeypatch)
    config.principals["local"].approval_mode = "automatic"
    value = request(arguments={"path": config.principals["local"].roots[0]})
    async with MCPClientPool() as clients:
        await clients.connect(Peer("chatgpt", url=endpoint, token="local-test-" + "a" * 40))
        result = (
            await clients.call("chatgpt", "task_request", {"request": value.model_dump()})
        ).structuredContent
    assert result["state"] == "queued"
    assert "conversation_return" not in result


async def test_grok_voice_message_returns_actual_agent_reply_to_same_client(
    http_bridge,  # noqa: F811
    config,
    monkeypatch,
    tmp_path,  # noqa: F811
):
    from test_agents import fake_cli

    bridge, endpoint = http_bridge
    configure(config, monkeypatch)
    source = config.principals["grok_app"]
    source.capabilities += ["message.send", "message.read", "message.ack"]
    source.message_peers = ["codex"]
    target = source.model_copy(deep=True)
    target.message_peers = ["grok_app"]
    target.token_env = "GROK_MESSAGE_CODEX_TOKEN"
    monkeypatch.setenv(target.token_env, "codex-native-return-" + "x" * 40)
    config.principals["codex"] = target
    cli = fake_cli(
        tmp_path,
        """import json,sys
sys.stdin.read()
for event in [
 {'type':'thread.started','thread_id':'explicit-test-codex'},
 {'type':'turn.started'},
 {'type':'item.completed','item':{'type':'agent_message','text':'EXACT_AGENT_RETURN'}},
 {'type':'turn.completed'}]:print(json.dumps(event),flush=True)
""",
    )
    config.agents["codex"] = AgentConfig(kind="codex", executable=cli)
    config.messaging.receivers["codex"] = ReceiverConfig(cwd=source.roots[0], timeout=5)
    await bridge.message_receiver.start()
    value = {
        "recipient": "codex",
        "conversation_id": "real-tool-client-return",
        "idempotency_key": "once",
        "kind": "question",
        "body": "This test double must return its protocol result.",
    }
    async with MCPClientPool() as clients:
        await connect(clients, endpoint)
        result = (await clients.call("grok", "message_send", {"message": value})).structuredContent
        assert result["message_buffer"]["state"] == "waiting"
        assert "Puffer" in result["conversation_return"]["text"]
        result = (
            await clients.call(
                "grok",
                "message_release",
                {
                    "message_id": result["id"],
                    "token": "go-go-go",
                },
            )
        ).structuredContent
        assert result["conversation_return"]["text"] == "EXACT_AGENT_RETURN"
        assert result["conversation_return"]["final"]
        reply = result["reply_message"]
        assert reply["recipient"] == "grok_app" and reply["receipt"]
        assert reply["acknowledged"] is None and reply["processing"] is None
        await clients.call(
            "grok", "message_ack", {"message_id": reply["id"], "receipt": reply["receipt"]}
        )
        duplicate = (
            await clients.call("grok", "message_send", {"message": value})
        ).structuredContent
        assert duplicate["reply_message"]["id"] == reply["id"]
    assert bridge.store.db.execute("SELECT count(*) FROM message_jobs").fetchone()[0] == 1
