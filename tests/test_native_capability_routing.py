"""Native sealed-work routing; all executable/model/login responses are fixtures."""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_autonext import scenario, until  # noqa: F401
from test_autonext_coordinator import configure
from test_coordinator_runtime import runtime as loop
from test_mcp import http_bridge  # noqa: F401

from kirabridge.autonext.continuation import validate_source
from kirabridge.autonext.manager import text_sha
from kirabridge.autonext.models import AutoNextConfig
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import AgentConfig, TeamConfig, TeamWorkerConfig
from kirabridge.bridge_core.models import AgentInput, BridgeError
from kirabridge.capability_routing.hook import DelegationGuard
from kirabridge.capability_routing.native import native_routed_manager
from kirabridge.capability_routing.router import NativeRoutingSettings, Runtime, WorkerRouting
from kirabridge.capability_routing.source import BEGIN, END, ThreadDeskSource
from kirabridge.whiteboard_read import append_whiteboard, read_whiteboard

PROBES = """import sys,json,pathlib
argv=sys.argv[1:]
if '--version' in argv: print('fixture 1.0'); raise SystemExit(0)
if 'login' in argv: print('Logged in using ChatGPT'); raise SystemExit(0)
if 'models' in argv:
 print('You are logged in with grok.com.\\n- fixture-grok'); raise SystemExit(0)
with open('routing-native-argv.jsonl','a') as f: f.write(json.dumps(argv)+'\\n')
"""
STRUCTURED = """import json,pathlib,sys
argv=sys.argv[1:]
prompt=pathlib.Path(argv[argv.index('--prompt-file')+1]).read_text()
data=json.loads(prompt.split('\\n',1)[1])
assert '--json-schema' in argv and '--no-subagents' in argv
assert argv.count('--no-auto-update') == 1
assert '--disable-web-search' in argv and '--no-leader' in argv
assert [argv[i+1] for i,v in enumerate(argv) if v=='--deny']==['Bash','Edit','MCPTool']
print(json.dumps({'sessionId':'fixture-routed-grok','requestId':'fixture-request',
 'stopReason':'end_turn','modelUsage':{'fixture-grok-build':{}},
 'structuredOutput':{'verdict':'pass','source_sha256':data['source_sha256'],'summary':'fixture'}}))
"""


@pytest.fixture
def routed(scenario, tmp_path, monkeypatch, request):  # noqa: F811
    s = scenario
    mode = getattr(request, "param", "read-only")
    write_grant = mode == "workspace-write"
    if isinstance(mode, tuple):
        mode, write_grant = mode
    card = configure(s, tmp_path, monkeypatch, grok=True, main_mode=mode)
    b, cfg = s["bridge"], s["config"]
    cfg.visible_handoffs.enabled = True
    seen = set()
    for name in ("codex", "codex_verify", "grok"):
        agent = cfg.agents[name]
        path = Path(agent.executable)
        if path not in seen:
            body = STRUCTURED if name == "grok" else path.read_text().split("\n", 1)[1]
            path.write_text("#!" + sys.executable + "\n" + PROBES + body)
            seen.add(path)
        agent.model = "fixture-grok" if name == "grok" else "fixture-codex"
        if name == "grok":
            agent.kind = "grok_structured"
        cfg.team.workers[name].routing = WorkerRouting(
            workload="review" if name != "codex" else "implementation",
            effort="xhigh" if name == "grok" else "max",
            independent_of_provider="openai" if name == "grok" else None,
        )
    now = datetime.now(timezone.utc)
    clis = []
    access = []
    for cli, name, provider in [("codex", "codex", "openai"), ("grok", "grok", "xai")]:
        model = cfg.agents[name].model
        clis.append(
            {
                "id": cli,
                "installed_version": "fixture 1.0",
                "capabilities": ["headless", "coding"],
                "models": [
                    {
                        "id": model,
                        "provider": provider,
                        "efforts": ["high", "xhigh", "max"]
                        if cli == "codex"
                        else ["high", "xhigh"],
                        "fit": {"implementation": 5, "review": 5},
                        "cost_rank": 1,
                        "evidence": "synthetic",
                    }
                ],
                "documented_models": [],
                "sources": [],
                "limitations": "fixture only",
            }
        )
        access.append(
            {
                "cli": cli,
                "executable": cfg.agents[name].executable,
                "version": "fixture 1.0",
                "models": [model],
                "access_kind": "subscription",
                "verified_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                "evidence": "synthetic login",
            }
        )
    matrix = {
        "schema_version": "bigplan.cli-matrix.v1",
        "checked_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "clis": clis,
    }
    document = {"id": "matrix-fixture", "revision": 5, "notes": BEGIN + json.dumps(matrix) + END}
    runtime = Runtime(
        schema_version="bigplan.cli-runtime.v1",
        access=access,
        allowed_roots=[str(s["root"])],
        state_dir=str(tmp_path / "native-routing-state"),
        allow_write=write_grant,
    )
    cfg.team.routing = NativeRoutingSettings(
        workspace=str(s["desk"]), thread_id=document["id"], runtime=runtime
    )
    guard = DelegationGuard(ThreadDeskSource(lambda _: document, document["id"]), runtime)
    profiles = []
    prepare = guard.prepare

    def observed(profile):
        profiles.append(profile.model_dump())
        return prepare(profile)

    guard.prepare = observed
    previous = b.agents
    b.agents = native_routed_manager(b, guard)
    b.agents.worktree_guard = previous.worktree_guard
    b.agents.visible_handoffs = previous.visible_handoffs
    return SimpleNamespace(
        s=s, b=b, cfg=cfg, card=card, guard=guard, document=document, profiles=profiles
    )


