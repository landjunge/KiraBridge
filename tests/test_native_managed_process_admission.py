"""Managed start admission is distinct from completion, input and historical replay."""

import asyncio
import copy
import sys
from types import SimpleNamespace

import pytest
from conftest import request

from kirabridge.bridge_core.models import State, UncertainExecution
from kirabridge.task_manager.direct import NativeAdmission


def configure(bridge):
    bridge.config.concurrency = 1
    bridge.config.visible_handoffs.enabled = True
    bridge.config.principals["chatgpt"] = bridge.config.principals["local"].model_copy(deep=True)
    bridge.config.principals["chatgpt"].capabilities.append("session.inspect")
    bridge.tasks.preflight = None
    bridge.tasks.maintenance = None


def enqueue(bridge, key, *, argv=None):
    value = request(
        "terminal.execute",
        {
            "argv": argv or [sys.executable, "-c", "pass"],
            "cwd": bridge.config.principals["chatgpt"].roots[0],
            "background": True,
            "timeout": 2,
        },
        task_id=key,
    )
    return bridge.tasks.enqueue("chatgpt", value, bridge.security.grant("chatgpt", value))


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


async def test_real_owned_process_outlives_admission_budget_and_finishes_once(bridge):
    configure(bridge)
    bridge.tasks.native.timeout = 0.25
    calls = []

    async def executor(task, running, progress):
        calls.append(task["id"])
        return await bridge.execute(task, running, progress)

    bridge.tasks.executor = executor
    await bridge.tasks.start()
    try:
        task = enqueue(
            bridge,
            "owned-long-process",
            argv=[sys.executable, "-c", "import time; time.sleep(.75); print('owned-complete')"],
        )
        async with asyncio.timeout(1):
            observed = await bridge.tasks.wait_delivery(task["id"])
        assert observed["state"] == State.RUNNING
        assert observed["delivery"]["status"] == "process_started"
        assert "not process completion" in observed["delivery"]["scope"]
        assert observed["result"] is None
        assert observed["evidence"] == {
            "pid": bridge.terminal.sessions[task["id"]].process.pid,
            "evidence_type": "local_process_spawned",
        }
        assert "terminal_input_attempted" not in observed["evidence"]
        await asyncio.sleep(0.35)  # Cross the scaled admission deadline while child still lives.
        assert bridge.store.get(task["id"])["state"] == State.RUNNING
        assert bridge.terminal.sessions[task["id"]].process.returncode is None
        assert task["id"] in bridge.tasks.native.active
        assert task["id"] in bridge.tasks.native.targets.values()
        assert task["id"] not in bridge.tasks.native.expired
        await until(lambda: bridge.store.get(task["id"])["state"] == State.COMPLETED)
        result = bridge.store.get(task["id"])
        assert result["result"]["exit_code"] == 0
        assert result["result"]["stdout"].strip() == "owned-complete"
        assert result["result"]["timed_out"] is False
        assert task["id"] not in bridge.terminal.sessions
        await until(lambda: not bridge.tasks.native.active)
        assert not bridge.tasks.native.managed_admissions
        enqueue(bridge, "owned-long-process", argv=task["args"]["argv"])
        assert calls == [task["id"]]
    finally:
        await bridge.tasks.stop()


async def test_background_history_and_old_idempotency_cannot_admit_or_spawn(bridge):
    configure(bridge)
    calls = []

    async def executor(task, running, progress):
        calls.append(task["id"])
        await running({"pid": 42, "evidence_type": "local_process_spawned"})
        return {"success": True}

    bridge.tasks.executor = executor
    old = enqueue(bridge, "historical-background")
    await bridge.tasks.start()
    try:
        await asyncio.sleep(0.12)  # Include the fresh-approval observer's first scan.
        observed = await bridge.tasks.wait_delivery(old["id"])
        assert observed["state"] == State.QUEUED
        assert observed["error"]["code"] == "native_delivery_not_admitted"
        enqueue(bridge, "historical-background")
        assert calls == []
        fresh = enqueue(bridge, "fresh-background")
        await until(lambda: bridge.store.get(fresh["id"])["state"] == State.COMPLETED)
        assert calls == [fresh["id"]]
        assert bridge.store.get(old["id"])["state"] == State.QUEUED
    finally:
        await bridge.tasks.stop()


