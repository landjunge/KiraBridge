"""Owned dummy processes and actual optional TollGate source, no CLI/model calls."""

import asyncio
import importlib
import json
import os
import sys
from pathlib import Path

import pytest
from conftest import archive_task, request

from kirabridge.bridge_core.models import BridgeError, TerminalInput, UncertainExecution, canonical
from kirabridge.workflow_control_adapter import WorkflowControlAdapter, process_dispatch


@pytest.fixture
def control(bridge, tmp_path, monkeypatch):
    source = os.environ.get("KIRABRIDGE_TEST_TOLLGATE_SOURCE")
    if not source:
        pytest.skip("Reviewed optional TollGate process_start source required")
    sys.path.insert(0, str(Path(source) / "src"))
    module = importlib.import_module("tollgate.workflow_control")
    monkeypatch.setenv("TOLLGATE_HOME", str(tmp_path / "tollgate"))
    gate = module.WorkflowControl(
        root=tmp_path / "tollgate",
        lock_timeout_s=0.2,
        registered_process_actors={"codex": "codex-lane"},
    )
    adapter = WorkflowControlAdapter(
        bridge, gate, project_id="synthetic-project", actor_id="codex", consumer_id="codex-lane"
    )
    bridge.workflow_control = adapter
    yield adapter
    sys.path.remove(str(Path(source) / "src"))


def binding(bridge, identity="turn1", principal="local", handoff="h-synthetic"):
    args = {
        "handoff_id": handoff,
        "revision": 1,
        "cwd": bridge.config.principals[principal].roots[0],
    }
    archive_task(bridge, request("handoff.start", args, task_id=identity), principal=principal)
    task = bridge.store.claim("synthetic-worker", 30)
    assert task["id"] == identity
    metadata = {
        "id": bridge.handoffs.identity(principal, handoff, 1),
        "principal": principal,
        "handoff_id": handoff,
        "revision": 1,
        "original_task_id": "thread:task",
        "first_task_id": identity,
        "last_task_id": identity,
        "run_id": task["receipt"],
        "phase": "bound",
        "issued_content_hash": "a" * 64,
    }
    with bridge.store.transaction():
        bridge.store.db.execute(
            "INSERT INTO handoff_bindings VALUES(?,?,?,?,?,?,?,?)",
            (
                metadata["id"],
                principal,
                bridge.handoffs.operator_ref,
                handoff,
                1,
                identity,
                "b" * 64,
                canonical(metadata),
            ),
        )
    return task, metadata


async def noop(_):
    pass


async def terminal(bridge, task, seconds=0):
    policy = bridge.config.principals[task["principal"]]
    return await bridge.terminal.execute(
        task["id"],
        task["principal"],
        TerminalInput(
            argv=[sys.executable, "-I", "-c", f"import time;time.sleep({seconds})"],
            cwd=policy.roots[0],
            timeout=5,
        ),
        policy.roots,
        [sys.executable],
        noop,
    )


async def run_bound(bridge, control, task, metadata, seconds=0):
    with control.bind_turn(task, metadata):
        return await terminal(bridge, task, seconds)


async def wait_session(bridge, identity):
    async with asyncio.timeout(3):
        while identity not in bridge.terminal.sessions:
            await asyncio.sleep(0.01)


