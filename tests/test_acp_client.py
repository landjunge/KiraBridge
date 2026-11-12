"""Focused fake-ACP tests for the shared client and the OpenCode ACP adapter.

Every fixture is a small Python server speaking JSON-RPC over stdio. No real CLI or
provider is started.
"""

import asyncio
import sys

import pytest

from kirabridge.agent_manager.acp import ACPClient
from kirabridge.agent_manager.opencode_acp import OpenCodeACPAdapter
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import AgentInput, UncertainExecution
from kirabridge.terminal_manager import TerminalManager


def server(tmp_path, body):
    path = tmp_path / "acp-server.py"
    path.write_text(body)
    path.chmod(0o700)
    return path


async def spawn_server(tmp_path, body):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(server(tmp_path, body)),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    return process


def client(process):
    return ACPClient(process)


async def stop(process):
    if process.returncode is None:
        process.terminate()
    await process.wait()


HANDSHAKE = """
def handshake(msg):
    method = msg.get("method")
    if method == "initialize":
        return {"protocolVersion": 1, "authMethods": [{"id": "cached_token"}]}
    if method == "authenticate":
        return {}
    if method == "session/new":
        return {"sessionId": "s1"}
    return None
"""


async def test_initialize_session_prompt_and_update_are_bound(tmp_path):
    body = (
        "import json,sys\n"
        + HANDSHAKE
        + """
for line in sys.stdin:
    msg = json.loads(line)
    result = handshake(msg)
    if msg.get("method") == "session/prompt":
        print(json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "s1",
            "update": {"sessionUpdate": "agent_message_chunk",
                       "content": {"type": "text", "text": "hello"},
                       "messageId": "m1", "chunkIndex": 0},
        }}), flush=True)
        result = {"stopReason": "end_turn"}
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
"""
    )
    process = await spawn_server(tmp_path, body)
    acp = client(process)
    acp.start()
    try:
        init = await acp.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}}, 3)
        assert init["protocolVersion"] == 1
        await acp.request(
            "authenticate", {"methodId": "cached_token", "_meta": {"headless": True}}, 3
        )
        new = await acp.request("session/new", {"cwd": str(tmp_path), "mcpServers": []}, 3)
        assert acp.bind_session(new["sessionId"]) == "s1"
        result = await acp.request(
            "session/prompt", {"sessionId": "s1", "prompt": [{"type": "text", "text": "hi"}]}, 3
        )
        assert result["stopReason"] == "end_turn"
        assert acp.text == "hello" and acp.started and not acp.truncated
    finally:
        await acp.aclose()
        await stop(process)


async def test_duplicated_update_is_counted_once(tmp_path):
    body = (
        "import json,sys\n"
        + HANDSHAKE
        + """
for line in sys.stdin:
    msg = json.loads(line)
    result = handshake(msg)
    if msg.get("method") == "session/prompt":
        update = {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "s1",
            "update": {"sessionUpdate": "agent_message_chunk",
                       "content": {"type": "text", "text": "hello"},
                       "messageId": "m1", "chunkIndex": 0},
        }}
        print(json.dumps(update), flush=True)
        print(json.dumps(update), flush=True)
        result = {"stopReason": "end_turn"}
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
"""
    )
    process = await spawn_server(tmp_path, body)
    acp = client(process)
    acp.start()
    try:
        await acp.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}}, 3)
        await acp.request("authenticate", {"methodId": "cached_token"}, 3)
        new = await acp.request("session/new", {"cwd": str(tmp_path), "mcpServers": []}, 3)
        acp.bind_session(new["sessionId"])
        await acp.request(
            "session/prompt", {"sessionId": "s1", "prompt": [{"type": "text", "text": "hi"}]}, 3
        )
        assert acp.text == "hello"
    finally:
        await acp.aclose()
        await stop(process)