async def test_waiter_cancellation_does_not_cancel_or_repeat_managed_execution(bridge):
    configure(bridge)
    entered, spawn, finish, cancelled = (asyncio.Event() for _ in range(4))
    calls = []

    async def executor(task, running, progress):
        calls.append(task["id"])
        entered.set()
        try:
            await spawn.wait()
            await running({"pid": 42, "evidence_type": "local_process_spawned"})
            await finish.wait()
            return {"success": True}
        except asyncio.CancelledError:
            cancelled.set()
            raise

    bridge.tasks.executor = executor
    await bridge.tasks.start()
    try:
        task = enqueue(bridge, "caller-cancelled")
        await entered.wait()
        waiter = asyncio.create_task(bridge.tasks.wait_delivery(task["id"]))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not cancelled.is_set()
        spawn.set()
        observed = await bridge.tasks.wait_delivery(task["id"])
        assert observed["delivery"]["status"] == "process_started"
        assert observed["state"] == State.RUNNING
        enqueue(bridge, "caller-cancelled")
        assert calls == [task["id"]] and not cancelled.is_set()
        finish.set()
        await until(lambda: bridge.store.get(task["id"])["state"] == State.COMPLETED)
    finally:
        finish.set()
        await bridge.tasks.stop()


@pytest.mark.parametrize("outcome", ["uncertain", "shutdown"])
async def test_spawn_admission_cannot_hide_later_unknown_or_shutdown(bridge, outcome):
    configure(bridge)
    finish, cleaned = asyncio.Event(), asyncio.Event()
    calls = []

    async def executor(task, running, progress):
        calls.append(task["id"])
        await running({"pid": 42, "evidence_type": "local_process_spawned"})
        try:
            await finish.wait()
            raise UncertainExecution("owned_process_unknown", "Synthetic post-start uncertainty")
        finally:
            cleaned.set()

    bridge.tasks.executor = executor
    await bridge.tasks.start()
    try:
        task = enqueue(bridge, "late-unknown")
        observed = await bridge.tasks.wait_delivery(task["id"])
        assert observed["delivery"]["status"] == "process_started"
        if outcome == "shutdown":
            await bridge.tasks.stop()
        else:
            finish.set()
        await until(lambda: bridge.store.get(task["id"])["state"] == State.UNKNOWN)
        current = bridge.store.get(task["id"])
        assert current["evidence"]["automatic_retry"] is False
        assert current["evidence"]["last_observation"]["evidence_type"] == "local_process_spawned"
        assert current["error"] is None or current["error"]["code"] == "owned_process_unknown"
        assert cleaned.is_set()
        await bridge.tasks.stop()
        await bridge.tasks.start()
        enqueue(bridge, "late-unknown")
        assert calls == [task["id"]]
        assert not bridge.tasks.native.active
        assert not bridge.tasks.native.managed_admissions
    finally:
        finish.set()
        await bridge.tasks.stop()


@pytest.mark.parametrize(
    "evidence", [None, {"pid": True, "evidence_type": "local_process_spawned"}]
)
async def test_unobserved_or_malformed_spawn_keeps_admission_deadline(bridge, evidence):
    configure(bridge)
    bridge.tasks.native.timeout = 0.02
    calls = []

    async def executor(task, running, progress):
        calls.append(task["id"])
        if evidence is not None:
            await running(evidence)
        await asyncio.Event().wait()

    bridge.tasks.executor = executor
    await bridge.tasks.start()
    try:
        task = enqueue(bridge, "no-valid-spawn")
        async with asyncio.timeout(1):
            await bridge.tasks.wait_delivery(task["id"])
            await until(
                lambda: bridge.store.get(task["id"])["state"] in {State.FAILED, State.UNKNOWN}
            )
        current = bridge.store.get(task["id"])
        assert current["state"] == (State.FAILED if evidence is None else State.UNKNOWN)
        assert current["error"]["code"] == "native_admission_timeout"
        assert current["evidence"]["automatic_retry"] is False
        enqueue(bridge, "no-valid-spawn")
        assert calls == [task["id"]]
    finally:
        await bridge.tasks.stop()


