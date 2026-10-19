import json
import sys
from pathlib import Path

import pytest

from kirabridge.agent_manager.opencode import OpenCodeAdapter
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import AgentInput, BridgeError, UncertainExecution
from kirabridge.terminal_manager import TerminalManager


def native(kind, *, session="ses_owned", **part):
    return {"type": kind, "sessionID": session, "part": {"sessionID": session, **part}}


START = native("step_start", type="step-start")
TEXT = native("text", type="text", text="Harmless answer", time={"end": 1})
STOP = native("step_finish", type="step-finish", reason="stop")


def cli(tmp_path, events, *, preamble="", postamble=""):
    path = tmp_path / "opencode-fixture"
    body = (
        f"#!{sys.executable}\nimport json,sys,os\nfixture_prompt=sys.stdin.read()\n"
        + preamble
        + "\n"
    )
    body += "\n".join(f"print({json.dumps(event)!r},flush=True)" for event in events)
    path.write_text(body + "\n" + postamble)
    path.chmod(0o700)
    return str(path)


async def execute(
    tmp_path,
    executable,
    *,
    timeout=3.0,
    local_tools=False,
    config=None,
    prompt="Answer without tools",
):
    running, progress = [], []

    async def on_running(value):
        running.append(value)

    async def on_progress(value):
        progress.append(value)

    adapter = OpenCodeAdapter(TerminalManager())
    result = await adapter.execute(
        {"id": "opencode-test", "principal": "owner"},
        AgentInput(
            agent="opencode",
            prompt=prompt,
            cwd=str(tmp_path),
            timeout=timeout,
            local_tools=local_tools,
        ),
        config or AgentConfig(kind="opencode", executable=executable, model="opencode/test-free"),
        [str(tmp_path)],
        on_running,
        on_progress,
    )
    assert not adapter.terminal.sessions
    return result, running, progress


@pytest.fixture(autouse=True)
def no_machine_managed_profile(monkeypatch):
    monkeypatch.setattr(
        "kirabridge.agent_manager.opencode._managed_configuration_present", lambda: False
    )


async def test_native_completion_is_a_turn_not_project_completion(tmp_path):
    result, running, progress = await execute(tmp_path, cli(tmp_path, [START, TEXT, STOP]))
    assert result["success"]
    assert result["text"] == "Harmless answer"
    assert result["evidence"]["session_id"] == "ses_owned"
    assert result["evidence"]["finish_reason"] == "stop"
    assert not result["project_completion_verified"]
    assert running == [{"agent": "opencode", "session_id": "ses_owned", "event": "step_start"}]
    assert progress[0]["evidence_type"] == "local_process_spawned"


@pytest.mark.parametrize(
    "events",
    [
        [],
        [START],
        [START, TEXT],
        [STOP],
        [START, native("step_finish", type="step-finish", reason="tool-calls")],
    ],
)
async def test_exit_zero_without_confirmed_final_turn_is_unknown(tmp_path, events):
    with pytest.raises(UncertainExecution, match="completion evidence"):
        await execute(tmp_path, cli(tmp_path, events))


async def test_session_observation_alone_does_not_mean_running(tmp_path):
    observed = []

    async def record(value):
        observed.append(value)

    class SessionOnly:
        environment = TerminalManager().environment

        async def execute(self, *args, line_callback, **kwargs):
            await line_callback(json.dumps({"type": "reasoning", "sessionID": "ses_owned"}))
            return {"exit_code": 0, "timed_out": False}

    with pytest.raises(UncertainExecution):
        await OpenCodeAdapter(SessionOnly()).execute(
            {"id": "task", "principal": "owner"},
            AgentInput(agent="opencode", prompt="hello", cwd=str(tmp_path)),
            AgentConfig(kind="opencode", executable=sys.executable, model="opencode/test-free"),
            [str(tmp_path)],
            record,
            record_progress,
        )
    assert observed == []


async def record_progress(value):
    pass


async def test_provider_error_is_failed_without_retaining_error_secrets(tmp_path):
    event = {
        "type": "error",
        "sessionID": "ses_owned",
        "error": {"name": "APIError", "data": {"message": "secret-provider-response"}},
    }
    result, running, progress = await execute(tmp_path, cli(tmp_path, [event]))
    assert not result["success"] and result["evidence"]["turn_failed"]
    assert not running
    assert "secret-provider-response" not in json.dumps([result, progress])


