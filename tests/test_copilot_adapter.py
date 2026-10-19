import json
from pathlib import Path

import pytest

from kirabridge.agent_manager.copilot import CopilotCLIAdapter
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import AgentInput, BridgeError, UncertainExecution

SESSION = "6f71c0ae-830f-4016-b0b7-afba2b93caa8"
WORKSPACE = str(Path(__file__).resolve().parent)


class Terminal:
    def __init__(self, events, *, exit_code=0, timed_out=False, terminated=False):
        self.environment = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}
        self.events = events
        self.result = {"exit_code": exit_code, "timed_out": timed_out, "terminated": terminated}
        self.calls = []
        self.isolation = None

    async def execute(self, task_id, principal, args, roots, executables, spawned, **kwargs):
        self.calls.append((task_id, principal, args, roots, executables, kwargs))
        cli_home = Path(kwargs["env"]["COPILOT_HOME"])
        workspace = Path(args.argv[args.argv.index("-C") + 1])
        self.isolation = {
            "config": json.loads((cli_home / "config.json").read_text()),
            "workspace_empty": not list(workspace.iterdir()),
            "cli_home": str(cli_home),
            "workspace": str(workspace),
        }
        await spawned({"pid": 123, "evidence_type": "local_process_spawned"})
        for event in self.events:
            await kwargs["line_callback"](json.dumps(event))
        return self.result


def events():
    return [
        {"type": "session.start", "data": {"sessionId": SESSION}},
        {"type": "assistant.message", "data": {"content": "Hello 🌉"}},
        {"type": "assistant.turn_end", "data": {"turnId": "turn-1"}},
        {"type": "result", "sessionId": SESSION, "exitCode": 0},
    ]


async def execute(terminal, *, local_tools=False, prompt="Test 🌉", cwd=WORKSPACE):
    running, progress = [], []

    async def run(value):
        running.append(value)

    async def record(value):
        progress.append(value)

    result = await CopilotCLIAdapter(terminal).execute(
        {"id": "copilot-test", "principal": "grok"},
        AgentInput(agent="copilot", prompt=prompt, cwd=cwd, local_tools=local_tools),
        AgentConfig(
            kind="copilot_cli",
            executable="/usr/local/bin/copilot",
            api_key_env="COPILOT_GITHUB_TOKEN",
        ),
        [WORKSPACE],
        run,
        record,
    )
    return result, running, progress


async def test_copilot_native_result_uses_fresh_tool_free_workspace(monkeypatch):
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "test-key-never-in-evidence")
    monkeypatch.setenv("OUTSIDE_SECRET", "not-inherited")
    terminal = Terminal(events())
    result, running, progress = await execute(terminal)
    assert result["success"] and result["text"] == "Hello 🌉"
    assert running[0]["event"] == "assistant_message"
    assert progress[0]["evidence_type"] == "local_process_spawned"
    _, _, args, roots, executables, options = terminal.calls[0]
    assert args.cwd == terminal.isolation["workspace"] and roots == [args.cwd]
    assert executables == ["/usr/local/bin/copilot"]
    assert "--available-tools=kirabridge_text_only_no_tools" in args.argv
    assert "--available-tools=" not in args.argv and "--deny-tool=*" in args.argv
    assert "--disable-builtin-mcps" in args.argv and "--no-remote-export" in args.argv
    assert "--no-custom-instructions" in args.argv
    assert "--allow-all" not in args.argv and "--yolo" not in args.argv
    assert options["env"]["COPILOT_GITHUB_TOKEN"] == "test-key-never-in-evidence"
    assert "OUTSIDE_SECRET" not in options["env"]
    assert terminal.isolation["workspace_empty"]
    assert terminal.isolation["config"]["disableAllHooks"]
    assert not Path(terminal.isolation["workspace"]).exists()
    assert "test-key-never-in-evidence" not in json.dumps((result, running, progress))


@pytest.mark.parametrize("values", [events()[:1], events()[:-1], [events()[-1]]])
async def test_copilot_spawn_init_exit_zero_without_turn_is_unknown(values):
    with pytest.raises(UncertainExecution):
        await execute(Terminal(values))


@pytest.mark.parametrize(
    "extra",
    [
        {"type": "session.start", "data": {"sessionId": "foreign"}},
        {"type": "session.resume", "data": {"sessionId": SESSION}},
        {"type": "tool.execution_start", "data": {}},
        {"type": "hook.start", "data": {}},
        {"type": "subagent.started", "data": {}},
        {"type": "assistant.message", "data": {"toolRequests": [{"name": "shell"}]}},
    ],
)
async def test_copilot_rejects_identity_and_disabled_execution(extra):
    values = events()
    values.insert(1, extra)
    with pytest.raises(UncertainExecution):
        await execute(Terminal(values))


async def test_copilot_native_auth_error_is_failed_and_redacted():
    values = [
        {"type": "session.start", "data": {"sessionId": SESSION}},
        {"type": "session.error", "data": {"message": "sensitive-token"}},
        {"type": "result", "sessionId": SESSION, "exitCode": 1},
    ]
    result, running, progress = await execute(Terminal(values, exit_code=1))
    assert not result["success"] and result["text"] == "" and not running
    assert "sensitive-token" not in json.dumps((result, running, progress))


async def test_copilot_rejects_duplicate_results_and_result_identity_change():
    values = events()
    with pytest.raises(UncertainExecution):
        await execute(Terminal(values + [values[-1]]))
    values[-1]["sessionId"] = "foreign"
    with pytest.raises(UncertainExecution):
        await execute(Terminal(values))


async def test_copilot_result_cannot_override_timeout_exit_or_abort():
    result, _, _ = await execute(Terminal(events(), exit_code=1))
    assert not result["success"]
    aborted = events()
    aborted.insert(2, {"type": "session.idle", "data": {"aborted": True}})
    result, _, _ = await execute(Terminal(aborted))
    assert not result["success"]
    with pytest.raises(UncertainExecution) as error:
        await execute(Terminal(events(), timed_out=True))
    assert error.value.code == "agent_timeout"


async def test_copilot_termination_cannot_override_native_success():
    with pytest.raises(UncertainExecution) as error:
        await execute(Terminal(events(), terminated=True))
    assert error.value.code == "agent_timeout"


async def test_copilot_refuses_local_tools_before_spawn():
    terminal = Terminal(events())
    with pytest.raises(BridgeError) as error:
        await execute(terminal, local_tools=True)
    assert error.value.code == "agent_tools_unsupported" and not terminal.calls


async def test_copilot_complete_messages_are_bounded_without_duplicating_deltas():
    values = events()
    values[1]["data"]["content"] = "🌉" * 100000
    values.insert(1, {"type": "assistant.message_delta", "data": {"deltaContent": "partial"}})
    result, _, _ = await execute(Terminal(values))
    assert len(result["text"].encode()) <= 65536
    assert "partial" not in result["text"]


async def test_copilot_file_mentions_and_commands_remain_literal_text():
    terminal = Terminal(events())
    prompt = "/unknown-command @/outside/private-file \n user@example.test"
    await execute(terminal, prompt=prompt)
    argv = terminal.calls[0][2].argv
    wire_text = argv[argv.index("--prompt") + 1]
    assert not wire_text.startswith("/") and "@" not in wire_text
    assert json.loads(wire_text.split("\n", 1)[1]) == prompt


async def test_copilot_validates_original_directory_before_isolation(tmp_path):
    terminal = Terminal(events())
    with pytest.raises(BridgeError) as error:
        await execute(terminal, cwd=str(tmp_path))
    assert error.value.code == "path_denied" and not terminal.calls
