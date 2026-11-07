"""Native admission uses synthetic executors, never real Terminal or agent sessions."""

import asyncio

import pytest
from conftest import request

from kirabridge.bridge_core.config import VisibleTerminalBinding
from kirabridge.bridge_core.models import BridgeError, State, UncertainExecution
from kirabridge.task_manager.manager import TaskManager


def setup_native(bridge):
    bridge.config.concurrency = 1
    bridge.config.visible_handoffs.enabled = True
    bridge.config.visible_handoffs.bindings = {
        agent: VisibleTerminalBinding(
            pane_id=f"terminal:{number}:ttys00{number}",
            expected_pid=number + 100,
            agent_pid=number + 200,
            ready_pattern="ready",
        )
        for agent, number in [("codex", 1), ("grok", 2)]
    }
    bridge.tasks.preflight = None
    bridge.tasks.maintenance = None


def enqueue(bridge, key, agent="codex", *, pending=False):
    value = request(
        "agent.execute", {"agent": agent, "prompt": "synthetic", "cwd": "/tmp"}, task_id=key
    )
    token = "" if pending else bridge.security.grant("local", value)
    return bridge.tasks.enqueue("local", value, token, pending=pending)


async def tick_until(predicate):
    async with asyncio.timeout(1):
        while not predicate():
            await asyncio.sleep(0)


async def test_different_native_targets_execute_without_waiting_for_prior_reply(bridge):
    setup_native(bridge)
    entered = []
    finish = asyncio.Event()

    async def executor(task, running, progress):
        entered.append(task["id"])
        await running({"handoff_id": task["id"], "state": "sent"})
        await finish.wait()
        return {"success": True}

    bridge.tasks.executor = executor
    await bridge.tasks.start()
    try:
        first = enqueue(bridge, "codex-first")
        second = enqueue(bridge, "grok-first", "grok")
        await tick_until(lambda: len(entered) == 2)
        assert first["state"] == second["state"] == State.ACCEPTED
        assert entered == [first["id"], second["id"]]
        observed = await bridge.tasks.wait_delivery(first["id"])
        assert observed["state"] == State.RUNNING
        assert observed["delivery"]["status"] == "confirmed_input"
        # Neither an identical key nor another record for this pane repeats input.
        assert enqueue(bridge, "codex-first")["id"] == first["id"]
        refused = enqueue(bridge, "codex-second")
        assert refused["state"] == State.FAILED
        assert refused["error"]["code"] == "execution_busy"
        assert refused["evidence"]["terminal_input_attempted"] is False
        assert entered == [first["id"], second["id"]]
    finally:
        finish.set()
        await bridge.tasks.stop()


async def test_historical_queued_native_is_not_claimed_on_start(bridge):
    setup_native(bridge)
    called = []

    async def executor(task, running, progress):
        called.append(task["id"])
        await running({"handoff_id": task["id"], "state": "sent"})
        return {"success": True}

    bridge.tasks.executor = executor
    old = enqueue(bridge, "old-unadmitted")
    assert old["state"] == State.QUEUED
    await bridge.tasks.start()
    try:
        await asyncio.sleep(0.02)
        observed = await bridge.tasks.wait_delivery(old["id"])
        assert observed["state"] == State.QUEUED
        assert observed["delivery"]["status"] == "not_admitted"
        assert observed["error"]["code"] == "native_delivery_not_admitted"
        assert not called
        # Reading/reusing the original key is not a fresh admission.
        enqueue(bridge, "old-unadmitted")
        await asyncio.sleep(0)
        assert not called
    finally:
        await bridge.tasks.stop()


@pytest.mark.parametrize(
    "code", ["visible_target_busy", "session_busy", "session_selection_changed"]
)
async def test_preinput_failure_is_immediate_durable_and_not_retried(bridge, code):
    setup_native(bridge)
    called = []

    async def executor(task, running, progress):
        called.append(task["id"])
        raise BridgeError(code, "synthetic refusal")

    bridge.tasks.executor = executor
    await bridge.tasks.start()
    try:
        task = enqueue(bridge, "refused")
        observed = await bridge.tasks.wait_delivery(task["id"])
        assert observed["state"] == State.FAILED
        assert observed["error"]["code"] == code
        assert observed["evidence"]["terminal_input_attempted"] is False
        assert observed["evidence"]["safe_to_retry"] is False
        assert observed["evidence"]["automatic_retry"] is False
        enqueue(bridge, "refused")
        assert called == [task["id"]]
    finally:
        await bridge.tasks.stop()