async def complete(r):
    await r.s["start"]()
    await until(lambda: r.b.autonext.inspect()["state"] in {"complete", "stopped"}, timeout=20)
    return r.b.autonext.inspect()


def starts(r):
    p = r.s["root"] / "routing-native-argv.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []


async def test_native_worker_chain_preserves_visible_and_structured_verdict(routed):
    r = routed
    status = await complete(r)
    assert status["state"] == "complete", status
    calls = starts(r)
    assert len(calls) == 3
    assert r.cfg.visible_handoffs.enabled is True
    for argv in calls:
        assert "--model" in argv
        if "--prompt-file" in argv:
            assert argv[argv.index("--effort") + 1] == "xhigh"
        else:
            assert 'model_reasoning_effort="max"' in argv
    cores = [
        r.b.store.get(row[0])
        for row in r.b.store.db.execute(
            "SELECT core_task_id FROM team_work WHERE core_task_id IS NOT NULL"
        )
    ]
    assert len(cores) == 3
    assert all(core["state"] == "completed" and core["attempt"] == 1 for core in cores)
    for core in cores:
        decision = core["evidence"]["routing_decision"]
        assert decision["thread_desk"] == {"thread_id": "matrix-fixture", "revision": 5}
        assert decision["effective_effort"] == "unverified"
    grok = next(core for core in cores if core["principal"] == "grok")
    decision = grok["evidence"]["routing_decision"]
    assert (
        decision["model"] == "fixture-grok" and decision["effective_model"] == "fixture-grok-build"
    )
    assert decision["model_matches_requested_id"] is False
    from kirabridge.completion_manager import completion_payload

    notice = completion_payload(grok, 1)
    assert notice["routing"]["effort"] == "xhigh"
    assert notice["routing"]["effective_effort"] == "unverified"
    assert notice["routing"]["model"] != notice["routing"]["effective_model"]
    assert "executable" not in notice["routing"] and "prompt" not in notice["routing"]
    before = len(r.profiles)
    await r.b.autonext.tick()
    assert len(r.profiles) == before and len(starts(r)) == 3


