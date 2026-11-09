"""Claude Code coordinator roles (BP-CLI-01) with deterministic CLI fixtures.

Fixtures are not a live acceptance: no real model turn was started.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from test_agents import fake_cli
from test_autonext import scenario, until  # noqa: F401
from test_autonext_coordinator import configure as configure_codex
from test_mcp import http_bridge  # noqa: F401

from kirabridge.agent_manager.claude_headless import ClaudeHeadlessAdapter
from kirabridge.autonext.coordinator import CoordinatedAutoNext
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import AgentInput, BridgeError, UncertainExecution
from kirabridge.cli_adapters import adapter_for
from kirabridge.cli_adapters.claude import probe, quota_evidence

spec = importlib.util.spec_from_file_location(
    "loop_claude", Path(__file__).parents[1] / "scripts/bigplan_loop.py"
)
loop = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = loop
spec.loader.exec_module(loop)

SESSION = "b76c50c8-a8e8-4224-bb00-d18836589bce"
WORKSPACE = str(Path(__file__).resolve().parent)
SHA = "a" * 64


class Terminal:
    def __init__(self, events, *, exit_code=0, timed_out=False):
        self.environment = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}
        self.events = events
        self.result = {"exit_code": exit_code, "timed_out": timed_out, "terminated": False}
        self.calls = []

    async def execute(self, task_id, principal, args, roots, executables, spawned, **kwargs):
        self.calls.append((args, kwargs))
        await spawned({"pid": 1})
        for event in self.events:
            await kwargs["line_callback"](json.dumps(event))
        return self.result


def stream(output=None, *, tools=("Read", "Grep", "Glob"), blocks=(), subtype="success"):
    events = [{"type": "system", "subtype": "init", "session_id": SESSION, "tools": list(tools)}]
    if blocks:
        events.append(
            {
                "type": "assistant",
                "session_id": SESSION,
                "message": {"content": list(blocks)},
            }
        )
    events.append(
        {
            "type": "result",
            "subtype": subtype,
            "is_error": subtype != "success",
            "session_id": SESSION,
            "structured_output": output,
        }
    )
    return events


VERDICT = {"verdict": "pass", "source_sha256": SHA, "summary": "ok"}
TURN = {"kirabridge_team": "1", "result": "DONE", "actions": []}


async def run(role, events, *, sandbox="read-only", terminal=None, **config):
    terminal = terminal or Terminal(events)
    cfg = AgentConfig(
        kind="claude_verify" if role == "verifier" else "claude_worker",
        executable="/usr/local/bin/claude",
        api_key_env="ANTHROPIC_API_KEY",
        sandbox_mode=sandbox,
        **config,
    )
    progress = []

    async def record(value):
        progress.append(value)

    result = await ClaudeHeadlessAdapter(terminal, role).execute(
        {"id": "t1", "principal": "codex_verify"},
        AgentInput(agent="x", prompt='KiraBridge team turn\n{"a":"@b"}', cwd=WORKSPACE),
        cfg,
        [WORKSPACE],
        record,
        record,
    )
    return result, terminal


async def test_verifier_success_is_read_only_and_strict(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result, terminal = await run("verifier", stream(VERDICT))
    argv, options = terminal.calls[0]
    argv = argv.argv
    assert argv[argv.index("--tools") + 1] == "Read,Grep,Glob"
    denied = argv[argv.index("--disallowedTools") + 1].split(",")
    assert {"Bash", "Edit", "Write", "NotebookEdit"} <= set(denied)
    assert "--dangerously-skip-permissions" not in argv
    assert "\\u0040" in options["stdin"].decode() and "@" not in options["stdin"].decode()
    assert json.loads(json.loads(result["text"])["result"]) == VERDICT
    assert result["evidence"]["write_tools_enabled"] is False
    assert result["evidence"]["sandbox_mode"] == "read-only"


@pytest.mark.parametrize("name", ["Write", "Edit", "Bash", "NotebookEdit"])
async def test_verifier_write_attempt_is_rejected(name, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    block = {"type": "tool_use", "name": name, "input": {"file_path": WORKSPACE + "/x"}}
    with pytest.raises(BridgeError) as error:
        await run("verifier", stream(VERDICT, blocks=[block]))
    assert error.value.code == "agent_write_denied"


async def test_verifier_init_with_write_tool_is_rejected(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(UncertainExecution):
        await run("verifier", stream(VERDICT, tools=("Read", "Write")))


async def test_verifier_cannot_be_configured_writable(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(BridgeError) as error:
        await run("verifier", stream(VERDICT), sandbox="workspace-write")
    assert error.value.code == "agent_tools_denied"


async def test_worker_writes_only_inside_fixed_worktree(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    tools = ("Read", "Grep", "Glob", "Edit", "Write")
    inside = {"type": "tool_use", "name": "Write", "input": {"file_path": WORKSPACE + "/o.txt"}}
    result, terminal = await run(
        "worker", stream(TURN, tools=tools, blocks=[inside]), sandbox="workspace-write"
    )
    assert json.loads(result["text"]) == TURN
    assert terminal.calls[0][0].argv[terminal.calls[0][0].argv.index("--tools") + 1] == (
        "Read,Grep,Glob,Edit,Write"
    )
    outside = {"type": "tool_use", "name": "Write", "input": {"file_path": "/etc/passwd"}}
    with pytest.raises(BridgeError):
        await run("worker", stream(TURN, tools=tools, blocks=[outside]), sandbox="workspace-write")
    shell = {"type": "tool_use", "name": "Bash", "input": {"command": "id"}}
    with pytest.raises(BridgeError):
        await run("worker", stream(TURN, tools=tools, blocks=[shell]), sandbox="workspace-write")


async def test_read_only_worker_has_no_write_tools(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _, terminal = await run("worker", stream(TURN))
    assert terminal.calls[0][0].argv[terminal.calls[0][0].argv.index("--tools") + 1] == (
        "Read,Grep,Glob"
    )


@pytest.mark.parametrize(
    "output", [None, {"verdict": "pass"}, {**VERDICT, "extra": 1}, {**VERDICT, "verdict": "maybe"}]
)
async def test_non_strict_verdict_is_unknown(output, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(UncertainExecution):
        await run("verifier", stream(output))


async def test_timeout_is_unknown_not_failed(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(UncertainExecution) as error:
        await run("worker", stream(TURN), terminal=Terminal([], timed_out=True))
    assert error.value.code == "agent_timeout"


async def test_native_login_error_is_failed_without_replay_text(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(BridgeError) as error:
        await run("worker", stream(None, subtype="error_during_execution"))
    assert error.value.code == "agent_failed"


async def test_api_key_billing_is_refused_before_spawn(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-be-used")
    terminal = Terminal(stream(TURN))
    with pytest.raises(BridgeError) as error:
        await run("worker", None, terminal=terminal)
    assert error.value.code == "agent_billing_unknown" and not terminal.calls


# ---- version / login / quota evidence, no model cost ----


def runner(version="2.1.319", status=None, code=0):
    def run_(argv, env):
        assert "-p" not in argv and "--print" not in argv  # never a model turn
        if argv[1] == "--version":
            return 0, version + " (Claude Code)\n"
        return code, json.dumps(status if status is not None else {})

    return run_


LOGGED_IN = {
    "loggedIn": True,
    "authMethod": "claude.ai",
    "subscriptionType": "pro",
    "email": "x@example.invalid",
}


def test_probe_reads_version_and_login_without_identity():
    state = probe("/c", runner=runner(status=LOGGED_IN), environ={"PATH": "/bin"})
    assert state["version"] == "2.1.319" and state["logged_in"] is True
    assert state["usage"] == "unknown"
    assert "example.invalid" not in json.dumps(state)


def test_quota_is_unknown_never_a_percentage():
    evidence = quota_evidence("/c", runner=runner(status=LOGGED_IN), environ={"PATH": "/bin"})
    assert evidence["usage"] == "unknown" and evidence["subscription_confirmed"] is True
    assert not any("percent" in key for key in evidence)


@pytest.mark.parametrize(
    "status,environ",
    [
        ({"loggedIn": False}, {}),
        ({}, {}),
        ({"loggedIn": True, "authMethod": "api_key"}, {}),
        (LOGGED_IN, {"ANTHROPIC_API_KEY": "k"}),
    ],
)
def test_missing_login_or_api_key_route_stops(status, environ):
    with pytest.raises(RuntimeError):
        quota_evidence("/c", runner=runner(status=status), environ=environ)


async def test_grant_needs_explicit_user_acknowledgement(monkeypatch):
    profile = {
        "coordinator_cli": "claude",
        "claude": "/c",
        "claude_quota_unknown_acknowledged": False,
    }
    with pytest.raises(RuntimeError, match="acknowledg"):
        await loop.grant_quota(profile)
    monkeypatch.setattr(loop, "quota_evidence", lambda exe: {"usage": "unknown", "exe": exe})
    assert await loop.grant_quota({**profile, "claude_quota_unknown_acknowledged": True}) == {
        "usage": "unknown",
        "exe": "/c",
    }


def test_cli_module_is_registered_but_claims_no_terminal_capability():
    adapter = adapter_for("claude")
    assert adapter.name == "claude" and not any(vars(adapter.capabilities).values())
    assert adapter.observe("", None)["ready"] is False


# ---- profile selection is opt-in ----


def base_profile(tmp_path, **extra):
    return loop.LoopProfile.model_validate(
        {
            "cwd": str(tmp_path),
            "state_dir": str(tmp_path / "s"),
            "search_path": ["/usr/bin"],
            "codex": "/usr/bin/codex",
            "grok": "/usr/bin/grok",
            "workspace": str(tmp_path),
            "threaddesk_source": str(tmp_path),
            "report_cli": "/usr/bin/true",
            "instance": "t",
            "board_id": "b",
            **extra,
        }
    ).model_dump()


def test_default_profile_keeps_codex_agents(tmp_path):
    agents = loop.agent_profiles(base_profile(tmp_path))
    assert agents["codex"]["kind"] == agents["codex_verify"]["kind"] == "codex"
    assert agents["codex"]["api_key_env"] == "CODEX_API_KEY"


def test_claude_profile_selects_worker_and_read_only_verifier(tmp_path):
    profile = base_profile(tmp_path, coordinator_cli="claude", claude="/usr/local/bin/claude")
    agents = loop.agent_profiles(profile)
    assert agents["codex"]["kind"] == "claude_worker"
    assert agents["codex_verify"] == {
        "kind": "claude_verify",
        "executable": "/usr/local/bin/claude",
        "sandbox_mode": "read-only",
        "api_key_env": "ANTHROPIC_API_KEY",
    }
    assert agents["grok"]["kind"] == "grok_structured"  # optional review unchanged


@pytest.mark.parametrize("extra", [{}, {"claude": "relative/claude"}])
def test_claude_profile_requires_absolute_executable(tmp_path, extra):
    with pytest.raises(ValueError):
        base_profile(tmp_path, coordinator_cli="claude", **extra)


# ---- full coordinator chain with deterministic Claude fixtures ----

CLAUDE = """import json,sys,time,pathlib
MODE="__MODE__"
log=pathlib.Path("__LOG__")
prompt=sys.stdin.read(); data=json.loads(prompt.split("\\n",1)[1])
verify="source_sha256" in data
log.open("a").write(("verify" if verify else "work")+"\\n")
print(json.dumps({"type":"system","subtype":"init","session_id":"s1","tools":["Read","Grep","Glob"]}),flush=True)
if MODE=="login":
 print(json.dumps({"type":"result","subtype":"error_during_execution","is_error":True,
  "session_id":"s1","result":"Not logged in"}),flush=True); sys.exit(1)