async def test_durable_pre_spawn_marker_and_actual_registered_process_then_restart_no_replay(
    bridge, control, monkeypatch
):
    task, metadata = binding(bridge)
    import kirabridge.terminal_manager as tm

    original, observed = tm.spawn_process, []

    async def spawn(*args, **kwargs):
        data = json.loads(control.control._path(control.scope(metadata)).read_text())
        attempt = next(iter(data["attempts"].values()))
        assert attempt["state"] == "DISPATCH_ATTEMPTED" and not attempt["spawn_observed"]
        observed.append(True)
        return await original(*args, **kwargs)

    monkeypatch.setattr(tm, "spawn_process", spawn)
    result = await run_bound(bridge, control, task, metadata)
    assert result["exit_code"] == 0 and observed == [True]
    assert not bridge.terminal.sessions
    status = control.control.status(control.scope(metadata))
    assert status["attempts"][0]["spawn_observed"]
    assert status["budgets"] == [] and status["attempts"][0]["cost_kind"] == "unknown"
    # New assembly over the same durable journal cannot replay this turn.
    restarted = WorkflowControlAdapter(
        bridge,
        type(control.control)(
            root=control.control.root, registered_process_actors={"codex": "codex-lane"}
        ),
        project_id="synthetic-project",
        actor_id="codex",
        consumer_id="codex-lane",
    )
    with pytest.raises(BridgeError, match="stopped or already attempted"):
        await run_bound(bridge, restarted, task, metadata)
    assert observed == [True]
    # Context is reset after either success/failure: an unrelated standalone task
    # remains usable, without inheriting another turn's dispatch permission.
    monkeypatch.setattr(tm, "spawn_process", original)
    result = await terminal(bridge, {"id": "standalone", "principal": "local"})
    assert result["exit_code"] == 0


async def test_stop_cancels_only_owned_matching_queue_and_terminates_only_owned_process(
    bridge, control
):
    task, metadata = binding(bridge)
    foreign, _ = binding(bridge, "foreign", "other")
    own = asyncio.create_task(run_bound(bridge, control, task, metadata, 30))
    other = asyncio.create_task(terminal(bridge, foreign, 30))
    try:
        await wait_session(bridge, task["id"])
        await wait_session(bridge, foreign["id"])
        for identity, principal, handoff in [
            ("pending", "local", "h-synthetic"),
            ("foreign-pending", "other", "h-synthetic"),
            ("other-handoff", "local", "h-other"),
        ]:
            archive_task(
                bridge,
                request(
                    "handoff.start",
                    {
                        "handoff_id": handoff,
                        "revision": 1,
                        "cwd": bridge.config.principals[principal].roots[0],
                    },
                    task_id=identity,
                ),
                principal=principal,
            )
        bridge.config.max_queued = 1  # Already full; direct control path cannot wait behind work.
        result = await control.stop("local", "h-synthetic", 1, "stop1")
        assert result["barrier"]["status"] == "EFFECTIVE"
        assert result["process"]["items"] == [{"task_id": "turn1", "status": "exit_observed"}]
        assert result["queued"]["cancelled"] == 1
        assert bridge.store.get("pending")["state"] == "cancelled"
        assert bridge.store.get("foreign-pending")["state"] == "queued"
        assert bridge.store.get("other-handoff")["state"] == "queued"
        assert not other.done() and bridge.terminal.sessions["foreign"].process.returncode is None
        assert (await own)["terminated"]
        assert result["external_effect"] == "unknown" and not result["hard_cost_cap"]
    finally:
        if "foreign" in bridge.terminal.sessions:
            await bridge.terminal.terminate("other", "foreign")
        await asyncio.gather(own, other, return_exceptions=True)


async def test_stop_before_spawn_and_foreign_or_missing_grants_fail_closed(bridge, control):
    task, metadata = binding(bridge)
    with pytest.raises(BridgeError):
        await control.stop("other", "h-synthetic", 1, "foreign-stop")
    bridge.config.principals["local"].capabilities.remove("process.terminate")
    with pytest.raises(BridgeError):
        await control.stop("local", "h-synthetic", 1, "missing-grant")
    bridge.config.principals["local"].capabilities.append("process.terminate")
    assert (await control.stop("local", "h-synthetic", 1, "stop1"))["barrier"][
        "status"
    ] == "EFFECTIVE"
    with pytest.raises(BridgeError) as failure:
        await run_bound(bridge, control, task, metadata)
    assert failure.value.code == "workflow_start_blocked" and not bridge.terminal.sessions
    view = bridge.handoffs.view(metadata)
    assert view["control_mode"] == "stop_only" and not view["hard_cost_cap"]


