"""Native structured Grok receipts, with deterministic CLI fixtures only."""

import json
from unittest.mock import AsyncMock

import pytest
from test_agents import fake_cli

from kirabridge.agent_manager.grok_structured import GrokStructuredAdapter
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import AgentInput, BridgeError
from kirabridge.terminal_manager import TerminalManager

SOURCE = "a" * 64
VALID = {
    "text": "commentary and deliberately misleading prose",
    "sessionId": "fixture-session",
    "stopReason": "end_turn",
    "structuredOutput": {"verdict": "pass", "source_sha256": SOURCE, "summary": "fixture reviewed"},
}


async def run_fixture(tmp_path, monkeypatch, payload=VALID, *, exit_code=0, mode="read-only"):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("GROK_STRUCTURED_FIXTURE_KEY", raising=False)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    body = """import json,sys,pathlib,stat
argv=sys.argv[1:]
assert '--prompt-file' in argv and '-p' not in argv
path=pathlib.Path(argv[argv.index('--prompt-file')+1])
assert stat.S_IMODE(path.stat().st_mode)==0o600
assert stat.S_IMODE(path.parent.stat().st_mode)==0o700
assert path.read_text()=='private fixture prompt'
assert 'private fixture prompt' not in '\\n'.join(argv)
assert '--no-auto-update' in argv and '--no-leader' in argv and '--no-subagents' in argv
assert '--disable-web-search' in argv
assert argv[argv.index('--permission-mode')+1]=='dontAsk'
assert [argv[i+1] for i,v in enumerate(argv) if v=='--deny']==['Bash','Edit','MCPTool']
schema=json.loads(argv[argv.index('--json-schema')+1])
assert schema['additionalProperties'] is False
pathlib.Path('prompt-path.json').write_text(json.dumps(str(path)))
"""
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    body += "print(" + repr(raw) + ")\nraise SystemExit(" + str(exit_code) + ")\n"
    executable = fake_cli(tmp_path, body)
    config = AgentConfig(
        kind="grok_structured",
        executable=executable,
        sandbox_mode=mode,
        api_key_env="GROK_STRUCTURED_FIXTURE_KEY",
    )
    args = AgentInput(agent="grok", prompt="private fixture prompt", cwd=str(workspace), timeout=2)
    result = await GrokStructuredAdapter(TerminalManager()).execute(
        {"id": "structured-fixture", "principal": "grok"},
        args,
        config,
        [str(workspace)],
        AsyncMock(),
        AsyncMock(),
    )
    return result, workspace


async def test_structured_verdict_ignores_prose_and_preserves_native_completion(
    tmp_path, monkeypatch
):
    from pathlib import Path

    result, workspace = await run_fixture(tmp_path, monkeypatch)
    assert result["success"] is True
    assert result["evidence"]["adapter"] == "grok_structured"
    assert result["evidence"]["turn_completed"] is True
    assert result["evidence"]["session_id"] == "fixture-session"
    team = json.loads(result["text"])
    assert team["kirabridge_team"] == "1" and team["actions"] == []
    assert json.loads(team["result"]) == VALID["structuredOutput"]
    assert "misleading" not in result["text"]
    assert result["final_message"] == result["text"]
    assert not Path(json.loads((workspace / "prompt-path.json").read_text())).exists()


@pytest.mark.parametrize(
    "payload",
    [
        {**VALID, "stopReason": "max_turns"},
        {**VALID, "sessionId": ""},
        {**VALID, "structuredOutput": json.dumps(VALID["structuredOutput"])},
        {
            "text": json.dumps(VALID["structuredOutput"]),
            "sessionId": "fixture",
            "stopReason": "end_turn",
        },
        {**VALID, "structuredOutput": {**VALID["structuredOutput"], "actions": ["execute"]}},
        json.dumps(json.dumps(VALID)),
        '{"sessionId":"fixture","stopReason":"end_turn","structuredOutput":'
        '{"verdict":"fail","verdict":"pass","source_sha256":"' + SOURCE + '","summary":"x"}}',
    ],
)
async def test_unconfirmed_or_ambiguous_receipts_are_rejected(tmp_path, monkeypatch, payload):
    with pytest.raises(BridgeError) as error:
        await run_fixture(tmp_path, monkeypatch, payload)
    assert error.value.code == "agent_protocol"


async def test_nonzero_native_exit_never_completes_a_turn(tmp_path, monkeypatch):
    with pytest.raises(BridgeError) as error:
        await run_fixture(tmp_path, monkeypatch, exit_code=2)
    assert error.value.code == "agent_failed"


async def test_read_only_profile_is_required_before_native_start(tmp_path, monkeypatch):
    with pytest.raises(BridgeError) as error:
        await run_fixture(tmp_path, monkeypatch, mode="workspace-write")
    assert error.value.code == "agent_tools_denied"
    assert not (tmp_path / "workspace/prompt-path.json").exists()
