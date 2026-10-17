import pytest
from conftest import request, submit

from kirabridge.bridge_core.models import BridgeError


def test_full_execution_queue_preserves_control_capacity(bridge, config):
    config.max_queued = 1
    config.max_control_queued = 1
    submit(bridge, request(arguments={"path": config.principals["local"].roots[0]}))
    control = request("process.list", task_id="control")
    assert submit(bridge, control)["state"] == "queued"
    with pytest.raises(BridgeError, match="capacity"):
        submit(
            bridge,
            control.model_copy(update={"task_id": "control-2", "idempotency_key": "control-2"}),
        )


def test_delegation_chain_has_exactly_32_task_limit(bridge, config):
    parent = None
    for index in range(32):
        value = request(
            arguments={"path": config.principals["local"].roots[0]},
            task_id=f"chain-{index}",
            parent=parent,
        )
        submit(bridge, value)
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