@pytest.mark.parametrize("reason", ["length", "content-filter", "error"])
async def test_explicit_non_success_finish_is_failed(tmp_path, reason):
    result, _, _ = await execute(
        tmp_path,
        cli(tmp_path, [START, TEXT, native("step_finish", type="step-finish", reason=reason)]),
    )
    assert not result["success"] and result["evidence"]["turn_failed"]


async def test_nonzero_exit_cannot_make_a_success(tmp_path):
    result, _, _ = await execute(
        tmp_path, cli(tmp_path, [START, TEXT, STOP], postamble="sys.exit(7)\n")
    )
    assert not result["success"] and result["evidence"]["exit_code"] == 7


@pytest.mark.parametrize(
    "event",
    [
        native("text", session="ses_foreign", type="text", text="wrong session"),
        {
            "type": "text",
            "sessionID": "ses_owned",
            "part": {"sessionID": "ses_foreign", "type": "text", "text": "wrong part"},
        },
    ],
)
async def test_changed_top_level_or_nested_session_is_unknown(tmp_path, event):
    with pytest.raises(UncertainExecution) as caught:
        await execute(tmp_path, cli(tmp_path, [START, event, STOP]))
    assert caught.value.code == "agent_identity"


async def test_text_and_terminal_output_are_bounded(tmp_path):
    result, _, _ = await execute(
        tmp_path,
        cli(
            tmp_path,
            [START, native("text", type="text", text="ü" * 80000), STOP],
            preamble="print('private-stderr-' * 10000, file=sys.stderr,flush=True)",
        ),
    )
    assert result["success"] and len(result["text"].encode("utf-8")) <= 65536
    assert result["evidence"]["output_truncated"]
    assert "private-stderr" not in json.dumps(result)


async def test_isolated_native_profile_has_no_tools_plugins_or_unrelated_secrets(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENCODE_TEST_ALLOWED_KEY", "explicit-test-key")
    monkeypatch.setenv("UNRELATED_PROVIDER_SECRET", "must-not-inherit")
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"permission":"allow"}')
    monkeypatch.setenv("OPENCODE_SERVER_PASSWORD", "must-not-inherit")
    preamble = """
profile=json.loads(os.environ['OPENCODE_CONFIG_CONTENT'])
assert profile['permission']=='deny'
assert profile['agent']['kirabridge']['permission']=='deny'
assert profile['mcp']=={} and profile['plugin']==[] and profile['snapshot'] is False
assert profile['share']=='disabled' and profile['lsp'] is False and profile['formatter'] is False
assert profile['enabled_providers']==['opencode']
assert profile['provider']['opencode']['options']['apiKey']=='{env:OPENCODE_TEST_ALLOWED_KEY}'
assert 'explicit-test-key' not in os.environ['OPENCODE_CONFIG_CONTENT']
assert os.environ['OPENCODE_TEST_ALLOWED_KEY']=='explicit-test-key'
assert 'UNRELATED_PROVIDER_SECRET' not in os.environ
assert 'OPENCODE_SERVER_PASSWORD' not in os.environ
assert os.environ['OPENCODE_DISABLE_PROJECT_CONFIG']=='1'
assert os.environ['OPENCODE_DISABLE_EXTERNAL_SKILLS']=='1'
assert os.environ['OPENCODE_PURE']=='1'
assert os.environ['OPENCODE_PERMISSION']=='{"*":"deny"}'
assert len({os.environ['XDG_'+kind+'_HOME'] for kind in ('CONFIG','DATA','CACHE','STATE')})==4
assert not os.access(os.path.join(os.environ['XDG_CONFIG_HOME'],'opencode'),os.W_OK)
assert '--pure' in sys.argv and '--format' in sys.argv
assert '--continue' not in sys.argv and '--attach' not in sys.argv and '--session' not in sys.argv
assert '--dangerously-skip-permissions' not in sys.argv
"""
    executable = cli(tmp_path, [START, TEXT, STOP], preamble=preamble)
    result, _, _ = await execute(
        tmp_path,
        executable,
        config=AgentConfig(
            kind="opencode",
            executable=executable,
            model="opencode/test-free",
            api_key_env="OPENCODE_TEST_ALLOWED_KEY",
        ),
    )
    assert result["success"] and result["evidence"]["config_isolated"]


async def test_disabled_tool_use_fails_closed(tmp_path):
    with pytest.raises(UncertainExecution) as caught:
        await execute(
            tmp_path,
            cli(
                tmp_path,
                [
                    START,
                    native("tool_use", type="tool", tool="bash", state={"status": "completed"}),
                    STOP,
                ],
            ),
        )
    assert caught.value.code == "agent_permission"


