"""Real authenticated team tools and CLI use the same domain and private boundaries."""

import asyncio
import json
import os
import sys

import pytest
from test_mcp import http_bridge as live_http_fixture

from kirabridge.bridge_core.config import PrincipalConfig, TeamConfig, TeamWorkerConfig
from kirabridge.mcp_gateway.client import MCPClientPool, Peer

http_bridge = live_http_fixture


async def setup_team(http_bridge):
    bridge, endpoint = http_bridge
    bridge.config.team = TeamConfig(
        enabled=True, workers={name: TeamWorkerConfig() for name in ("local", "other")}
    )
    for policy in bridge.config.principals.values():
        policy.capabilities += ["team.read", "team.write", "team.manage"]
        policy.approval_mode = "automatic"
    pool = MCPClientPool()
    await pool.__aenter__()
    await pool.connect(Peer("owner", url=endpoint, token="local-test-" + "a" * 40))
    await pool.connect(Peer("peer", url=endpoint, token="other-test-" + "b" * 40))
    response = await pool.call(
        "owner",
        "team_create",
        {
            "request": {
                "team_id": "gateway",
                "name": "Gateway team",
                "members": {"other": "worker"},
                "coordinator": "local",
                "idempotency_key": "create-gateway",
            }
        },
    )
    assert response.structuredContent["owner"] == "local"
    return bridge, endpoint, pool


async def test_authenticated_team_identity_roles_and_manual_work(http_bridge):
    bridge, _, pool = await setup_team(http_bridge)
    try:
        request = {
            "team_id": "gateway",
            "recipient": "local",
            "body": "Question",
            "kind": "question",
            "idempotency_key": "question-1",
        }
        sent = await pool.call("peer", "team_message_send", {"request": request})
        assert sent.structuredContent["sender"] == "other"
        forged = await pool.call(
            "peer", "team_message_send", {"request": {**request, "sender": "local"}}
        )
        assert forged.isError
        assignment = await pool.call(
            "peer",
            "team_work_create",
            {
                "request": {
                    "team_id": "gateway",
                    "assignee": "local",
                    "title": "Review",
                    "body": "Check it",
                    "idempotency_key": "review-1",
                }
            },
        )
        work = assignment.structuredContent
        assert work["assigned_by"] == "other" and work["state"] == "queued_manual"
        claimed = await pool.call(
            "owner",
            "team_work_claim",
            {
                "request": {
                    "team_id": "gateway",
                    "work_id": work["id"],
                    "idempotency_key": "claim-1",
                }
            },
        )
        assert claimed.structuredContent["state"] == "accepted_manual"
        completed = await pool.call(
            "owner",
            "team_work_complete",
            {
                "request": {
                    "team_id": "gateway",
                    "work_id": work["id"],
                    "result": "Reviewed",
                    "idempotency_key": "complete-1",
                }
            },
        )
        assert completed.structuredContent["state"] == "completed"
        shared = await pool.call(
            "peer",
            "team_work_get",
            {
                "team_id": "gateway",
                "work_id": work["id"],
            },
        )
        assert shared.structuredContent["result"] == "Reviewed"
        assert not shared.structuredContent["evidence"]["project_completion_verified"]
        role = {
            "team_id": "gateway",
            "member": "other",
            "role": "observer",
            "expected_revision": 1,
            "idempotency_key": "role-1",
        }
        denied = await pool.call("peer", "team_set_role", {"request": role})
        assert denied.structuredContent["error"]["code"] == "team_role_denied"
        changed = await pool.call("owner", "team_set_role", {"request": role})
        assert changed.structuredContent["revision"] == 2
        blocked = await pool.call(
            "peer",
            "team_message_send",
            {
                "request": {
                    **request,
                    "idempotency_key": "question-2",
                }
            },
        )
        assert blocked.structuredContent["error"]["code"] == "team_role_denied"
        assert not bridge.store.db.execute("SELECT id FROM tasks").fetchall()
    finally:
        await pool.__aexit__(None, None, None)