async def test_continuation_preview_and_native_tasks_share_routes(routed, tmp_path, monkeypatch):
    r = routed
    (r.s["root"] / ".git").write_text("private fixture worktree")
    matrix = json.loads(r.document["notes"].split(BEGIN)[1].split(END)[0])
    alternate = {**matrix["clis"][0]["models"][0], "id": "fixture-task-codex"}
    matrix["clis"][0]["models"].append(alternate)
    r.guard.runtime.access[0].models.append(alternate["id"])
    r.document["notes"] = BEGIN + json.dumps(matrix) + END
    previous = r.b.agents
    r.b.agents = native_routed_manager(r.b, r.guard)
    r.b.agents.worktree_guard = previous.worktree_guard
    r.b.agents.visible_handoffs = previous.visible_handoffs
    team = r.b.teams.get("codex", "auto-team")
    anchor = r.b.teams.work_get("codex", team["id"], r.cfg.autonext.after_work_id)
    profile = dict(
        cwd=str(r.s["root"]),
        state_dir=str(r.cfg.state_path),
        search_path=[],
        codex=r.cfg.agents["codex"].executable,
        grok=r.cfg.agents["grok"].executable,
        workspace=str(r.s["desk"]),
        threaddesk_source="fixture-source",
        report_cli="fixture-report",
        instance="routing-parity-fixture",
        board_id="board",
        sandbox="read-only",
        enabled=True,
        cards=[],
        continuation={
            "authority_ref": "private fixture authority",
            "allowed_cwds": [str(r.s["root"])],
            "products": ["KiraBridge"],
            "checks": r.card["acceptance"]["checks"],
            "sources": [pin.model_dump() for pin in r.cfg.autonext.cards],
            "task_routing": {
                r.card["task_id"]: {
                    "workload": "implementation",
                    "model": alternate["id"],
                    "effort": "high",
                }
            },
        },
        routing=r.cfg.team.routing.model_dump(),
        worker_routing={
            name: r.cfg.team.workers[name].routing.model_dump()
            for name in ("codex", "grok", "codex_verify")
        },
    )
    original_globals = json.dumps(profile["worker_routing"], sort_keys=True)
    original_agents = {name: agent.model_dump() for name, agent in r.cfg.agents.items()}
    profile_path, fixture_path = tmp_path / "profile.json", tmp_path / "preview.json"

    def preview():
        profile_path.write_text(json.dumps(profile))
        fixture_path.write_text(
            json.dumps(
                {
                    "matrix": matrix,
                    "snapshot": {
                        "entries": read_whiteboard(
                            str(r.s["desk"]),
                            "board",
                            include_content=True,
                        )["entries"]
                    },
                }
            )
        )
        return loop.preview_profile(profile_path, fixture_path)

    decision = preview()["selected"]["routing"]
    assert (decision["model"], decision["effort"]) == (alternate["id"], "high")
    r.cfg.autonext = AutoNextConfig(coordinator_mode=True, principal="codex")
    r.b.autonext.continuation_guard = lambda card: validate_source(r.b, profile, card)
    monkeypatch.setattr(
        loop,
        "quota",
        AsyncMock(
            return_value={
                "observed_at": datetime.now(timezone.utc).timestamp(),
                "source": "fixture",
            }
        ),
    )
    active, _ = await loop.advance(r.b, profile, team, anchor, None)
    assert (await complete(r))["state"] == "complete"
    argv = starts(r)[0]
    assert argv[argv.index("--model") + 1] == decision["model"]
    assert 'model_reasoning_effort="high"' in argv

    second = {**r.card, "task_id": "followup.global"}
    content = json.dumps(second)
    entry = append_whiteboard(
        str(r.s["desk"]),
        "board",
        actor="coordinator",
        actor_type="codex",
        entry_type="task",
        content=content,
    )
    profile["continuation"]["sources"].append(
        {
            "task_id": second["task_id"],
            "entry_id": entry["id"],
            "content_sha256": text_sha(content),
        }
    )
    decision = preview()["selected"]["routing"]
    assert (decision["model"], decision["effort"]) == ("fixture-codex", "max")
    active, _ = await loop.advance(r.b, profile, team, anchor, active)
    await until(lambda: r.b.autonext.inspect()["state"] in {"complete", "stopped"}, timeout=20)
    assert r.b.autonext.inspect()["state"] == "complete", r.b.autonext.inspect()
    argv = starts(r)[3]
    assert argv[argv.index("--model") + 1] == "fixture-codex"
    assert 'model_reasoning_effort="max"' in argv
    assert r.cfg.team.workers["codex"].routing == WorkerRouting.model_validate(
        profile["worker_routing"]["codex"]
    )
    assert json.dumps(profile["worker_routing"], sort_keys=True) == original_globals
    assert {name: agent.model_dump() for name, agent in r.cfg.agents.items()} == original_agents


