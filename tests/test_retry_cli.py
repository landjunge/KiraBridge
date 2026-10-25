import asyncio
import json
import sys

import pytest
from conftest import request, submit

from kirabridge.bridge_core.models import BridgeError


async def test_cli_without_daemon_refuses_agent_handoff_before_admission(bridge, config):
    from kirabridge.cli import run_request

    config.visible_handoffs.enabled = True
    value = request(
        "agent.execute",
        {
            "agent": "codex",
            "prompt": "must not reach a terminal",
            "cwd": config.principals["local"].roots[0],
        },
    )
    with pytest.raises(BridgeError) as refused:
        await run_request(bridge, "local", value, wait=1, approve=True)
    assert refused.value.code == "receiver_unavailable"
    assert not bridge.tasks.started
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    assert (
        bridge.store.db.execute("SELECT count(*) FROM approvals WHERE used IS NOT NULL").fetchone()[
            0
        ]
        == 0
    )


async def test_retry_only_proven_not_started_and_bounded(bridge, config):
    config.principals["local"].executables = []
    original = request(
        "terminal.execute",
        {"argv": [sys.executable, "-c", "print(1)"], "cwd": config.principals["local"].roots[0]},
    )
    async with bridge:
        submit(bridge, original)
        first = await bridge.tasks.wait("local", original.task_id)
        assert first["evidence"]["safe_to_retry"]
        for attempt in (2, 3):
            following = original.model_copy(
                update={
                    "task_id": f"attempt-{attempt}",
                    "idempotency_key": f"attempt-{attempt}",
                    "parent_id": original.task_id,
                }
            )
            token = bridge.security.grant("local", following)
            queued = bridge.tasks.retry("local", original.task_id, following, token)
            assert queued["attempt"] == attempt
            assert (await bridge.tasks.wait("local", following.task_id))["state"] == "failed"
            original = following
        following = original.model_copy(
            update={
                "task_id": "attempt-4",
                "idempotency_key": "attempt-4",
                "parent_id": original.task_id,
            }
        )
        token = bridge.security.grant("local", following)
        with pytest.raises(BridgeError, match="three"):
            bridge.tasks.retry("local", original.task_id, following, token)


async def test_failure_after_execution_cannot_be_retried(bridge, config):
    value = request(
        "terminal.execute",
        {
            "argv": [sys.executable, "-c", "raise SystemExit(1)"],
            "cwd": config.principals["local"].roots[0],
        },
    )
    async with bridge:
        submit(bridge, value)
        assert (await bridge.tasks.wait("local", value.task_id))["state"] == "failed"
        following = value.model_copy(
            update={"task_id": "again", "idempotency_key": "again", "parent_id": value.task_id}
        )
        with pytest.raises(BridgeError, match="never started"):
            bridge.tasks.retry(
                "local", value.task_id, following, bridge.security.grant("local", following)
            )


async def cli(*arguments, env=None):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "kirabridge.cli",
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await process.communicate()
    return process.returncode, stdout.decode(), stderr.decode()


async def test_cli_init_grant_run_and_idempotency(tmp_path):
    config = tmp_path / "local.toml"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    code, output, _ = await cli("init", str(config), "--workspace", str(workspace))
    assert code == 0
    assert config.stat().st_mode & 0o077 == 0
    code, _, _ = await cli("init", str(config), "--workspace", str(workspace))
    assert code == 1
    value = request(arguments={"path": str(workspace)})
    file = tmp_path / "request.json"
    file.write_text(value.model_dump_json())
    code, output, _ = await cli("--config", str(config), "run", str(file))
    assert code == 1 and json.loads(output)["error"]["code"] == "approval_required"
    code, output, _ = await cli("--config", str(config), "run", str(file), "--approve")
    assert code == 0 and json.loads(output)["state"] == "completed"
    code, output, _ = await cli("--config", str(config), "run", str(file))
    assert code == 0 and json.loads(output)["state"] == "completed"
    code, output, _ = await cli("--config", str(config), "audit")
    assert code == 0 and json.loads(output)["valid"]