async def test_wrong_session_update_is_identity_failure(tmp_path):
    body = (
        "import json,sys\n"
        + HANDSHAKE
        + """
for line in sys.stdin:
    msg = json.loads(line)
    result = handshake(msg)
    if msg.get("method") == "session/prompt":
        print(json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "s2",
            "update": {"sessionUpdate": "agent_message_chunk",
                       "content": {"type": "text", "text": "wrong"}},
        }}), flush=True)
        result = {"stopReason": "end_turn"}
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
"""
    )
    process = await spawn_server(tmp_path, body)
    acp = client(process)
    acp.start()
    try:
        await acp.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}}, 3)
        await acp.request("authenticate", {"methodId": "cached_token"}, 3)
        new = await acp.request("session/new", {"cwd": str(tmp_path), "mcpServers": []}, 3)
        acp.bind_session(new["sessionId"])
        with pytest.raises(UncertainExecution) as caught:
            await acp.request(
                "session/prompt", {"sessionId": "s1", "prompt": [{"type": "text", "text": "hi"}]}, 3
            )
        assert caught.value.code == "agent_identity"
    finally:
        await acp.aclose()
        await stop(process)


async def test_disconnect_during_prompt_is_reported(tmp_path):
    body = (
        "import json,sys\n"
        + HANDSHAKE
        + """
for line in sys.stdin:
    msg = json.loads(line)
    result = handshake(msg)
    if msg.get("method") == "session/prompt":
        sys.exit(0)
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
"""
    )
    process = await spawn_server(tmp_path, body)
    acp = client(process)
    acp.start()
    try:
        await acp.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}}, 3)
        await acp.request("authenticate", {"methodId": "cached_token"}, 3)
        new = await acp.request("session/new", {"cwd": str(tmp_path), "mcpServers": []}, 3)
        acp.bind_session(new["sessionId"])
        with pytest.raises(UncertainExecution) as caught:
            await acp.request(
                "session/prompt", {"sessionId": "s1", "prompt": [{"type": "text", "text": "hi"}]}, 3
            )
        assert caught.value.code == "agent_disconnected"
    finally:
        await acp.aclose()
        await stop(process)


async def test_back_to_back_session_and_update_are_bound_atomically(tmp_path):
    body = (
        "import json,sys\n"
        + HANDSHAKE
        + """
for line in sys.stdin:
    msg = json.loads(line)
    result = handshake(msg)
    if msg.get("method") == "session/new":
        print(
            json.dumps(
                {"jsonrpc": "2.0", "id": msg["id"], "result": {"sessionId": "s1"}}
            ),
            flush=True,
        )
        print(json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "s1",
            "update": {"sessionUpdate": "agent_message_chunk",
                       "content": {"type": "text", "text": "early"}},
        }}), flush=True)
        continue
    if msg.get("method") == "session/prompt":
        result = {"stopReason": "end_turn"}
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
"""
    )
    process = await spawn_server(tmp_path, body)
    acp = client(process)
    acp.start()
    try:
        await acp.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}}, 3)
        await acp.request("authenticate", {"methodId": "cached_token"}, 3)
        await acp.request("session/new", {"cwd": str(tmp_path), "mcpServers": []}, 3)
        # No caller-side bind_session: the client must bind atomically while
        # processing the session/new response, before the back-to-back update in
        # the same read buffer is validated.
        assert acp.session_id == "s1"
        result = await acp.request(
            "session/prompt", {"sessionId": "s1", "prompt": [{"type": "text", "text": "hi"}]}, 3
        )
        assert result["stopReason"] == "end_turn"
        assert acp.text == "early"
    finally:
        await acp.aclose()
        await stop(process)


async def test_request_timeout_is_interrupted_without_retry(tmp_path):
    body = (
        "import json,sys,time\n"
        + HANDSHAKE
        + """
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("method") == "authenticate":
        time.sleep(10)
    result = handshake(msg)
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
"""
    )
    process = await spawn_server(tmp_path, body)
    acp = client(process)
    acp.start()
    try:
        await acp.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}}, 3)
        with pytest.raises(UncertainExecution) as caught:
            await acp.request("authenticate", {"methodId": "cached_token"}, 0.2)
        assert caught.value.code == "agent_interrupted"
    finally:
        await acp.aclose()
        await stop(process)


