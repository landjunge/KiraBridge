"""Real HTTP Core/Team prompt + seal + Qwen execute; fake native spawn only."""

import asyncio
import json
import time

import pytest
from test_mcp import http_bridge  # noqa: F401
from test_scoped_qwen_routing import scoped  # noqa: F401

from kirabridge.agent_manager.qwen_acp import QwenACPAdapter
from kirabridge.bridge_core.config import TeamConfig, TeamWorkerConfig
from kirabridge.bridge_core.models import AgentInput, AgentToolGrant
from kirabridge.capability_routing.hook import DelegationGuard
from kirabridge.capability_routing.qwen import ScopedQwenAdapter
from kirabridge.capability_routing.router import WorkerRouting, fingerprint
from kirabridge.private_files import write_private
from kirabridge.team_manager.models import TeamCreate, TeamWorkCreate


@pytest.mark.parametrize(
    "change,actor",
    [
        ("none", "coord"),
        ("none", "knowledge"),
        *[
            (change, "coord")
            for change in (
                "matrix",
                "config",
                "lease",
                "claim",
                "cwd",
                "actual_args",
                "matrix_during_final_probe",
                "lease_during_final_probe",
                "minimum",
            )
        ],
    ],
)
async def test_actual_dispatcher_input_and_last_effect_gate(
    http_bridge,  # noqa: F811
    config,
    tmp_path,
    monkeypatch,
    scoped,  # noqa: F811
    change,
    actor,
):
    bridge, _ = http_bridge
    source, runtime, _, agent, _, _, _, document, _ = scoped
    root = config.principals["local"].roots[0]
    agent.qwen_mcp_read_roots = [root]
    config.agents["qwen"] = agent
    policy = config.principals["local"].model_copy(deep=True)
    policy.approval_mode = "automatic"
    policy.agents = ["qwen"]
    policy.token_env = "SCOPED_QWEN_TEAM_FIXTURE_TOKEN"
    policy.capabilities = sorted(
        set(policy.capabilities)
        | {"team.manage", "team.read", "team.write", "agent.execute", "bridge.health", "task.read"}
    )
    config.principals[actor] = policy
    config.principals["local"].approval_mode = "automatic"
    config.principals["local"].capabilities = sorted(
        set(config.principals["local"].capabilities) | {"team.manage", "team.read", "team.write"}
    )
    token = "synthetic-worker-" + "a" * 40
    monkeypatch.setenv(policy.token_env, token)
    query = {"queries": [{"operation": "bridge.status", "arguments": {}}]}
    config.team = TeamConfig(
        enabled=True,
        workers={
            "local": TeamWorkerConfig(),
            actor: TeamWorkerConfig(
                agent="qwen",
                cwd=root,
                timeout=12,
                execution_scope="separate_managed_session",
                mcp_operations=["file.read"],
                mcp_read_roots=[root],
                mcp_grants=[AgentToolGrant(tool="read_queries", arguments=query, calls=1)],
            ),
        },
    )
    if change == "minimum":
        config.team.workers[actor].routing = WorkerRouting(
            workload="implementation", model=agent.model, effort="medium", min_effort="high"
        )
    credentials = tmp_path / "worker-credentials.json"
    write_private(credentials, json.dumps({actor: token}))
    client_config = tmp_path / "client.toml"
    write_private(
        client_config,
        f"data_dir={json.dumps(str(tmp_path / 'unused'))}\nport={config.port}\n"
        f"credentials_file={json.dumps(str(credentials))}\n"
        f'[principals.{actor}]\ncapabilities=["bridge.health","task.read","team.read"]\n',
    )
    config._source_path = str(client_config)
    history = tmp_path / "history-sentinel.json"
    history.write_text('{"old_unknown":"preserve"}')
    original_history = history.read_bytes()
    bridge.store.db.execute(
        "INSERT INTO tasks(id,principal,idem,request_hash,operation,args,state,created,updated) "
        "VALUES(?,?,?,?,?,?,'unknown',?,?)",
        (
            "historical-unknown",
            actor,
            "historical-unknown",
            "0" * 64,
            "agent.execute",
            json.dumps({"agent": "qwen", "cwd": root, "prompt": "old unrelated turn"}),
            time.time() - 600,
            time.time() - 600,
        ),
    )
    prior_unknown = tuple(
        bridge.store.db.execute("SELECT * FROM tasks WHERE id='historical-unknown'").fetchone()
    )
    spawns, actual, preflights, final_entries = [], [], [], []

    async def fake_spawn(*args, **kwargs):
        spawns.append((args, kwargs))
        raise RuntimeError("synthetic native spawn boundary reached; no model process")

    monkeypatch.setattr("kirabridge.agent_manager.qwen_acp.spawn_process", fake_spawn)

    class CountedNativeQwen(QwenACPAdapter):
        async def execute(self, *args, before_spawn=None, **kwargs):
            def counted_boundary():
                final_entries.append(True)
                before_spawn()

            return await super().execute(*args, before_spawn=counted_boundary, **kwargs)

    guarded = ScopedQwenAdapter(
        bridge, CountedNativeQwen(bridge.terminal, config), DelegationGuard(source, runtime)
    )

    class Observed:
        async def execute(self, task, args, agent_config, roots, running, progress, **kwargs):
            actual.append(
                {
                    "task": dict(task),
                    "args": args.model_copy(deep=True),
                    "agent": agent_config.model_copy(deep=True),
                }
            )

            async def observed_progress(event):
                await progress(event)
                if event.get("event") != "scoped_qwen_preflight":
                    return
                preflights.append(event["routing_decision"])
                if change == "matrix":
                    document["revision"] += 1
                elif change == "config":
                    agent_config.qwen_reasoning_effort = "high"
                elif change == "lease":
                    bridge.store.db.execute(
                        "UPDATE tasks SET lease_until=? WHERE id=?", (time.time() - 1, task["id"])
                    )
                elif change == "claim":
                    bridge.store.db.execute(
                        "UPDATE team_work SET state='unknown' WHERE core_task_id=?", (task["id"],)
                    )
                elif change == "cwd":
                    config.team.workers[actor].cwd = str(tmp_path)
                elif change == "actual_args":
                    args.prompt = "unsealed replacement"

            return await guarded.execute(
                task, args, agent_config, roots, running, observed_progress, **kwargs
            )

    bridge.agents.adapters["qwen_acp"] = Observed()
    if change.endswith("during_final_probe"):
        from kirabridge.capability_routing import hook

        run = hook.subprocess.run
        probes = 0

        def changed_during_probe(*args, **kwargs):
            nonlocal probes
            result = run(*args, **kwargs)
            probes += 1
            if probes == 2:
                if change == "matrix_during_final_probe":
                    document["revision"] += 1
                else:
                    bridge.store.db.execute(
                        "UPDATE tasks SET lease_until=? WHERE id=?",
                        (time.time() - 1, actual[0]["task"]["id"]),
                    )
            return result

        monkeypatch.setattr(hook.subprocess, "run", changed_during_probe)

    bridge.teams.create(
        "local",
        TeamCreate(
            team_id="scoped-qwen-team",
            name="synthetic",
            coordinator="local",
            members={"local": "coordinator", actor: "worker"},
            idempotency_key="create",
        ),
    )
    work = bridge.teams.delegate(
        "local",
        TeamWorkCreate(
            team_id="scoped-qwen-team",
            assignee=actor,
            title="Exact fixture task",
            body="RAW_WORK_BODY_not_the_actual_packed_prompt",
            idempotency_key="one-owned-work",
        ),
    )
    await bridge.team_dispatcher.start()
    try:
        async with asyncio.timeout(20):
            while True:
                latest = bridge.teams.work_get("local", "scoped-qwen-team", work["id"])
                if latest["state"] in {"completed", "failed", "blocked", "unknown", "cancelled"}:
                    break
                await asyncio.sleep(0.02)
        assert len(actual) == 1, latest
        assert len(preflights) == (0 if change == "minimum" else 1), latest
        bound = actual[0]
        core = bridge.store.get(latest["core_task_id"], actor)
        sealed = bridge.store.db.execute(
            "SELECT core_request_hash FROM team_work WHERE id=?", (work["id"],)
        ).fetchone()[0]
        assert sealed and sealed == core["request_sha256"]
        assert bound["args"].prompt != "RAW_WORK_BODY_not_the_actual_packed_prompt"
        assert "RAW_WORK_BODY_not_the_actual_packed_prompt" in bound["args"].prompt
        assert bound["args"].cwd == core["args"]["cwd"] == root
        if preflights:
            assert preflights[0]["task_id"] == core["id"]
            assert preflights[0]["agent_input_sha256"] == fingerprint(
                AgentInput.model_validate(core["args"])
            )
            assert preflights[0]["configured_agent_sha256"] == fingerprint(bound["agent"])
        assert len(spawns) == (1 if change == "none" else 0), (core["state"], core.get("error"))
        assert len(final_entries) == (0 if change in {"actual_args", "minimum"} else 1), core.get(
            "error"
        )
        assert (
            bridge.store.db.execute(
                "SELECT count(*) FROM tasks WHERE operation='agent.execute' "
                "AND id!='historical-unknown'"
            ).fetchone()[0]
            == 1
        )
        assert (
            tuple(
                bridge.store.db.execute(
                    "SELECT * FROM tasks WHERE id='historical-unknown'"
                ).fetchone()
            )
            == prior_unknown
        )
        assert history.read_bytes() == original_history
        assert not (tmp_path / "unused").exists()
    finally:
        await bridge.team_dispatcher.stop()