@pytest.mark.parametrize(
    "change",
    [
        "bool_pid",
        "zero_pid",
        "negative_pid",
        "large_pid",
        "string_pid",
        "missing_pid",
        "bare_pid",
        "other_marker",
        "other_operation",
        "other_principal",
        "background_false",
        "invalid_args",
        "changed_args",
        "no_active",
        "no_admitted_route",
        "not_accepting",
        "expired",
        "lost_lease",
        "accepted_state",
        "completed_state",
        "mismatched_pid",
        "mismatched_pid_type",
    ],
)
async def test_spawn_evidence_requires_exact_owned_fresh_managed_route(change):
    proof = {"pid": 42, "evidence_type": "local_process_spawned"}
    original = {
        "id": "owned",
        "operation": "terminal.execute",
        "principal": "chatgpt",
        "args": {"argv": ["synthetic"], "cwd": "/tmp", "background": True},
        "state": State.RUNNING,
        "lease_owner": "owner",
        "evidence": copy.deepcopy(proof),
    }
    task = copy.deepcopy(original)
    admission = NativeAdmission(
        SimpleNamespace(
            owner="owner",
            store=SimpleNamespace(get=lambda identifier: task),
        )
    )
    admission.accepting = True
    admission.events["owned"] = asyncio.Event()
    admission.active["owned"] = object()
    admission.status["owned"] = "admitting"
    admission.managed_admissions["owned"] = admission._route_identity(original)
    bad_pid = {
        "bool_pid": True,
        "zero_pid": 0,
        "negative_pid": -1,
        "large_pid": 2**31,
        "string_pid": "42",
    }
    if change in bad_pid:
        proof["pid"] = bad_pid[change]
    elif change == "missing_pid":
        proof.pop("pid")
    elif change == "bare_pid":
        proof.pop("evidence_type")
    elif change == "other_marker":
        proof["evidence_type"] = "untrusted_process"
    elif change == "other_operation":
        task["operation"] = "agent.execute"
    elif change == "other_principal":
        task["principal"] = "other"
    elif change == "background_false":
        task["args"]["background"] = False
    elif change == "invalid_args":
        task["args"].pop("argv")
    elif change == "changed_args":
        task["args"]["cwd"] = "/another"
    elif change == "no_active":
        admission.active.clear()
    elif change == "no_admitted_route":
        admission.managed_admissions.clear()
    elif change == "not_accepting":
        admission.accepting = False
    elif change == "expired":
        admission.expired.add("owned")
    elif change == "lost_lease":
        task["lease_owner"] = "different-runtime"
    elif change == "accepted_state":
        task["state"] = State.ACCEPTED
    elif change == "completed_state":
        task["state"] = State.COMPLETED
    elif change == "mismatched_pid":
        task["evidence"]["pid"] = 43
    elif change == "mismatched_pid_type":
        task["evidence"]["pid"] = 42.0
    admission.observe("owned", proof)
    assert not admission.events["owned"].is_set()
    assert admission.status["owned"] == "admitting"


async def test_agent_session_ends_admission_wait_without_claiming_completion():
    admission = NativeAdmission(SimpleNamespace(owner="owner", store=SimpleNamespace(get=lambda _id: {})))
    admission.timeout = 0.05
    event = asyncio.Event()
    admission.events["task"] = event
    admission.status["task"] = "admitting"
    execution = asyncio.create_task(asyncio.sleep(1))
    watch = asyncio.create_task(admission._watch("task", event, execution))
    admission.observe("task", {"event": "prompt_admitted", "session_id": "ses_1"})
    await watch
    assert event.is_set()
    assert not execution.cancelled()
    assert "task" not in admission.expired
    assert admission.status["task"] == "admitting"
    execution.cancel()
    blank = asyncio.Event()
    admission.events["blank"] = blank
    admission.observe("blank", {"event": "session_created", "session_id": ""})
    assert not blank.is_set()


@pytest.mark.parametrize("value", [True, False, "true", 1, None])
def test_background_route_matches_executor_strict_bool_validation(value):
    assert NativeAdmission._managed_background(
        {
            "operation": "terminal.execute",
            "principal": "chatgpt",
            "args": {"argv": ["synthetic"], "cwd": "/tmp", "background": value},
        }
    ) is (value is True)
