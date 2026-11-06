"""All configured visible terminal routes share fresh admission and no history replay."""

import asyncio
import sys

import pytest
from conftest import request

from kirabridge.bridge_core.models import State
from kirabridge.permissions import decision
from kirabridge.task_manager.manager import TaskManager


def configure(bridge, principal):
    bridge.config.concurrency = 1
    bridge.config.visible_handoffs.enabled = True
    policy = bridge.config.principals["local"].model_copy(deep=True)
    policy.client_type = "chatgpt"
    policy.capabilities.append("session.inspect")
    bridge.config.principals[principal] = policy
    bridge.tasks.maintenance = None
    return policy.roots[0]


def command(operation, cwd, identifier):
    return request(
        operation,
        {"argv": [sys.executable, "-c", "pass"], "cwd": cwd},
        task_id=identifier,
    )


@pytest.mark.parametrize(
    ("principal", "operation"),
    [
        ("chatgpt", "terminal.execute"),
        ("voice_alias", "terminal.execute"),
        ("chatgpt", "admin.execute"),
        ("voice_alias", "admin.execute"),
    ],
)
async def test_historical_visible_routes_never_dispatch_after_start(bridge, principal, operation):
    cwd = configure(bridge, principal)
    visible_calls = []

    async def visible(task, args, running, *, progress=None, privileged=False):
        visible_calls.append((task["id"], privileged))
        await running({"execution_route": "visible_terminal"})
        return {"success": True}

    bridge.visible_terminal.execute = visible
    value = command(operation, cwd, "historical-command")
    assert decision(bridge.config, principal, operation)["authorized"]
    old = bridge.submit(principal, value, bridge.security.grant(principal, value))
    assert old["state"] == State.QUEUED
    # This ordinary read proves the normal dispatcher actually processed the queue.
    sentinel = request("file.list", {"path": cwd}, task_id="dispatcher-sentinel")
    bridge.submit(principal, sentinel, bridge.security.grant(principal, sentinel))
    await bridge.tasks.start()
    try:
        await bridge.tasks.wait(principal, sentinel.task_id, timeout=3)
        assert bridge.store.get(sentinel.task_id)["state"] == State.COMPLETED
        current = bridge.store.get(old["id"])
        assert current["state"] == State.QUEUED
        assert visible_calls == []
        assert bridge.submit(principal, value)["state"] == State.QUEUED
        observed = await bridge.tasks.wait_delivery(old["id"])
        assert observed["delivery"]["status"] == "not_admitted"
    finally:
        await bridge.tasks.stop()


@pytest.mark.parametrize("operation", ["terminal.execute", "admin.execute"])
async def test_fresh_alias_commands_use_native_admission_and_execute_once(bridge, operation):
    principal = "voice_alias"
    cwd = configure(bridge, principal)
    visible_calls = []

    async def visible(task, args, running, *, progress=None, privileged=False):
        visible_calls.append((task["id"], privileged))
        await running({"execution_route": "visible_terminal"})
        return {"success": True}

    bridge.visible_terminal.execute = visible
    await bridge.tasks.start()
    try:
        value = command(operation, cwd, "fresh-command")
        submitted = bridge.submit(principal, value, bridge.security.grant(principal, value))
        assert submitted["state"] == State.ACCEPTED
        result = await bridge.tasks.wait(principal, value.task_id, timeout=3)
        assert result["state"] == State.COMPLETED
        assert visible_calls == [(value.task_id, operation == "admin.execute")]
        assert bridge.submit(principal, value)["state"] == State.COMPLETED
        assert visible_calls == [(value.task_id, operation == "admin.execute")]
    finally:
        await bridge.tasks.stop()


async def test_fresh_alias_background_spawn_finishes_admission_not_execution(bridge):
    principal = "voice_alias"
    cwd = configure(bridge, principal)
    finish = asyncio.Event()

    async def executor(task, running, progress):
        await running({"evidence_type": "local_process_spawned", "pid": 42})
        await finish.wait()
        return {"success": True}

    bridge.tasks.executor = executor
    await bridge.tasks.start()
    try:
        value = request(
            "terminal.execute",
            {"argv": [sys.executable, "-c", "pass"], "cwd": cwd, "background": True},
            task_id="alias-background",
        )
        submitted = bridge.submit(principal, value, bridge.security.grant(principal, value))
        assert submitted["state"] == State.ACCEPTED
        async with asyncio.timeout(3):
            observed = await bridge.tasks.wait_delivery(value.task_id)
        assert observed["state"] == State.RUNNING
        assert observed["delivery"]["status"] == "process_started"
        assert observed["result"] is None
    finally:
        finish.set()
        await bridge.tasks.stop()


@pytest.mark.parametrize("operation", ["terminal.execute", "admin.execute"])
async def test_external_fresh_alias_approval_does_not_release_old_commands(bridge, operation):
    principal = "voice_alias"
    cwd = configure(bridge, principal)
    calls = []

    async def executor(task, running, progress):
        calls.append(task["id"])
        await running({"execution_route": "visible_terminal"})
        return {"success": True}

    bridge.tasks.executor = executor
    old = command(operation, cwd, "old-command")
    bridge.submit(principal, old, bridge.security.grant(principal, old))
    selected = command(operation, cwd, "fresh-approval")
    bridge.prepare(principal, selected)
    cli = TaskManager(bridge.config, bridge.store, bridge.security, executor)
    await bridge.tasks.start()
    try:
        cli.approve(selected.task_id)
        result = await bridge.tasks.wait(principal, selected.task_id, timeout=3)
        assert result["state"] == State.COMPLETED
        assert calls == [selected.task_id]
        assert bridge.store.get(old.task_id)["state"] == State.QUEUED
        assert not cli.native.active and not cli.workers
    finally:
        await bridge.tasks.stop()
