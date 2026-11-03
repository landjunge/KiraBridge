"""Task observations resolve output once while retaining ownership and durable snapshots."""

import asyncio
import json
import sqlite3
import sys
from types import SimpleNamespace

import pytest
from conftest import request

import kirabridge.task_observation as observations
from kirabridge.bridge_core.models import State
from kirabridge.mcp_gateway.server import create_server
from kirabridge.task_observation import observe_submitted_task, observe_task


def output_task(bridge, config, *, state=State.COMPLETED):
    config.principals["local"].approval_mode = "automatic"
    task = request(
        "terminal.execute",
        {"argv": [sys.executable, "-c", "pass"], "cwd": config.principals["local"].roots[0]},
        task_id="large-owned-output",
    )
    bridge.prepare("local", task)
    bridge.store.claim_exact("output-fixture", 30, task.task_id)
    bridge.store.transition(task.task_id, State.RUNNING, {"fixture": True}, owner="output-fixture")
    if state != State.RUNNING:
        complete_output(bridge, task.task_id, state=state)
    return task


def complete_output(bridge, task_id, *, state=State.COMPLETED):
    bridge.store.transition(
        task_id,
        state,
        {"fixture": True},
        result={"stdout": "synthetic output " * 8192, "stderr": "", "exit_code": 0},
        owner="output-fixture",
    )


def count_output_reads(bridge, monkeypatch):
    reads = []
    original = bridge.outputs.read

    def counted(principal, reference):
        reads.append((principal, reference["id"]))
        return original(principal, reference)

    monkeypatch.setattr(bridge.outputs, "read", counted)
    return reads


async def test_task_observe_reads_large_output_once_and_preserves_event_contract(
    bridge, config, monkeypatch
):
    task = output_task(bridge, config)
    expected = bridge.events("local", task.task_id)
    reads = count_output_reads(bridge, monkeypatch)
    result = await observe_task(bridge, "local", task.task_id, wait_seconds=18)
    assert result["complete"] and result["state"] == "completed"
    assert result["events"] == expected
    assert len(reads) == 1 and result["task"]["result"]["stdout"] == "synthetic output " * 8192
    assert not {"lease_owner", "lease_until", "idem"} & result["task"].keys()


async def test_chatgpt_task_get_reads_large_output_once_without_an_unused_event_page(
    bridge, config, monkeypatch
):
    task = output_task(bridge, config)
    config.principals["local"].client_type = "chatgpt"
    server = create_server(bridge)
    reads = count_output_reads(bridge, monkeypatch)
    statements = []
    bridge.store.db.set_trace_callback(statements.append)
    try:
        result = await server._tool_manager.get_tool("task_get").fn(task.task_id, None)
    finally:
        bridge.store.db.set_trace_callback(None)
    assert result["state"] == "completed" and len(reads) == 1
    assert result["result"]["stdout"] == "synthetic output " * 8192
    assert not any("FROM events" in sql for sql in statements)


async def test_nonnative_submit_only_resolves_final_output_without_native_delivery_wait(
    bridge, config, monkeypatch
):
    task = output_task(bridge, config, state=State.RUNNING)
    stored = bridge.store.get(task.task_id, "local", resolve_output=False)
    monkeypatch.setattr(bridge.tasks, "workers", [object()])
    reads = count_output_reads(bridge, monkeypatch)

    async def forbidden_native_wait(_task_id):
        raise AssertionError("A managed non-native task has no native delivery to observe")

    monkeypatch.setattr(bridge.tasks, "wait_delivery", forbidden_native_wait)

    async def completed_after_yield():
        await asyncio.sleep(0)
        complete_output(bridge, task.task_id)

    completion = asyncio.create_task(completed_after_yield())
    result = await observe_submitted_task(
        bridge,
        "local",
        stored,
        wait_seconds=2,
        deadline=asyncio.get_running_loop().time() + 18,
    )
    await completion
    assert result["state"] == "completed" and result["result"]["output_available"]
    assert len(reads) == 1
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1


async def test_task_get_corrupt_stored_result_keeps_its_sanitized_error_envelope(bridge, config):
    task = output_task(bridge, config)
    config.principals["local"].client_type = "chatgpt"
    bridge.store.db.execute(
        "UPDATE tasks SET result=? WHERE id=?", ("PRIVATE_INVALID_RESULT", task.task_id)
    )
    server = create_server(bridge)
    result = await server._tool_manager.get_tool("task_get").fn(task.task_id, None)
    assert result == {
        "error": {"code": "internal_error", "message": "Request could not be completed"}
    }


async def test_task_and_events_remain_one_snapshot_during_external_reconciliation(
    bridge, config, monkeypatch
):
    task = output_task(bridge, config, state=State.UNKNOWN)
    path = bridge.store.db.execute("PRAGMA database_list").fetchone()["file"]
    original = bridge.task

    def concurrent_completion(principal, task_id):
        result = original(principal, task_id)
        # A second connection commits after the snapshot's task read. WAL permits
        # the writer while the observer retains its original read transaction.
        with sqlite3.connect(path) as writer:
            writer.execute("UPDATE tasks SET state='completed' WHERE id=?", (task_id,))
            writer.execute(
                "INSERT INTO events(task_id,at,state,evidence) VALUES(?,1,'completed',?)",
                (task_id, json.dumps({"source": "synthetic external reconciliation"})),
            )
        return result

    monkeypatch.setattr(bridge, "task", concurrent_completion)
    result = await observe_task(bridge, "local", task.task_id, wait_seconds=18)
    assert result["state"] == "unknown" and result["execution_outcome_unknown"]
    assert result["task"]["diagnostic"]["task_id"] == task.task_id
    assert result["events"]["events"][-1]["state"] == "unknown"
    assert bridge.store.db.execute("SELECT state FROM tasks").fetchone()[0] == "completed"


async def test_first_fifty_milliseconds_use_only_ten_short_state_checks(
    bridge, config, monkeypatch
):
    task = output_task(bridge, config, state=State.RUNNING)
    delays, clock = [], [0.0]

    async def simulated_wait(seconds):
        delays.append(seconds)
        clock[0] += seconds
        if len(delays) == 11:
            complete_output(bridge, task.task_id)

    monkeypatch.setattr(
        observations,
        "asyncio",
        SimpleNamespace(
            get_running_loop=lambda: SimpleNamespace(time=lambda: clock[0]), sleep=simulated_wait
        ),
    )
    result = await observe_task(bridge, "local", task.task_id, wait_seconds=1)
    assert result["complete"] and delays == pytest.approx([0.005] * 10 + [0.05])


async def test_scheduler_stall_skips_missed_ticks_instead_of_catch_up_reads(
    bridge, config, monkeypatch
):
    task = output_task(bridge, config, state=State.RUNNING)
    delays, clock = [], [0.0]

    async def simulated_wait(seconds):
        delays.append(seconds)
        if len(delays) == 1:
            clock[0] += 0.08  # OS scheduling stalled past the entire short phase.
        else:
            clock[0] += seconds
            complete_output(bridge, task.task_id)

    monkeypatch.setattr(
        observations,
        "asyncio",
        SimpleNamespace(
            get_running_loop=lambda: SimpleNamespace(time=lambda: clock[0]), sleep=simulated_wait
        ),
    )
    result = await observe_task(bridge, "local", task.task_id, wait_seconds=1)
    assert result["complete"] and delays == pytest.approx([0.005, 0.02])
