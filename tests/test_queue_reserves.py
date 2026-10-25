import pytest
from conftest import request, submit

from kirabridge.bridge_core.models import BridgeError


async def test_immediate_capacity_preserves_reserved_read_lane_without_backlog(bridge, config):
    config.concurrency = 1
    config.read_concurrency = 1
    async with bridge:
        assert (
            submit(bridge, request(arguments={"path": config.principals["local"].roots[0]}))[
                "state"
            ]
            == "accepted"
        )
        control = request("process.list", task_id="control")
        assert submit(bridge, control)["state"] == "accepted"
        with pytest.raises(BridgeError, match="capacity"):
            submit(
                bridge,
                control.model_copy(update={"task_id": "control-2", "idempotency_key": "control-2"}),
            )
        assert (
            bridge.store.db.execute("SELECT count(*) FROM tasks WHERE id='control-2'").fetchone()[0]
            == 0
        )
        assert (await bridge.tasks.wait("local", "control"))["state"] == "completed"
        assert (await bridge.tasks.wait("local", "task-1"))["state"] == "completed"


async def test_delegation_chain_has_exactly_32_task_limit(bridge, config):
    async with bridge:
        parent = None
        for index in range(32):
            value = request(
                arguments={"path": config.principals["local"].roots[0]},
                task_id=f"chain-{index}",
                parent=parent,
            )
            submit(bridge, value)
            assert (await bridge.tasks.wait("local", value.task_id))["state"] == "completed"
            parent = value.task_id
        with pytest.raises(BridgeError, match="32"):
            submit(
                bridge,
                request(
                    arguments={"path": config.principals["local"].roots[0]},
                    task_id="too-deep",
                    parent=parent,
                ),
            )