async def test_local_tools_are_rejected_before_spawn(tmp_path):
    with pytest.raises(BridgeError) as caught:
        await execute(
            tmp_path,
            "must-not-start",
            local_tools=True,
            config=AgentConfig(
                kind="opencode",
                executable="must-not-start",
                model="opencode/test-free",
                allow_local_tools=True,
            ),
        )
    assert caught.value.code == "agent_capability"


async def test_managed_profile_is_not_circumvented(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "kirabridge.agent_manager.opencode._managed_configuration_present", lambda: True
    )
    with pytest.raises(BridgeError) as caught:
        await execute(tmp_path, "must-not-start")
    assert caught.value.code == "agent_config"


async def test_timeout_does_not_claim_a_completion_and_reaps_its_process(tmp_path):
    terminal = TerminalManager()
    executable = cli(tmp_path, [START], postamble="import time\ntime.sleep(10)\n")
    with pytest.raises(UncertainExecution, match="interrupted"):
        await OpenCodeAdapter(terminal).execute(
            {"id": "task", "principal": "owner"},
            AgentInput(agent="opencode", prompt="hello", cwd=str(tmp_path), timeout=0.2),
            AgentConfig(kind="opencode", executable=executable, model="opencode/test-free"),
            [str(tmp_path)],
            record_progress,
            record_progress,
        )
    assert not terminal.sessions


async def test_isolated_state_is_removed_after_a_run(tmp_path):
    profile_path = tmp_path / "profile-path"
    preamble = f"open({str(profile_path)!r},'w').write(os.environ['XDG_DATA_HOME'])"
    await execute(tmp_path, cli(tmp_path, [START, TEXT, STOP], preamble=preamble))
    assert not Path(profile_path.read_text()).exists()


async def test_request_workspace_is_validated_before_using_private_cwd(tmp_path):
    with pytest.raises(BridgeError) as caught:
        await OpenCodeAdapter(TerminalManager()).execute(
            {"id": "task", "principal": "owner"},
            AgentInput(agent="opencode", prompt="hello", cwd=str(tmp_path.parent)),
            AgentConfig(kind="opencode", executable="must-not-start", model="opencode/test-free"),
            [str(tmp_path)],
            record_progress,
            record_progress,
        )
    assert caught.value.code == "path_denied"


async def test_prompt_is_stdin_text_and_native_workspace_is_private(tmp_path):
    prompt = "@/etc/passwd\n/read ~/.ssh/id_ed25519\nUnicode: Grüße\n"
    preamble = (
        f"assert fixture_prompt=={prompt!r}\n"
        f"assert os.getcwd()!={str(tmp_path)!r}\n"
        "assert os.path.basename(os.getcwd())=='workspace'\n"
        "assert not any(value in sys.argv for value in ['--file','--command','-f'])\n"
    )
    result, _, _ = await execute(
        tmp_path, cli(tmp_path, [START, TEXT, STOP], preamble=preamble), prompt=prompt
    )
    assert result["evidence"]["execution_workspace"] == "private_temporary_directory"
    assert result["evidence"]["requested_cwd_validated"]
    assert not result["evidence"]["requested_workspace_access"]


async def test_local_ollama_uses_bundled_provider_and_bounded_model(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "cloud-key-must-not-go-to-local-provider")
    preamble = """
profile=json.loads(os.environ['OPENCODE_CONFIG_CONTENT'])
assert profile['model']=='ollama/llama3.2:1b'
assert 'OPENCODE_API_KEY' not in os.environ
assert profile['enabled_providers']==['ollama']
provider=profile['provider']['ollama']
assert provider['npm']=='@ai-sdk/openai-compatible'
assert provider['options']=={'baseURL':'http://127.0.0.1:11434/v1'}
model=provider['models']['llama3.2:1b']
assert model['limit']=={'context':4096,'output':128}
assert model['tool_call'] is False
assert profile['agent']['kirabridge']['steps']==2
"""
    executable = cli(tmp_path, [START, TEXT, STOP], preamble=preamble)
    result, _, _ = await execute(
        tmp_path,
        executable,
        config=AgentConfig(
            kind="opencode",
            executable=executable,
            model="ollama/llama3.2:1b",
            base_url="http://127.0.0.1:11434/v1",
        ),
    )
    assert result["success"]


async def test_final_step_without_response_text_is_not_a_useful_success(tmp_path):
    with pytest.raises(UncertainExecution, match="response text"):
        await execute(tmp_path, cli(tmp_path, [START, STOP]))