@pytest.mark.parametrize(
    "change", ["budget", "matrix_revision", "matrix_hash", "scope", "runtime_write"]
)
async def test_changed_after_slow_probe_stops_without_native_start(routed, change):
    r = routed
    original = r.guard.prepare

    def changed(profile):
        result = original(profile)
        if change == "budget":
            r.cfg.autonext.budget_state = "exhausted"
        elif change == "matrix_revision":
            r.document["revision"] += 1
        elif change == "matrix_hash":
            r.document["notes"] = r.document["notes"].replace("fixture only", "changed fixture")
        elif change == "scope":
            r.cfg.team.workers["codex"].execution_scope = "existing_visible_terminal"
        else:
            r.cfg.team.routing.runtime.allow_write = True
        return result

    r.guard.prepare = changed
    status = await complete(r)
    assert status["state"] == "stopped", status
    assert starts(r) == []


@pytest.mark.parametrize("change", ["budget", "claim", "lease"])
async def test_live_gate_changed_in_progress_stops_before_spawn(routed, change):
    r = routed
    adapter = r.b.agents.adapters["codex"]
    execute = adapter.execute
    applied = False

    async def changed(task, args, config, roots, running, progress, **kwargs):
        async def event(data):
            nonlocal applied
            await progress(data)
            if "routing_decision" in data and not applied:
                applied = True
                if change == "budget":
                    r.cfg.autonext.budget_state = "exhausted"
                elif change == "claim":
                    row = r.b.store.db.execute(
                        "SELECT id FROM team_work WHERE core_task_id=?", (task["id"],)
                    ).fetchone()
                    r.b.teams.fail(row["id"], "cancelled", "synthetic_claim_withdrawn", {})
                else:
                    r.b.store.db.execute("UPDATE autonext_items SET lease_until=0")

        return await execute(task, args, config, roots, running, event, **kwargs)

    adapter.execute = changed
    assert (await complete(r))["state"] == "stopped"
    assert applied and not starts(r)


@pytest.mark.parametrize("change", ["budget", "claim"])
async def test_last_shim_io_revocation_is_checked_before_native_start(routed, monkeypatch, change):
    import kirabridge.capability_routing.integration as integration

    r = routed
    original = integration.effort_shim
    shim_calls = 0
    revoked = False

    def revoked_during_io(decision, state_dir):
        nonlocal shim_calls, revoked
        shim_calls += 1
        path = original(decision, state_dir)
        # Config creation, adapter preflight, then the actual TerminalManager callback.
        if shim_calls == 3:
            if change == "budget":
                r.cfg.autonext.budget_state = "exhausted"
            else:
                r.b.store.db.execute(
                    "UPDATE team_work SET claimed=NULL WHERE core_task_id IS NOT NULL"
                )
            revoked = True
        return path

    monkeypatch.setattr(integration, "effort_shim", revoked_during_io)
    status = await complete(r)
    assert revoked and shim_calls >= 3
    assert starts(r) == [], "Authority withdrawn during last shim I/O must prevent native starts"
    assert status["state"] == "stopped", status


@pytest.mark.parametrize("routed", ["workspace-write"], indirect=True)
async def test_write_profile_requires_original_sandbox_and_runtime_grant(routed):
    r = routed
    assert not r.cfg.agents["codex"].allow_local_tools
    assert (await complete(r))["state"] == "complete"
    assert [p["read_only"] for p in r.profiles] == [False, True, True]
    argv = starts(r)[0]
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"