async def test_child_context_and_wrong_owner_never_inherit_dispatch_permission(bridge, control):
    task, metadata = binding(bridge)
    with control.bind_turn(task, metadata):
        with pytest.raises(BridgeError) as wrong:
            async with process_dispatch(task["id"], "other"):
                pytest.fail("wrong principal")
        assert wrong.value.code == "workflow_process_owner"
        with pytest.raises(BridgeError) as child:
            await asyncio.create_task(terminal(bridge, task))
        assert child.value.code == "workflow_process_owner"
    assert not bridge.terminal.sessions


async def test_cancel_during_thread_lock_enter_releases_late_lock_without_spawn(bridge, control):
    task, metadata = binding(bridge)
    with control.control._transaction(control.scope(metadata)):
        pending = asyncio.create_task(run_bound(bridge, control, task, metadata, 30))
        await asyncio.sleep(0.04)
        pending.cancel()
        await asyncio.sleep(0.04)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(pending, 2)
    assert not bridge.terminal.sessions
    assert (await control.stop("local", "h-synthetic", 1, "after-cancel"))["barrier"][
        "status"
    ] == "EFFECTIVE"
    assert (
        control.control.status(control.scope(metadata))["attempts"][0]["state"] == "OUTCOME_UNKNOWN"
    )


async def test_cancel_during_actual_spawn_reaps_process_and_does_not_resume(
    bridge, control, monkeypatch
):
    task, metadata = binding(bridge)
    original = asyncio.create_subprocess_exec
    created, release, processes = asyncio.Event(), asyncio.Event(), []

    async def delayed(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        created.set()
        await release.wait()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed)
    pending = asyncio.create_task(run_bound(bridge, control, task, metadata, 30))
    await asyncio.wait_for(created.wait(), 2)
    pending.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(pending, 3)
    assert processes and processes[0].returncode is not None and not bridge.terminal.sessions
    with pytest.raises(BridgeError):
        await run_bound(bridge, control, task, metadata)


