import sys

import pytest

from kirabridge.bridge_core.bridge import INPUTS, Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.bridge_core.models import TaskRequest


@pytest.fixture
def config(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = PrincipalConfig(
        capabilities=[*INPUTS, "bridge.health", "task.read", "task.cancel", "agent.inspect"],
        roots=[str(workspace)],
        executables=[sys.executable],
        agents=["codex", "grok"],
    )
    return Config(
        data_dir=str(tmp_path / "state"),
        concurrency=2,
        principals={"local": policy, "other": policy.model_copy(deep=True)},
    )


@pytest.fixture
def bridge(config):
    instance = Bridge(config)
    yield instance
    instance.store.close()


def request(operation="file.list", arguments=None, *, task_id="task-1", key=None, parent=None):
    return TaskRequest(
        task_id=task_id,
        idempotency_key=key or task_id,
        operation=operation,
        arguments=arguments or {},
        parent_id=parent,
    )


def submit(bridge, value, principal="local"):
    token = bridge.security.grant(principal, value)
    return bridge.submit(principal, value, token)