def test_native_constructor_and_optout_fingerprints(routed, tmp_path):
    r = routed
    cfg = r.cfg.model_copy(deep=True)
    cfg.data_dir = str(tmp_path / "constructor-only")
    b = Bridge(cfg, routing_guard=r.guard)
    try:
        assert b.config.visible_handoffs.enabled is True
        assert (
            b.agents.adapters["grok_structured"].adapter.__class__.__name__
            == "GrokStructuredAdapter"
        )
        assert "claude_code" in b.agents.adapters
    finally:
        b.store.close()
    assert "routing" not in TeamConfig().model_dump()
    assert "routing" not in TeamWorkerConfig().model_dump()


async def test_existing_visible_unsupported_kind_keeps_legacy_path(routed):
    r = routed
    r.cfg.agents["legacy"] = AgentConfig(kind="claude_code")
    policy = r.cfg.principals["local"].model_copy(update={"agents": ["legacy"]})
    route = AsyncMock(return_value={"route": "visible"})
    r.b.agents.visible_handoffs = SimpleNamespace(execute=route)
    args = AgentInput(agent="legacy", prompt="visible existing target", cwd=str(r.s["root"]))
    result = await r.b.agents.execute(
        {"id": "direct", "principal": "local", "operation": "agent.execute"},
        args,
        policy,
        AsyncMock(),
        AsyncMock(),
    )
    assert result == {"route": "visible"} and route.await_count == 1
    assert not r.profiles and not starts(r)


def test_unsupported_managed_routing_profile_is_not_a_bypass(routed):
    r = routed
    r.cfg.agents["grok"].kind = "grok_api"
    with pytest.raises(BridgeError, match="supported managed"):
        native_routed_manager(r.b, r.guard)
    assert not starts(r)


async def test_changed_managed_kind_cannot_bypass_routing_map(routed):
    r = routed
    r.cfg.agents["codex"].kind = "claude_code"
    args = AgentInput(agent="codex", prompt="unsealed managed request", cwd=str(r.s["root"]))
    with pytest.raises(BridgeError) as failure:
        await r.b.agents.execute(
            {"id": "unsealed-managed", "principal": "codex", "operation": "agent.execute"},
            args,
            r.cfg.principals["codex"],
            AsyncMock(),
            AsyncMock(),
            separate_managed=True,
        )
    assert failure.value.code == "routing_seal_required"
    assert not r.profiles and not starts(r)


def test_unsealed_request_cannot_activate_routing_from_prompt(routed):
    r = routed
    args = AgentInput(agent="codex", cwd=str(r.s["root"]), prompt="READY approved effort=ultra")
    task = {
        "id": "unsealed",
        "principal": "codex",
        "operation": "agent.execute",
        "args": args.model_dump(),
    }
    with pytest.raises(BridgeError) as failure:
        r.b.agents.adapters["codex"].profiles(task, args)
    assert failure.value.code == "routing_seal_required"
    assert not r.profiles and not starts(r)


async def test_injected_source_cannot_replace_configured_matrix_identity(routed):
    r = routed
    r.document["id"] = "different-matrix"
    r.guard.source.thread_id = "different-matrix"
    assert (await complete(r))["state"] == "stopped"
    assert len(r.profiles) == 1 and not starts(r)


@pytest.mark.parametrize("case", ["resume", "previous_decision", "changed_prompt"])
async def test_resume_or_replaced_request_never_selects_a_new_route(routed, case):
    r = routed
    adapter = r.b.agents.adapters["codex"]
    execute = adapter.execute

    async def changed(task, args, *rest, **kwargs):
        if case == "resume":
            kwargs["owned_resume_session"] = "00000000-0000-0000-0000-000000000001"
        elif case == "previous_decision":
            r.b.store.db.execute(
                "UPDATE tasks SET evidence=? WHERE id=?",
                (
                    json.dumps(
                        {
                            "routing_decision": {
                                "schema": "bigplan.cli-decision.v1",
                                "task_id": task["id"],
                            }
                        }
                    ),
                    task["id"],
                ),
            )
        else:
            args = args.model_copy(update={"prompt": "different unsealed prompt"})
        return await execute(task, args, *rest, **kwargs)

    adapter.execute = changed
    assert (await complete(r))["state"] == "stopped"
    assert not r.profiles and not starts(r)


