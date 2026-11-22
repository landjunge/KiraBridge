"""Real authenticated team tools and CLI use the same domain and private boundaries."""

import asyncio
import json
import os
import subprocess
import sys

import pytest
from test_mcp import http_bridge as live_http_fixture

from kirabridge.bridge_core.config import PrincipalConfig, TeamConfig, TeamWorkerConfig
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.team_manager.models import TeamWorkCreate

http_bridge = live_http_fixture


async def setup_team(http_bridge, *, coordinator="local"):
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
                "coordinator": coordinator,
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


async def test_mcp_coordinator_self_demotion_retry_obeys_read_grant(http_bridge):
    bridge, _, pool = await setup_team(http_bridge, coordinator="other")
    request = {
        "team_id": "gateway",
        "member": "local",
        "role": "coordinator",
        "active": True,
        "expected_revision": 1,
        "idempotency_key": "mcp-coordinator-handoff",
    }
    try:
        first = await pool.call("peer", "team_set_role", {"request": request})
        assert first.structuredContent["coordinator"] == "local"
        assert first.structuredContent["revision"] == 2

        # The old coordinator can read back its exact operation after losing
        # manage rights, without repeating the write.
        replay = await pool.call("peer", "team_set_role", {"request": request})
        assert replay.structuredContent["coordinator"] == "local"
        assert replay.structuredContent["revision"] == 2

        changed = await pool.call(
            "peer",
            "team_set_role",
            {"request": {**request, "role": "worker"}},
        )
        assert changed.structuredContent["error"]["code"] == "idempotency_conflict"
        assert not {"members", "revision", "coordinator"} & changed.structuredContent.keys()

        # Idempotency records are principal-scoped: another actor cannot read
        # the first actor's receipt and receives no team snapshot.
        other_actor = await pool.call("owner", "team_set_role", {"request": request})
        assert other_actor.structuredContent["error"]["code"] == "team_revision_conflict"
        assert not {"members", "revision", "coordinator"} & other_actor.structuredContent.keys()

        bridge.config.principals["other"].capabilities = [
            capability
            for capability in bridge.config.principals["other"].capabilities
            if capability != "team.read"
        ]
        denied = await pool.call("peer", "team_set_role", {"request": request})
        assert denied.structuredContent["error"]["code"] == "forbidden"
        assert not {"members", "revision", "coordinator"} & denied.structuredContent.keys()
        denied_read = await pool.call("peer", "team_get", {"team_id": "gateway"})
        assert denied_read.structuredContent["error"]["code"] == "forbidden"
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
                            "body": key,
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


def client_config(tmp_path, endpoint):
    config_file = tmp_path / "client.toml"
    port = endpoint.split(":")[2].split("/")[0]
    config_file.write_text(
        'host="127.0.0.1"\nport=' + port + '\n[principals.local]\ntoken_env="BRIDGE_TEST_TOKEN"\n'
    )
    return config_file


async def team_command(config_file, *arguments):
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
    return process.returncode, stdout, stderr


def fill_work(bridge, count=60):
    bridge.config.team.max_pending_per_member = count
    for index in range(count):
        bridge.teams.delegate(
            "local",
            TeamWorkCreate(
                team_id="gateway",
                assignee="other",
                title=f"item {index}",
                body="paging",
                idempotency_key=f"page-{index}",
            ),
        )


async def test_team_work_cli_pages_past_the_default_fifty(http_bridge, tmp_path):
    bridge, endpoint, pool = await setup_team(http_bridge)
    config_file = client_config(tmp_path, endpoint)
    try:
        fill_work(bridge)
        code, stdout, stderr = await team_command(config_file, "work", "gateway")
        assert code == 0, stderr.decode()
        board = json.loads(stdout)
        assert [item["title"] for item in board["work"]] == [f"item {index}" for index in range(50)]
        assert board["next_after"] == board["work"][-1]["seq"]
        assert board["next_cursor"] == board["next_after"]
        code, stdout, stderr = await team_command(
            config_file, "work", "gateway", "--after", str(board["next_after"])
        )
        assert code == 0, stderr.decode()
        rest = json.loads(stdout)
        assert [item["title"] for item in rest["work"]] == [
            f"item {index}" for index in range(50, 60)
        ]
        assert "next_after" not in rest
        assert rest["next_cursor"] == rest["work"][-1]["seq"]
    finally:
        await pool.__aexit__(None, None, None)


async def test_team_work_cli_latest_returns_the_newest_five_ascending(http_bridge, tmp_path):
    bridge, endpoint, pool = await setup_team(http_bridge)
    config_file = client_config(tmp_path, endpoint)
    try:
        fill_work(bridge)
        code, stdout, stderr = await team_command(config_file, "work", "gateway", "--latest", "5")
        assert code == 0, stderr.decode()
        latest = json.loads(stdout)
        assert [item["title"] for item in latest["work"]] == [
            f"item {index}" for index in range(55, 60)
        ]
        sequences = [item["seq"] for item in latest["work"]]
        assert sequences == sorted(sequences) and len(set(sequences)) == 5
        assert "next_after" not in latest
    finally:
        await pool.__aexit__(None, None, None)


@pytest.mark.parametrize(
    ("flag", "value"),
    [("--limit", "0"), ("--limit", "101"), ("--latest", "0"), ("--latest", "101")],
)
def test_team_work_cli_rejects_invalid_limit_and_latest(flag, value):
    process = subprocess.run(
        [sys.executable, "-m", "kirabridge.cli", "team", "work", "gateway", flag, value],
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode != 0
    assert "unrecognized arguments" not in process.stderr
    assert flag in process.stderr