async def test_native_input_attempt_is_not_return_confirmation(bridge):
    setup_native(bridge)
    finish = asyncio.Event()

    async def executor(task, running, progress):
        await running({"terminal_input_attempted": True, "return_sent": False})
        await finish.wait()
        raise UncertainExecution("visible_submit_unknown", "synthetic uncertain return")

    bridge.tasks.executor = executor
    await bridge.tasks.start()
    try:
        task = enqueue(bridge, "possible-input")
        observed = await bridge.tasks.wait_delivery(task["id"])
        assert observed["state"] == State.RUNNING
        assert observed["delivery"]["status"] == "input_attempted"
        finish.set()
        await tick_until(lambda: bridge.store.get(task["id"])["state"] == State.UNKNOWN)
        assert bridge.store.get(task["id"])["error"]["code"] == "visible_submit_unknown"
    finally:
        finish.set()
        await bridge.tasks.stop()


async def test_preinput_timeout_is_bounded_and_cannot_replay(bridge):
    setup_native(bridge)
    bridge.tasks.native.timeout = 0.02

    async def executor(task, running, progress):
        await asyncio.Event().wait()

    bridge.tasks.executor = executor
    await bridge.tasks.start()
    try:
        task = enqueue(bridge, "deadline")
        async with asyncio.timeout(1):
            await bridge.tasks.wait_delivery(task["id"])
            await tick_until(lambda: bridge.store.get(task["id"])["state"] == State.FAILED)
        observed = bridge.store.get(task["id"])
        assert observed["error"]["code"] == "native_admission_timeout"
        assert observed["evidence"]["terminal_input_attempted"] is False
        assert observed["evidence"]["automatic_retry"] is False
        enqueue(bridge, "deadline")
        assert bridge.store.get(task["id"])["state"] == State.FAILED
    finally:
        await bridge.tasks.stop()


async def test_manual_approval_admits_only_exact_selected_record(bridge):
    setup_native(bridge)
    called = []

    async def executor(task, running, progress):
        called.append(task["id"])
        await running({"handoff_id": task["id"], "state": "sent"})
        return {"success": True}

    bridge.tasks.executor = executor
    await bridge.tasks.start()
    try:
        first = enqueue(bridge, "manual-first", pending=True)
        second = enqueue(bridge, "manual-second", pending=True)
        assert first["state"] == second["state"] == State.CREATED
        assert (await bridge.tasks.wait_delivery(first["id"]))["delivery"][
            "status"
        ] == "pending_approval"
        assert not called
        bridge.tasks.approve(first["id"])
        await bridge.tasks.wait_delivery(first["id"])
        assert called == [first["id"]]
        assert bridge.store.get(second["id"])["state"] == State.CREATED
    finally:
        await bridge.tasks.stop()


@pytest.mark.parametrize("proof", ["accepted_event", "old_evidence", "hold", "withdrawal"])
async def test_exact_native_claim_refuses_historical_execution_or_delivery_guards(bridge, proof):
    setup_native(bridge)
    task = enqueue(bridge, "guarded")
    if proof == "accepted_event":
        bridge.store.db.execute(
            "INSERT INTO events(task_id,at,state,evidence) VALUES(?,1,'accepted','{}')",
            (task["id"],),
        )
    elif proof == "old_evidence":
        bridge.store.db.execute(
            "UPDATE tasks SET evidence=? WHERE id=?",
            ('{"terminal_input_attempted":true}', task["id"]),
        )
    elif proof == "hold":
        bridge.store.db.execute(
            "INSERT INTO queue_holds VALUES('tasks',?,'local',1,'preserve')", (task["id"],)
        )
    else:
        bridge.store.db.execute(
            "INSERT INTO queue_withdrawals VALUES('tasks',?,'local',1,'digest')", (task["id"],)
        )
    assert bridge.store.claim_exact("synthetic-owner", 30, task["id"]) is None
    assert bridge.store.get(task["id"])["state"] == State.QUEUED


async def test_shutdown_before_coroutine_entry_closes_only_owned_observations(bridge):
    setup_native(bridge)
    called = []

    async def executor(task, running, progress):
        called.append(task["id"])
        await running({"handoff_id": task["id"], "state": "sent"})
        return {"success": True}

    bridge.tasks.executor = executor
    await bridge.tasks.start()
    task = enqueue(bridge, "stop-before-entry")
    event = bridge.tasks.native.events[task["id"]]
    # No yield between enqueue and stop: the executor must never be entered.
    await bridge.tasks.stop()
    async with asyncio.timeout(0.5):
        observed = await bridge.tasks.wait_delivery(task["id"])
    assert observed["state"] == State.UNKNOWN
    assert observed["evidence"]["reason"] == "native_dispatcher_stopped"
    assert observed["evidence"]["execution_stop_claimed"] is False
    assert event.is_set()
    assert not called
    assert not bridge.tasks.native.active
    assert not bridge.tasks.native.events
    assert not bridge.tasks.native.targets
    await bridge.tasks.start()
    try:
        enqueue(bridge, "stop-before-entry")
        await asyncio.sleep(0)
        assert not called  # Restart/readback cannot execute the original ID.
        new = enqueue(bridge, "new-after-stop")
        await bridge.tasks.wait_delivery(new["id"])
        assert called == [new["id"]]
        assert bridge.store.get(task["id"])["state"] == State.UNKNOWN
    finally:
        await bridge.tasks.stop()