@pytest.mark.parametrize("failure_stage", ["session_registration", "post_spawn_commit"])
async def test_registration_or_post_spawn_commit_error_reaps_owned_process_and_retains_unknown(
    bridge, control, monkeypatch, failure_stage
):
    task, metadata = binding(bridge)
    import kirabridge.terminal_manager as tm

    original, processes = tm.spawn_process, []

    async def spawn(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(tm, "spawn_process", spawn)
    if failure_stage == "session_registration":

        def rejected(*args):
            raise RuntimeError("synthetic-registration-failure")

        monkeypatch.setattr(tm, "Session", rejected)
    else:
        original_commit = control.control._commit

        def rejected(path, data):
            if next(iter(data["attempts"].values()))["spawn_observed"]:
                raise OSError("synthetic-commit-failure")
            original_commit(path, data)

        monkeypatch.setattr(control.control, "_commit", rejected)
    with pytest.raises((RuntimeError, UncertainExecution)):
        await run_bound(bridge, control, task, metadata, 30)
    assert processes and processes[0].returncode is not None and not bridge.terminal.sessions
    status = control.control.status(control.scope(metadata))
    assert status["attempts"][0]["state"] == "OUTCOME_UNKNOWN"


def test_standalone_view_never_claims_tollgate_or_bounded_costs(bridge):
    _, metadata = binding(bridge)
    view = bridge.handoffs.view(metadata)
    assert view["control_mode"] == "standalone" and view["cost_kind"] == "unknown"
    assert not view["hard_cost_cap"]


async def test_stop_during_actual_spawn_is_pending_until_registration_then_effective(
    bridge, control, monkeypatch
):
    task, metadata = binding(bridge)
    import kirabridge.terminal_manager as tm

    original, reached, release = tm.spawn_process, asyncio.Event(), asyncio.Event()

    async def held_spawn(*args, **kwargs):
        process = await original(*args, **kwargs)
        reached.set()
        await release.wait()
        return process

    monkeypatch.setattr(tm, "spawn_process", held_spawn)
    pending = asyncio.create_task(run_bound(bridge, control, task, metadata, 30))
    try:
        await asyncio.wait_for(reached.wait(), 2)
        before = await control.stop("local", "h-synthetic", 1, "same-stop")
        assert before["barrier"]["status"] == "PENDING"
        assert not before["barrier"]["further_dispatch_blocked"]
        assert before["process"]["status"] == "not_observed"
        release.set()
        await wait_session(bridge, "turn1")
        after = await control.stop("local", "h-synthetic", 1, "same-stop")
        assert after["barrier"]["status"] == "EFFECTIVE"
        assert after["process"]["items"] == [{"task_id": "turn1", "status": "exit_observed"}]
        assert (await pending)["terminated"]
    finally:
        release.set()
        if "turn1" in bridge.terminal.sessions:
            await bridge.terminal.terminate("local", "turn1")
        await asyncio.gather(pending, return_exceptions=True)


async def test_controlled_history_cannot_resume_without_assembly_or_downgrade_bounded(
    bridge, control
):
    task, metadata = binding(bridge)
    metadata["control_mode"] = "bounded"
    with pytest.raises(BridgeError) as downgrade:
        with control.bind_turn(task, metadata):
            pytest.fail("bounded mode downgraded")
    assert downgrade.value.code == "workflow_control_mode"
    metadata["control_mode"] = "stop_only"
    del bridge.workflow_control
    with pytest.raises(BridgeError) as missing:
        await bridge.handoffs.turn(
            task, metadata, "synthetic", 1, bridge.config.principals["local"], noop, noop
        )
    assert missing.value.code == "workflow_control_unavailable" and not bridge.terminal.sessions


async def test_late_turn_metadata_save_cannot_erase_effective_stop_observation(bridge, control):
    task, metadata = binding(bridge)
    before = dict(metadata)
    stopped = await control.stop("local", "h-synthetic", 1, "durable-stop")
    assert stopped["barrier"]["status"] == "EFFECTIVE"
    # Mimic a turn/question/return saving the earlier in-memory metadata after a stop.
    before["phase"] = "awaiting_answer"
    with bridge.store.transaction():
        bridge.handoffs.save(before, task_id=task["id"], event="handoff.question")
        bridge.store.audit(
            "workflow.stop",
            "local",
            task["id"],
            {
                "binding_ref": metadata["id"],
                "status": "PENDING",
                "further_dispatch_blocked": False,
            },
        )
    current = bridge.handoffs.get("local", "h-synthetic", 1)
    view = bridge.handoffs.view(current)
    assert view["phase"] == "awaiting_answer"  # reported turn phase, not authority
    assert view["stop_observation"]["status"] == "EFFECTIVE"
    assert view["stop_observation"]["further_dispatch_blocked"] is True
    assert view["stop_observation"]["process_exit_current"] == "unknown"
    assert control.control.status(control.scope(metadata))["stopped"] is True
    with pytest.raises(BridgeError):
        await run_bound(bridge, control, task, current)


def test_stale_caller_metadata_cannot_downgrade_persisted_bounded_mode(bridge, control):
    task, metadata = binding(bridge)
    persisted = {**metadata, "control_mode": "bounded"}
    with bridge.store.transaction():
        bridge.handoffs.save(persisted, task_id=task["id"], event="handoff.control_attached")
    with pytest.raises(BridgeError) as failure:
        with control.bind_turn(task, metadata):
            pytest.fail("stale standalone metadata downgraded the persisted mode")
    assert failure.value.code == "workflow_control_mode"
    assert bridge.handoffs.get("local", "h-synthetic", 1)["control_mode"] == "bounded"


def test_inconsistent_or_modified_stop_record_is_unknown_not_effective(bridge):
    task, metadata = binding(bridge)
    with bridge.store.transaction():
        bridge.store.audit(
            "workflow.stop",
            "local",
            task["id"],
            {
                "binding_ref": metadata["id"],
                "status": "EFFECTIVE",
                "further_dispatch_blocked": False,
            },
        )
    assert bridge.handoffs.view(metadata)["stop_observation"]["status"] == "not_observed"
    with bridge.store.transaction():
        bridge.store.db.execute(
            "UPDATE audit SET metadata=? WHERE kind='workflow.stop'",
            (
                canonical(
                    {
                        "binding_ref": metadata["id"],
                        "status": "EFFECTIVE",
                        "further_dispatch_blocked": True,
                    }
                ),
            ),
        )
    assert bridge.handoffs.view(metadata)["stop_observation"]["status"] == "not_observed"


async def test_stop_audit_uses_actual_owned_stop_task_preflight_never_old_turn(bridge, control):
    from kirabridge.bridge_core.models import digest

    turn, metadata = binding(bridge)
    with bridge.store.transaction():
        bridge.store.audit(
            "task.preflight",
            "local",
            turn["id"],
            {
                "runtime": {"instance_id": "old-turn-runtime"},
            },
        )
        # Isolated source fixture for the Root-owned future workflow.stop wiring.
        # No production schema or Bridge input catalog is changed by this test.
        bridge.store.db.execute(
            "INSERT INTO tasks(id,principal,idem,request_hash,operation,args,"
            "state,created,updated,receipt) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                "actual-stop",
                "local",
                "actual-stop",
                "d" * 64,
                "workflow.stop",
                canonical({"handoff_id": "h-synthetic", "revision": 1, "stop_id": "stop-actual"}),
                "accepted",
                100,
                100,
                "stop-receipt",
            ),
        )
        bridge.store.audit(
            "task.preflight",
            "local",
            "actual-stop",
            {
                "runtime": {"instance_id": "actual-stop-runtime"},
            },
        )
    with pytest.raises(BridgeError):
        await control.stop("local", "h-synthetic", 1, "stop-actual", task_id=turn["id"])
    with pytest.raises(BridgeError):
        await control.stop("other", "h-synthetic", 1, "stop-actual", task_id="actual-stop")
    with pytest.raises(BridgeError):
        await control.stop("local", "h-synthetic", 1, "changed-request", task_id="actual-stop")
    result = await control.stop("local", "h-synthetic", 1, "stop-actual", task_id="actual-stop")
    record = bridge.store.db.execute(
        "SELECT * FROM audit WHERE kind='workflow.stop' ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    evidence = json.loads(record["metadata"])
    assert record["task_id"] == "actual-stop" and evidence["bridge_task_id"] == "actual-stop"
    assert evidence["original_task_id"] == "thread:task"
    assert (
        evidence["project_id"] == "synthetic-project" and evidence["workflow_id"] == metadata["id"]
    )
    assert evidence["control_ref"] == digest(
        {"project_id": "synthetic-project", "workflow_id": metadata["id"]}
    )
    assert (
        evidence["stop_state"] == "EFFECTIVE"
        and evidence["barrier_seq"] == result["barrier"]["barrier_seq"]
    )
    runtime = bridge.store.db.execute(
        "SELECT metadata FROM audit WHERE principal=? AND task_id=? "
        "AND kind='task.preflight' AND seq<=? ORDER BY seq DESC LIMIT 1",
        (record["principal"], record["task_id"], record["seq"]),
    ).fetchone()
    assert json.loads(runtime[0])["runtime"]["instance_id"] == "actual-stop-runtime"
    await control.stop("local", "h-synthetic", 1, "host-probe")
    host = bridge.store.db.execute(
        "SELECT task_id,metadata FROM audit WHERE kind='workflow.stop' ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert host["task_id"] is None and "bridge_task_id" not in json.loads(host["metadata"])


async def test_invalid_stop_id_does_not_cancel_queued_work(bridge, control):
    binding(bridge)
    archive_task(
        bridge,
        request(
            "handoff.start",
            {
                "handoff_id": "h-synthetic",
                "revision": 1,
                "cwd": bridge.config.principals["local"].roots[0],
            },
            task_id="still-queued",
        ),
    )
    with pytest.raises(BridgeError) as failure:
        await control.stop("local", "h-synthetic", 1, "invalid\nstop")
    assert failure.value.code == "invalid_workflow_stop"
    assert bridge.store.get("still-queued")["state"] == "queued"
    assert not bridge.store.db.execute(
        "SELECT seq FROM audit WHERE kind='workflow.stop'"
    ).fetchall()


async def test_owned_abort_without_assembly_ends_only_owned_process_without_scope_claim(bridge):
    from kirabridge.workflow_control_adapter import owned_stop

    task, metadata = binding(bridge)
    foreign, _ = binding(bridge, "foreign-abort", "other")
    own = asyncio.create_task(terminal(bridge, task, 30))
    other = asyncio.create_task(terminal(bridge, foreign, 30))
    try:
        await wait_session(bridge, task["id"])
        await wait_session(bridge, foreign["id"])
        value = await owned_stop(
            bridge,
            "local",
            "h-synthetic",
            1,
            "no-assembly",
            scope=None,
            barrier={"status": "EFFECTIVE", "further_dispatch_blocked": True},
            control_error="SECRET_SHAPED_LIKE_AN_ERROR_CODE",
        )
        assert value["control_mode"] == "abort_only"
        assert (
            value["barrier"]["status"] == "UNKNOWN"
            and not value["barrier"]["further_dispatch_blocked"]
        )
        assert value["process"]["items"] == [{"task_id": "turn1", "status": "exit_observed"}]
        assert value["control_error"] == "workflow_control_unavailable"
        assert "SECRET_SHAPED_LIKE_AN_ERROR_CODE" not in canonical(value)
        assert (await own)["terminated"] and not other.done()
        row = bridge.store.db.execute(
            "SELECT task_id,metadata FROM audit WHERE kind='workflow.stop' "
            "ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        record = json.loads(row["metadata"])
        assert row["task_id"] is None and record["original_task_id"] == "thread:task"
        assert not {
            "project_id",
            "workflow_id",
            "control_ref",
            "barrier_seq",
            "bridge_task_id",
        }.intersection(record)
        assert bridge.handoffs.view(metadata)["stop_observation"]["control_mode"] == "abort_only"
    finally:
        if "foreign-abort" in bridge.terminal.sessions:
            await bridge.terminal.terminate("other", "foreign-abort")
        await asyncio.gather(own, other, return_exceptions=True)


async def test_owned_abort_helper_foreign_missing_rights_or_wrong_task_has_no_effect(bridge):
    from kirabridge.workflow_control_adapter import owned_stop

    task, _ = binding(bridge)
    archive_task(
        bridge,
        request(
            "handoff.start",
            {
                "handoff_id": "h-synthetic",
                "revision": 1,
                "cwd": bridge.config.principals["local"].roots[0],
            },
            task_id="pending-abort",
        ),
    )
    for principal, task_id in [("other", None), ("local", task["id"])]:
        with pytest.raises(BridgeError):
            await owned_stop(
                bridge,
                principal,
                "h-synthetic",
                1,
                "invalid-owner",
                task_id=task_id,
                barrier={"status": "UNKNOWN"},
            )
    bridge.config.principals["local"].capabilities.remove("process.terminate")
    with pytest.raises(BridgeError):
        await owned_stop(
            bridge, "local", "h-synthetic", 1, "invalid-rights", barrier={"status": "UNKNOWN"}
        )
    assert bridge.store.get("pending-abort")["state"] == "queued"
    assert not bridge.store.db.execute(
        "SELECT seq FROM audit WHERE kind='workflow.stop'"
    ).fetchall()