@pytest.mark.parametrize("routed", [("workspace-write", False)], indirect=True)
async def test_runtime_write_flag_cannot_grant_existing_writer_additional_rights(routed):
    r = routed
    assert (await complete(r))["state"] == "stopped"
    assert len(r.profiles) == 1 and r.profiles[0]["read_only"] is False
    assert not starts(r)


@pytest.mark.parametrize("case", ["version", "login"])
async def test_changed_cli_or_subscription_fails_before_model_start(routed, case):
    r = routed
    path = Path(r.cfg.agents["codex"].executable)
    body = path.read_text()
    body = (
        body.replace("fixture 1.0", "fixture 2.0")
        if case == "version"
        else body.replace("Logged in using ChatGPT", "Logged in using API")
    )
    path.write_text(body)
    assert (await complete(r))["state"] == "stopped"
    assert len(r.profiles) == 1 and not starts(r)


async def test_unconfirmed_native_turn_preserves_unknown_without_fresh_selection(routed):
    r = routed
    path = Path(r.cfg.agents["codex"].executable)
    body = path.read_text()
    assert '"type":"turn.completed"' in body
    path.write_text(body.replace('"type":"turn.completed"', '"type":"fixture.incomplete"'))
    assert (await complete(r))["state"] == "stopped"
    cores = [
        r.b.store.get(row[0])
        for row in r.b.store.db.execute(
            "SELECT core_task_id FROM team_work WHERE core_task_id IS NOT NULL"
        )
    ]
    assert len(cores) == 1 and cores[0]["state"] == "unknown"
    assert len(starts(r)) == 1 and len(r.profiles) == 1
    await r.b.autonext.tick()
    assert len(starts(r)) == 1 and len(r.profiles) == 1


async def test_routing_preserves_structured_original_billing_gate(tmp_path, monkeypatch):
    from kirabridge.agent_manager.grok_structured import GrokStructuredAdapter
    from kirabridge.capability_routing.integration import RoutedAdapter
    from kirabridge.capability_routing.router import Task, fingerprint

    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setenv("ROUTED_STRUCTURED_ORIGINAL_KEY", "synthetic-not-a-real-key")
    profile = Task(
        task_id="billing-gate",
        workload="review",
        prompt="bounded fixture",
        cwd=str(tmp_path),
        ownership_ref="synthetic",
    )
    matrix = {}
    decision = {
        "cli": "grok",
        "model": "fixture-grok",
        "effort": "xhigh",
        "access_kind": "subscription",
        "executable": "/synthetic/grok",
        "expected_version": "synthetic",
        "matrix_sha256": fingerprint(matrix),
        "thread_desk": {"thread_id": "matrix", "revision": 1},
    }
    guard = SimpleNamespace(
        runtime=SimpleNamespace(state_dir=str(tmp_path / "state")),
        prepare=lambda _: decision,
        source=SimpleNamespace(load=lambda: (matrix, decision["thread_desk"])),
    )
    terminal = SimpleNamespace(
        environment={"PATH": os.defpath},
        execute=AsyncMock(side_effect=AssertionError("billing gate bypassed")),
    )
    config = AgentConfig(
        kind="grok_structured",
        executable="/synthetic/grok",
        api_key_env="ROUTED_STRUCTURED_ORIGINAL_KEY",
    )
    adapter = RoutedAdapter(
        GrokStructuredAdapter(terminal),
        "grok",
        guard,
        lambda t, a: profile,
        authorize=lambda *args: None,
        optional=True,
    )
    args = AgentInput(
        agent="grok", prompt=profile.prompt, cwd=profile.cwd, timeout=profile.timeout_seconds
    )
    with pytest.raises(BridgeError) as error:
        await adapter.execute(
            {"id": profile.task_id, "principal": "grok"},
            args,
            config,
            [str(tmp_path)],
            AsyncMock(),
            AsyncMock(),
        )
    assert error.value.code == "agent_billing_unknown"
    terminal.execute.assert_not_awaited()