async def test_inserted_progress_without_sent_confirmation_times_out_unknown(bridge):
    setup_native(bridge)
    bridge.tasks.native.timeout = 0.02

    async def executor(task, running, progress):
        await progress({"handoff_id": task["id"], "state": "inserted"})
        await asyncio.Event().wait()

    bridge.tasks.executor = executor
    await bridge.tasks.start()
    try:
        task = enqueue(bridge, "inserted-unknown")
        async with asyncio.timeout(1):
            await bridge.tasks.wait_delivery(task["id"])
            await tick_until(lambda: bridge.store.get(task["id"])["state"] == State.UNKNOWN)
        observed = bridge.store.get(task["id"])
        assert observed["error"]["code"] == "native_admission_timeout"
        assert observed["evidence"]["side_effect_possible"] is True
        assert observed["evidence"]["automatic_retry"] is False
        await bridge.tasks.stop()
        await bridge.tasks.start()
        enqueue(bridge, "inserted-unknown")
        assert bridge.store.get(task["id"])["state"] == State.UNKNOWN
        assert not bridge.tasks.native.active
    finally:
        await bridge.tasks.stop()


async def test_two_aliases_of_same_native_pane_cannot_dispatch_concurrently(bridge):
    setup_native(bridge)
    bridge.config.visible_handoffs.bindings["grok"] = bridge.config.visible_handoffs.bindings[
        "codex"
    ].model_copy()
    finish = asyncio.Event()
    called = []

    async def executor(task, running, progress):
        called.append(task["id"])
        await running({"handoff_id": task["id"], "state": "sent"})
        await finish.wait()
        return {"success": True}

    bridge.tasks.executor = executor
    await bridge.tasks.start()
    try:
        first = enqueue(bridge, "shared-codex")
        await bridge.tasks.wait_delivery(first["id"])
        refused = enqueue(bridge, "shared-grok", "grok")
        assert refused["state"] == State.FAILED
        assert refused["error"]["code"] == "execution_busy"
        assert called == [first["id"]]
    finally:
        finish.set()
        await bridge.tasks.stop()


async def test_fresh_approval_from_separate_cli_manager_reuses_existing_dispatcher(bridge):
    setup_native(bridge)
    called = []

    async def executor(task, running, progress):
        called.append(task["id"])
        await running({"handoff_id": task["id"], "state": "sent"})
        return {"success": True}

    bridge.tasks.executor = executor
    old_queued = enqueue(bridge, "old-queued")
    selected = enqueue(bridge, "cli-approve", pending=True)
    standalone_cli = TaskManager(bridge.config, bridge.store, bridge.security, executor)
    await bridge.tasks.start()
    try:
        # cli.py creates its own manager and never starts another dispatcher.
        standalone_cli.approve(selected["id"])
        await tick_until(lambda: bridge.store.get(selected["id"])["state"] == State.COMPLETED)
        assert called == [selected["id"]]
        assert bridge.store.get(old_queued["id"])["state"] == State.QUEUED
        assert not standalone_cli.native.active
        assert not standalone_cli.workers
    finally:
        await bridge.tasks.stop()


async def test_chatgpt_legacy_terminal_alias_does_not_occupy_normal_worker(bridge):
    setup_native(bridge)
    bridge.config.principals["chatgpt"] = bridge.config.principals["local"].model_copy(deep=True)
    bridge.config.principals["chatgpt"].capabilities.append("session.inspect")
    finish = asyncio.Event()
    called = []

    async def executor(task, running, progress):
        called.append(task["id"])
        if task["id"] == "legacy-visible":
            await running({"execution_route": "visible_terminal"})
            await finish.wait()
        else:
            await running({"synthetic_operation": task["operation"]})
        return {"success": True}

    bridge.tasks.executor = executor
    await bridge.tasks.start()
    try:
        legacy = request(
            "terminal.execute", {"argv": ["synthetic"], "cwd": "/tmp"}, task_id="legacy-visible"
        )
        token = bridge.security.grant("chatgpt", legacy)
        accepted = bridge.tasks.enqueue("chatgpt", legacy, token)
        assert accepted["state"] == State.ACCEPTED
        observed = await bridge.tasks.wait_delivery(legacy.task_id)
        assert observed["delivery"]["status"] == "input_attempted"
        other = request(
            "file.write", {"path": "/synthetic", "text": "synthetic"}, task_id="normal-free"
        )
        token = bridge.security.grant("local", other)
        bridge.tasks.enqueue("local", other, token)
        await tick_until(lambda: bridge.store.get(other.task_id)["state"] == State.COMPLETED)
        assert bridge.store.get(legacy.task_id)["state"] == State.RUNNING
        assert called == [legacy.task_id, other.task_id]
    finally:
        finish.set()
        await bridge.tasks.stop()
