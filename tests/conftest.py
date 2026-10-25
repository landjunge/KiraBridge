import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

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
    result = Config(
        data_dir=str(tmp_path / "state"),
        concurrency=2,
        principals={"local": policy, "other": policy.model_copy(deep=True)},
    )
    # Unit-test legacy adapters independently. No persisted configuration can
    # disable the production visible route (its parser accepts Literal[True]).
    result.visible_handoffs.enabled = False
    return result


@pytest.fixture
def bridge(config):
    instance = Bridge(config)

    @asynccontextmanager
    async def isolated_clipboard(text):
        # Unit fixtures must never read or modify the operator's real clipboard.
        yield SimpleNamespace(generation=1, restore_status="restored")

    instance.sessions.terminal_app.clipboard_owner = isolated_clipboard
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


def archive_task(bridge, value, principal="local", **kwargs):
    """Seed a pre-upgrade journal for read/migration tests; never admit execution.

    Execution tests must start the dispatcher and use submit/prepare instead.
    """
    policy = bridge.config.principals[principal]
    review = policy.model_copy(deep=True)
    review.approval_mode = "manual"
    review.permission_level = "ask"
    review.automatic_operations = []
    try:
        bridge.config.principals[principal] = review
        bridge.prepare(principal, value, **kwargs)
    finally:
        bridge.config.principals[principal] = policy
    from kirabridge.bridge_core.models import State

    bridge.store.transition(value.task_id, State.QUEUED, {"legacy_fixture": True})
    return bridge.store.get(value.task_id, principal)


class DomainOnlyTeamPort:
    """Nonexecuting port for team-domain tests; real MCP tests use the real receiver."""

    accepting = True

    def check(self, assignee):
        pass

    def submit(self, work_id, *, existing=False):
        pass