async def test_team_cli_calls_real_authenticated_service(http_bridge, tmp_path):
    _, endpoint, pool = await setup_team(http_bridge)
    config_file = tmp_path / "client.toml"
    config_file.write_text(
        'host="127.0.0.1"\nport='
        + endpoint.split(":")[2].split("/")[0]
        + '\n[principals.local]\ntoken_env="BRIDGE_TEST_TOKEN"\n'
    )

    async def command(*arguments):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "kirabridge.cli",
            "--config",
            str(config_file),
            "team",
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )
        stdout, stderr = await process.communicate()
        assert process.returncode == 0, stderr.decode()
        return json.loads(stdout)

    try:
        teams = await command("list")
        assert teams["teams"][0]["id"] == "gateway"
        sent = await command("send", "gateway", "other", "CLI Unicode ü", "--key", "cli-msg")
        assert sent["sender"] == "local"
        same = await command("send", "gateway", "other", "CLI Unicode ü", "--key", "cli-msg")
        assert same["id"] == sent["id"]
        work = await command("assign", "gateway", "other", "CLI request", "--key", "cli-work")
        board = await command("work", "gateway")
        assert board["work"][0]["id"] == work["id"]
    finally:
        await pool.__aexit__(None, None, None)


@pytest.mark.parametrize("name", ["Bad Worker", "../worker", "x" * 42])
def test_operator_roster_rejects_ambiguous_identities(name):
    with pytest.raises(ValueError):
        TeamConfig(workers={name: TeamWorkerConfig()})


def test_automatic_worker_requires_operator_fixed_absolute_directory():
    with pytest.raises(ValueError):
        TeamWorkerConfig(agent="codex", cwd="relative")


async def test_all_seven_authenticated_agent_identities_can_address_each_other(
    http_bridge, monkeypatch
):
    bridge, endpoint = http_bridge
    names = ("chatgpt", "codex", "grok", "opencode", "claude", "gemini", "copilot")
    bridge.config.team = TeamConfig(
        enabled=True, workers={name: TeamWorkerConfig() for name in ("local", *names)}
    )
    bridge.config.principals["local"].approval_mode = "automatic"
    bridge.config.principals["local"].capabilities += ["team.manage", "team.read", "team.write"]
    async with MCPClientPool() as pool:
        await pool.connect(Peer("owner", url=endpoint, token="local-test-" + "a" * 40))
        for name in names:
            variable = "KB_TEAM_MATRIX_" + name.upper()
            token = "matrix-" + name + "-" + "x" * 40
            monkeypatch.setenv(variable, token)
            bridge.config.principals[name] = PrincipalConfig(
                approval_mode="automatic",
                capabilities=["team.read", "team.write"],
                token_env=variable,
            )
            await pool.connect(Peer(name, url=endpoint, token=token))
        created = await pool.call(
            "owner",
            "team_create",
            {
                "request": {
                    "team_id": "matrix",
                    "name": "Every agent to every agent",
                    "members": {name: "worker" for name in names},
                    "coordinator": "chatgpt",
                    "idempotency_key": "matrix-create",
                }
            },
        )
        assert created.structuredContent["coordinator"] == "chatgpt"
        for sender in names:
            for target in names:
                if sender == target:
                    continue
                key = sender + "-to-" + target
                message = await pool.call(
                    sender,
                    "team_message_send",
                    {
                        "request": {
                            "team_id": "matrix",
                            "recipient": target,
                            "body": key + (" go-go-go" if sender == "chatgpt" else ""),
                            "idempotency_key": key,
                        }
                    },
                )
                assert message.structuredContent["sender"] == sender
                assigned = await pool.call(
                    sender,
                    "team_work_create",
                    {
                        "request": {
                            "team_id": "matrix",
                            "assignee": target,
                            "title": key,
                            "body": "Shared test",
                            "idempotency_key": key,
                        }
                    },
                )
                assert assigned.structuredContent["assigned_by"] == sender
                assert assigned.structuredContent["assignee"] == target
        assert bridge.store.db.execute("SELECT count(*) FROM team_messages").fetchone()[0] == 42
        assert bridge.store.db.execute("SELECT count(*) FROM team_work").fetchone()[0] == 42
        assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
