"""Two sealed Core/Team turns through a fixture ACP provider and real scoped MCP."""

import asyncio
import json
import sys
from pathlib import Path

from test_mcp import http_bridge  # noqa: F401

from kirabridge.bridge_core.config import AgentConfig, TeamConfig, TeamWorkerConfig
from kirabridge.bridge_core.models import AgentToolGrant
from kirabridge.private_files import write_private
from kirabridge.team_manager.models import TeamCreate, TeamWorkCreate

PROVIDER = (Path(__file__).parent / "fixtures/qwen_owned_acp.py").read_text()


async def test_two_turn_team_resume_renews_real_mcp_scope(
    http_bridge,  # noqa: F811
    config,
    tmp_path,
    monkeypatch,
):
    bridge, _ = http_bridge
    executable = tmp_path / "qwen-fixture"
    executable.write_text("#!" + sys.executable + "\n" + PROVIDER)
    executable.chmod(0o700)
    principal = config.principals["local"].model_copy(deep=True)
    principal.approval_mode = "automatic"
    principal.token_env = "QWEN_FIXTURE_WORKER_TOKEN"
    principal.agents = ["qwen"]
    principal.capabilities = sorted(
        set(principal.capabilities)
        | {"agent.execute", "team.manage", "team.read", "team.write", "bridge.health", "task.read"}
    )
    token = "qwen-fixture-" + "a" * 40
    monkeypatch.setenv(principal.token_env, token)
    config.principals["codex"] = principal
    config.principals["local"].capabilities = sorted(
        set(config.principals["local"].capabilities) | {"team.manage", "team.read", "team.write"}
    )
    config.principals["local"].approval_mode = "automatic"
    cwd = principal.roots[0]
    config.agents["qwen"] = AgentConfig(
        kind="qwen_acp",
        executable=str(executable),
        model="fixture-model",
        qwen_auth_type="qwen-subscription",
        qwen_reasoning_effort="xhigh",
        bridge_tools=True,
        qwen_mcp_tools=["bridge_epoch"],
    )
    config.team = TeamConfig(
        enabled=True,
        workers={
            "local": TeamWorkerConfig(),
            "codex": TeamWorkerConfig(
                agent="qwen",
                cwd=cwd,
                timeout=15,
                execution_scope="separate_managed_session",
                mcp_grants=[AgentToolGrant(tool="bridge_epoch")],
            ),
        },
    )
    creds = tmp_path / "credentials.json"
    write_private(creds, json.dumps({"codex": token}))
    source = tmp_path / "connect.toml"
    write_private(
        source,
        f"data_dir = {json.dumps(str(tmp_path / 'connect-state'))}\n"
        f"port = {config.port}\ncredentials_file = {json.dumps(str(creds))}\n"
        '[principals.codex]\ncapabilities=["bridge.health","task.read","team.read"]\n',
    )
    config._source_path = str(source)
    bridge.teams.create(
        "local",
        TeamCreate(
            team_id="qwen-team",
            name="Fixture",
            members={"local": "coordinator", "codex": "worker"},
            coordinator="local",
            idempotency_key="create",
        ),
    )
    await bridge.team_dispatcher.start()
    try:
        turns = []
        for i in range(2):
            work = bridge.teams.delegate(
                "local",
                TeamWorkCreate(
                    team_id="qwen-team",
                    assignee="codex",
                    title="Fixture",
                    body="Turn " + str(i),
                    idempotency_key="qwen-work-" + str(i),
                ),
            )
            async with asyncio.timeout(25):
                while True:
                    work = bridge.teams.work_get("local", "qwen-team", work["id"])
                    if work["state"] in {"completed", "failed", "unknown", "blocked"}:
                        break
                    await asyncio.sleep(0.03)
            if work["state"] != "completed":
                task = bridge.store.get(work["core_task_id"], "codex")
                errors = Path(cwd) / "qwen-fixture-errors.log"
                raise AssertionError(
                    {
                        "core_error": task.get("error"),
                        "evidence": task.get("evidence"),
                        "fixture_error": errors.read_text() if errors.exists() else None,
                    }
                )
            task = bridge.store.get(work["core_task_id"], "codex")
            assert task["result"]["evidence"]["session_resumed"] is (i == 1)
            assert "REPLAYED_TEXT" not in task["result"]["text"]
            turns.append(task)
        log = [
            json.loads(x)
            for x in (Path(cwd) / "fixture-qwen-scopes.jsonl").read_text().splitlines()
        ]
        assert [x["method"] for x in log] == ["session/new", "session/load"]
        assert len({x["task_id"] for x in log}) == 2
        assert len({x["arguments_sha256"] for x in log}) == 2
        assert len({x["policy_path"] for x in log}) == 2
        assert turns[1]["args"]["resume_session"] == "fixture-qwen-owned"
    finally:
        await bridge.team_dispatcher.stop()
