"""Existing task gateway wiring for minimized owned-audit observations."""

import pytest

from kirabridge.bridge_core.models import BridgeError, TaskRequest, canonical


async def invoke(bridge, task_id, operation, arguments, principal="local"):
    bridge.prepare(
        principal,
        TaskRequest(
            task_id=task_id,
            idempotency_key=task_id,
            operation=operation,
            arguments=arguments,
        ),
    )
    return await bridge.tasks.wait(principal, task_id)


async def test_actual_operation_reads_owned_audit_without_payload_or_duplicate_execution(
    bridge, config
):
    for policy in config.principals.values():
        policy.approval_mode = "automatic"
    async with bridge:
        original = await invoke(
            bridge,
            "obs-source",
            "file.write",
            {
                "path": config.principals["local"].roots[0] + "/synthetic.txt",
                "text": "synthetic-private-content-must-not-be-exported",
            },
        )
        assert original["state"] == "completed"
        before = dict(
            bridge.store.db.execute("SELECT * FROM tasks WHERE id='obs-source'").fetchone()
        )
        page = await invoke(
            bridge,
            "obs-read",
            "observations.read",
            {
                "task_ids": ["obs-source"],
                "limit": 50,
            },
        )
        assert page["state"] == "completed" and page["attempt"] == 1
        result = page["result"]
        assert result["events"] and not result["has_more"]
        assert result["project_completion_verified"] is False
        assert result["source_authenticated"] is False
        assert "synthetic-private-content" not in canonical(result)
        assert "synthetic.txt" not in canonical(result)
        assert not any(e.get("reported_status") == "turn_completed" for e in result["events"])
        repeated = await invoke(
            bridge,
            "obs-reread",
            "observations.read",
            {
                "task_ids": ["obs-source"],
                "limit": 50,
                "through_seq": result["through_seq"],
            },
        )
        assert repeated["result"]["events"] == result["events"]
        after = dict(
            bridge.store.db.execute("SELECT * FROM tasks WHERE id='obs-source'").fetchone()
        )
        assert before == after
        foreign = await invoke(
            bridge,
            "obs-foreign",
            "observations.read",
            {
                "task_ids": ["obs-source"],
            },
            principal="other",
        )
        assert foreign["state"] == "failed" and foreign["error"]["code"] == "not_found"
        assert foreign["result"] is None


async def test_observation_operation_requires_separate_capability(bridge, config):
    config.principals["local"].approval_mode = "automatic"
    config.principals["local"].capabilities.remove("observations.read")
    async with bridge:
        with pytest.raises(BridgeError) as error:
            await invoke(bridge, "obs-denied", "observations.read", {"task_ids": ["not-read"]})
        assert error.value.code == "forbidden"
