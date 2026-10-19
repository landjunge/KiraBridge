import json
from pathlib import Path

import pytest

from kirabridge.agent_manager.claude import ClaudeCodeAdapter
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import AgentInput, BridgeError, UncertainExecution

SESSION = "b76c50c8-a8e8-4224-bb00-d18836589bce"
WORKSPACE = str(Path(__file__).resolve().parent)


class Terminal:
    def __init__(self, events, *, exit_code=0, timed_out=False, terminated=False):
        self.environment = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}
        self.events = events
        self.result = {"exit_code": exit_code, "timed_out": timed_out, "terminated": terminated}
        self.calls = []

    async def execute(self, task_id, principal, args, roots, executables, spawned, **kwargs):
        self.calls.append((task_id, principal, args, roots, executables, kwargs))
        await spawned({"pid": 123, "evidence_type": "local_process_spawned"})
        for event in self.events:
            await kwargs["line_callback"](json.dumps(event))
        return self.result


def events():
    return [
        {"type": "system", "subtype": "init", "session_id": SESSION, "tools": []},
        {
            "type": "assistant",
            "session_id": SESSION,
            "message": {"content": [{"type": "text", "text": "Hello"}]},
        },
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "session_id": SESSION,
            "result": "Hello 🌉",
        },
    ]


async def execute(terminal, *, local_tools=False, config=None, prompt="Test 🌉", cwd=WORKSPACE):
    running, progress = [], []

    async def run(value):
        running.append(value)

    async def record(value):
        progress.append(value)

    result = await ClaudeCodeAdapter(terminal).execute(
        {"id": "claude-test", "principal": "codex"},
        AgentInput(agent="claude", prompt=prompt, cwd=cwd, local_tools=local_tools),
        config
        or AgentConfig(
            kind="claude_code", executable="/usr/local/bin/claude", api_key_env="ANTHROPIC_API_KEY"
        ),
        [WORKSPACE],
        run,
        record,
    )
    return result, running, progress


async def test_claude_native_result_and_text_only_command(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-in-evidence")
    monkeypatch.setenv("OUTSIDE_SECRET", "not-inherited")
    terminal = Terminal(events())
    result, running, progress = await execute(terminal)
    assert result["success"] and result["text"] == "Hello 🌉"
    assert result["evidence"]["session_id"] == SESSION
    assert running[0]["event"] == "assistant_message"
    assert progress[0]["evidence_type"] == "local_process_spawned"
    _, _, args, roots, executables, options = terminal.calls[0]
    assert args.cwd != WORKSPACE and roots == [args.cwd]
    assert not Path(args.cwd).exists()
    assert executables == ["/usr/local/bin/claude"]
    assert args.argv[args.argv.index("--tools") + 1] == ""
    assert args.argv[args.argv.index("--permission-mode") + 1] == "dontAsk"
    assert "--safe-mode" in args.argv and "--strict-mcp-config" in args.argv
    assert "--no-session-persistence" in args.argv
    assert "--dangerously-skip-permissions" not in args.argv
    assert json.loads(options["stdin"].decode().split("\n", 1)[1]) == "Test 🌉"
    assert options["env"]["ANTHROPIC_API_KEY"] == "test-key-never-in-evidence"
    assert "OUTSIDE_SECRET" not in options["env"]
    assert "test-key-never-in-evidence" not in json.dumps((result, running, progress))


async def test_claude_spawn_and_init_do_not_claim_execution():
    terminal = Terminal(events()[:1])
    with pytest.raises(UncertainExecution, match="No native Claude"):
        await execute(terminal)


@pytest.mark.parametrize(
    "change",
    [
        lambda values: values[2].update(session_id="foreign-session"),
        lambda values: values[0].update(tools=["Bash"]),
        lambda values: values[0].update(mcp_servers=[{"name": "foreign"}]),
        lambda values: values[1]["message"].update(content=[{"type": "tool_use"}]),
        lambda values: values.append(values[-1]),
    ],
)
async def test_claude_rejects_identity_or_disabled_capabilities(change):
    values = events()
    change(values)
    with pytest.raises(UncertainExecution):
        await execute(Terminal(values))


async def test_claude_auth_failure_is_failed_without_exposing_raw_errors():
    terminal = Terminal(
        [
            {
                "type": "assistant",
                "session_id": SESSION,
                "error": "authentication_failed",
                "message": {"content": [{"type": "text", "text": "sensitive token-example"}]},
            },
            {
                "type": "result",
                "session_id": SESSION,
                "subtype": "error_during_execution",
                "is_error": True,
                "errors": ["sensitive token-example"],
                "result": "sensitive token-example",
            },
        ],
        exit_code=1,
    )
    result, running, progress = await execute(terminal)
    assert not result["success"] and result["text"] == "" and not running
    assert "sensitive" not in json.dumps((result, running, progress))


async def test_claude_result_cannot_override_timeout_or_nonzero_exit():
    result, _, _ = await execute(Terminal(events(), exit_code=1))
    assert not result["success"] and result["text"] == ""
    with pytest.raises(UncertainExecution) as error:
        await execute(Terminal(events(), timed_out=True))
    assert error.value.code == "agent_timeout"


async def test_claude_termination_cannot_override_native_success():
    with pytest.raises(UncertainExecution) as error:
        await execute(Terminal(events(), terminated=True))
    assert error.value.code == "agent_timeout"


async def test_claude_refuses_local_tools_before_spawn():
    terminal = Terminal(events())
    with pytest.raises(BridgeError) as error:
        await execute(terminal, local_tools=True)
    assert error.value.code == "agent_tools_unsupported" and not terminal.calls


async def test_claude_output_is_bounded():
    values = events()
    values[-1]["result"] = "🌉" * 100000
    result, _, _ = await execute(Terminal(values))
    assert len(result["text"].encode()) <= 65536


async def test_claude_file_mentions_and_commands_remain_literal_text():
    terminal = Terminal(events())
    prompt = "/unknown-command @/outside/private-file \n user@example.test"
    await execute(terminal, prompt=prompt)
    wire_text = terminal.calls[0][-1]["stdin"].decode()
    assert not wire_text.startswith("/") and "@" not in wire_text
    assert json.loads(wire_text.split("\n", 1)[1]) == prompt


async def test_claude_validates_original_directory_before_isolation(tmp_path):
    terminal = Terminal(events())
    with pytest.raises(BridgeError) as error:
        await execute(terminal, cwd=str(tmp_path))
    assert error.value.code == "path_denied" and not terminal.calls