if MODE=="slow" and not verify: time.sleep(30)
if verify:
 v="fail" if MODE=="negative" else "pass"
 out={"verdict":v,"source_sha256":data["source_sha256"],"summary":"fixture"}
else:
 out={"kirabridge_team":"1","result":"DONE:"+data["task_id"],"actions":[]}
if verify and MODE=="write":
 print(json.dumps({"type":"assistant","session_id":"s1","message":{"content":[
  {"type":"tool_use","name":"Write","input":{"file_path":data["cwd"]+"/x"}}]}}),flush=True)
print(json.dumps({"type":"result","subtype":"success","is_error":False,"session_id":"s1",
 "structured_output":out}),flush=True)
"""


def configure_claude(s, tmp_path, monkeypatch, mode):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    card = configure_codex(s, tmp_path, monkeypatch)
    config = s["config"]
    log = tmp_path / "claude.log"
    directory = tmp_path / "claude-cli"
    directory.mkdir()
    exe = fake_cli(directory, CLAUDE.replace("__MODE__", mode).replace("__LOG__", str(log)))
    for name, kind, sandbox in (
        ("codex", "claude_worker", "read-only"),
        ("codex_verify", "claude_verify", "read-only"),
    ):
        config.agents[name] = AgentConfig(
            kind=kind, executable=exe, api_key_env="ANTHROPIC_API_KEY", sandbox_mode=sandbox
        )
    config.autonext = config.autonext.model_copy(
        update={"budget_state": "user_acknowledged_unknown"}
    )
    s["bridge"].autonext = CoordinatedAutoNext(s["bridge"])
    return card, log


async def test_chain_success_with_claude_worker_and_verifier(scenario, tmp_path, monkeypatch):  # noqa: F811
    s = scenario
    card, log = configure_claude(s, tmp_path, monkeypatch, "ok")
    bridge = s["bridge"]
    await s["start"]()
    await until(lambda: bridge.autonext.inspect()["state"] in {"complete", "stopped"})
    assert bridge.autonext.inspect()["state"] == "complete", bridge.autonext.inspect()
    receipt = bridge.autonext.receipt("codex", card["task_id"])
    assert receipt["coordinator"]["checks"]["passed"] is True
    assert log.read_text().split() == ["work", "verify"]


async def test_negative_verdict_stops_before_checks(scenario, tmp_path, monkeypatch):  # noqa: F811
    s = scenario
    card, _ = configure_claude(s, tmp_path, monkeypatch, "negative")
    bridge = s["bridge"]
    await s["start"]()
    await until(lambda: bridge.autonext.inspect()["state"] == "stopped")
    assert bridge.autonext.inspect()["reason"] == "autonext_review_rejected"
    assert bridge.autonext.receipt("codex", card["task_id"]) is None
    row = bridge.store.db.execute("SELECT checks_state FROM autonext_coordinator").fetchone()
    assert row["checks_state"] == "not_started"


async def test_verifier_write_attempt_stops_without_receipt(scenario, tmp_path, monkeypatch):  # noqa: F811
    s = scenario
    card, _ = configure_claude(s, tmp_path, monkeypatch, "write")
    bridge = s["bridge"]
    await s["start"]()
    await until(lambda: bridge.autonext.inspect()["state"] == "stopped")
    assert bridge.autonext.receipt("codex", card["task_id"]) is None
    assert not (s["root"] / "x").exists()


async def test_missing_login_stops_without_receipt(scenario, tmp_path, monkeypatch):  # noqa: F811
    s = scenario
    card, log = configure_claude(s, tmp_path, monkeypatch, "login")
    bridge = s["bridge"]
    await s["start"]()
    await until(lambda: bridge.autonext.inspect()["state"] == "stopped")
    assert bridge.autonext.receipt("codex", card["task_id"]) is None
    assert log.read_text().split() == ["work"]


async def test_worker_timeout_stays_unknown_and_is_not_replayed(scenario, tmp_path, monkeypatch):  # noqa: F811
    s = scenario
    card, log = configure_claude(s, tmp_path, monkeypatch, "slow")
    bridge = s["bridge"]
    s["config"].team.workers["codex"].timeout = 1
    await s["start"]()
    await until(lambda: bridge.autonext.inspect()["state"] == "stopped", timeout=20)
    assert bridge.autonext.receipt("codex", card["task_id"]) is None
    await bridge.autonext.stop()
    bridge.autonext = CoordinatedAutoNext(bridge)
    await bridge.autonext.tick()
    assert log.read_text().split() == ["work"]


def test_claude_budget_requires_acknowledged_unknown_and_no_api_key(scenario, monkeypatch):  # noqa: F811
    s = scenario
    config = s["config"]
    config.agents["codex"] = AgentConfig(
        kind="claude_worker", executable=sys.executable, api_key_env="ANTHROPIC_API_KEY"
    )
    manager = CoordinatedAutoNext(s["bridge"])
    s["grant"]([])
    with pytest.raises(BridgeError):  # "available" is not an acknowledged-unknown Claude grant
        manager._budget()
    config.autonext = config.autonext.model_copy(
        update={"budget_state": "user_acknowledged_unknown"}
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    with pytest.raises(BridgeError):
        manager._budget()
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    manager._budget()