@pytest.fixture(autouse=True)
def no_managed_profile(monkeypatch):
    monkeypatch.setattr(
        "kirabridge.agent_manager.opencode_acp._managed_configuration_present", lambda: False
    )


async def execute_acp(tmp_path, executable, *, timeout=3.0):
    running, progress = [], []

    async def on_running(value):
        running.append(value)

    async def on_progress(value):
        progress.append(value)

    adapter = OpenCodeACPAdapter(TerminalManager())
    result = await adapter.execute(
        {"id": "opencode-acp-test", "principal": "owner"},
        AgentInput(agent="opencode", prompt="hi", cwd=str(tmp_path), timeout=timeout),
        AgentConfig(kind="opencode_acp", executable=executable, model="opencode/test-free"),
        [str(tmp_path)],
        on_running,
        on_progress,
    )
    return result, running, progress


def acp_cli(tmp_path, body):
    path = tmp_path / "opencode-acp-fixture"
    path.write_text(f"#!{sys.executable}\n" + body)
    path.chmod(0o700)
    return str(path)


async def test_opencode_acp_adapter_completes_a_text_only_turn(tmp_path):
    body = (
        HANDSHAKE
        + """
import json,sys
for line in sys.stdin:
    msg = json.loads(line)
    result = handshake(msg)
    if msg.get("method") == "session/prompt":
        print(json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "s1",
            "update": {"sessionUpdate": "agent_message_chunk",
                       "content": {"type": "text", "text": "Harmless answer"}},
        }}), flush=True)
        result = {"stopReason": "end_turn"}
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
"""
    )
    result, running, progress = await execute_acp(tmp_path, acp_cli(tmp_path, body))
    assert result["success"]
    assert result["text"] == "Harmless answer"
    assert result["evidence"]["adapter"] == "opencode_acp"
    assert result["evidence"]["session_id"] == "s1"
    assert result["evidence"]["local_tools_enabled"] is False
    assert not result["project_completion_verified"]
    assert running == [{"agent": "opencode", "session_id": "s1", "event": "agent_message_chunk"}]


async def test_opencode_acp_adapter_keeps_isolated_profile_until_process_end(tmp_path):
    body = (
        HANDSHAKE
        + """
import json,sys,os
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("method") == "initialize":
        # The isolated XDG profile must still exist while the server is running.
        assert os.path.isdir(os.environ["XDG_CONFIG_HOME"]), "profile deleted before initialize"
    result = handshake(msg)
    if msg.get("method") == "session/prompt":
        print(json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "s1",
            "update": {"sessionUpdate": "agent_message_chunk",
                       "content": {"type": "text", "text": "ok"}},
        }}), flush=True)
        result = {"stopReason": "end_turn"}
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
"""
    )
    result, _, _ = await execute_acp(tmp_path, acp_cli(tmp_path, body))
    assert result["success"] and result["text"] == "ok"


async def test_opencode_acp_adapter_wrong_session_is_unknown(tmp_path):
    body = (
        HANDSHAKE
        + """
import json,sys
for line in sys.stdin:
    msg = json.loads(line)
    result = handshake(msg)
    if msg.get("method") == "session/prompt":
        print(json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "s2",
            "update": {"sessionUpdate": "agent_message_chunk",
                       "content": {"type": "text", "text": "wrong"}},
        }}), flush=True)
        result = {"stopReason": "end_turn"}
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
"""
    )
    with pytest.raises(UncertainExecution) as caught:
        await execute_acp(tmp_path, acp_cli(tmp_path, body))
    assert caught.value.code == "agent_identity"


async def test_opencode_acp_adapter_disconnect_during_prompt_is_unknown(tmp_path):
    body = (
        HANDSHAKE
        + """
import json,sys
for line in sys.stdin:
    msg = json.loads(line)
    result = handshake(msg)
    if msg.get("method") == "session/prompt":
        sys.exit(0)
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
"""
    )
    with pytest.raises(UncertainExecution) as caught:
        await execute_acp(tmp_path, acp_cli(tmp_path, body))
    assert caught.value.code == "agent_disconnected"
