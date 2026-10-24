import json

import pytest

from kirabridge.agent_manager import CodexAdapter
from kirabridge.agent_manager.full_access import FullAccessAdapter
from kirabridge.bridge_core.config import AgentConfig, Config
from kirabridge.bridge_core.models import AgentInput


class RecordingTerminal:
    def __init__(self, events):
        self.events = events
        self.environment = {"PATH": "/usr/bin:/bin"}
        self.call = None

    async def execute(self, task_id, principal, args, roots, executables, running, **kw):
        self.call = {"args": args, "env": kw["env"]}
        await running({"pid": 123})
        for event in self.events:
            await kw["line_callback"](json.dumps(event))
        return {"pid": 123, "exit_code": 0, "timed_out": False, "terminated": False}


async def observe(value):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,events",
    [
        (
            "claude_code",
            [
                {"type": "system", "subtype": "init", "session_id": "claude-test"},
                {
                    "type": "assistant",
                    "session_id": "claude-test",
                    "message": {"content": [{"type": "tool_use"}]},
                },
                {
                    "type": "result",
                    "session_id": "claude-test",
                    "subtype": "success",
                    "is_error": False,
                    "result": "ok",
                },
            ],
        ),
        (
            "gemini_cli",
            [
                {"type": "init", "session_id": "gemini-test"},
                {"type": "tool_use", "tool_name": "mcp__kirabridge__message_send"},
                {"type": "message", "role": "assistant", "content": "ok"},
                {"type": "result", "status": "success"},
            ],
        ),
        (
            "opencode",
            [
                {
                    "type": "step_start",
                    "sessionID": "opencode-test",
                    "part": {"type": "step-start"},
                },
                {"type": "tool_use", "sessionID": "opencode-test", "part": {"type": "tool"}},
                {
                    "type": "text",
                    "sessionID": "opencode-test",
                    "part": {"type": "text", "text": "ok"},
                },
                {
                    "type": "step_finish",
                    "sessionID": "opencode-test",
                    "part": {"type": "step-finish", "reason": "stop"},
                },
            ],
        ),
        (
            "copilot_cli",
            [
                {"type": "session.start", "data": {"sessionId": "copilot-test"}},
                {"type": "tool.execution_start", "data": {}},
                {"type": "assistant.message", "data": {"content": "ok"}},
                {"type": "result", "sessionId": "copilot-test", "exitCode": 0},
            ],
        ),
    ],
)
async def test_native_full_profiles_enable_tools_and_bridge_without_false_failures(
    tmp_path, kind, events
):
    terminal = RecordingTerminal(events)
    adapter = FullAccessAdapter(terminal, "/private/config.toml")
    config = AgentConfig(
        kind=kind, executable="/bin/echo", bridge_tools=True, allow_local_tools=True
    )
    args = AgentInput(agent="worker", prompt="use the bridge", cwd=str(tmp_path))
    result = await adapter.execute(
        {"id": "test", "principal": "local"}, args, config, [str(tmp_path)], observe, observe
    )
    assert result["success"] and result["text"] == "ok"
    assert result["evidence"]["mcp_servers_enabled"]
    assert terminal.call["args"].cwd == str(tmp_path)
    command = terminal.call["args"].argv
    assert "--deny-tool=*" not in command and "--safe-mode" not in command
    if kind == "claude_code":
        assert command[command.index("--permission-mode") + 1] == "bypassPermissions"
        assert "kirabridge" in command[command.index("--mcp-config") + 1]
    if kind == "copilot_cli":
        assert "--allow-all" in command and "--additional-mcp-config" in command
    if kind == "opencode":
        settings = json.loads(terminal.call["env"]["OPENCODE_CONFIG_CONTENT"])
        assert settings["permission"] == "allow" and settings["mcp"]["kirabridge"]["enabled"]


@pytest.mark.asyncio
async def test_codex_explicit_full_profile_has_real_bridge_tools(tmp_path):
    terminal = RecordingTerminal(
        [
            {"type": "thread.started", "thread_id": "00000000-0000-0000-0000-000000000001"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "ok"}},
            {"type": "turn.completed"},
        ]
    )
    source = Config()
    source._source_path = "/private/config.toml"
    adapter = CodexAdapter(terminal, source)
    profile = AgentConfig(
        kind="codex", executable="/bin/echo", sandbox_mode="danger-full-access", bridge_tools=True
    )
    args = AgentInput(agent="codex", prompt="use bridge", cwd=str(tmp_path))
    result = await adapter.execute(
        {"id": "test", "principal": "local"}, args, profile, [str(tmp_path)], observe, observe
    )
    command = terminal.call["args"].argv
    assert result["evidence"]["mcp_servers_enabled"]
    assert "mcp_servers={}" not in command
    assert any("mcp_servers.kirabridge.command=" in value for value in command)
    assert "danger-full-access" in command
