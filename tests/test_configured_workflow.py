"""Configured source/journal provenance and actual reserved owned-stop task path."""

import asyncio
import os
import sys
from pathlib import Path

import pytest
from conftest import request, submit
from test_workflow_control_adapter import binding, noop, terminal, wait_session

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import WorkflowControlConfig
from kirabridge.bridge_core.models import BridgeError
from kirabridge.configured_workflow import ConfiguredWorkflowControl, package_fingerprint
from kirabridge.observation_export import export_workflow_observations


def configure(config, monkeypatch, tmp_path):
    source = os.environ.get("KIRABRIDGE_TEST_TOLLGATE_SOURCE")
    if not source:
        pytest.skip("Fixed actual TollGate source required")
    monkeypatch.syspath_prepend(str(Path(source) / "src"))
    config.workflow_control = WorkflowControlConfig(
        enabled=True,
        projects={"synthetic": config.principals["local"].roots},
        state_root=str(tmp_path / "control-state"),
        source_commit="a" * 40,
        source_package_sha256=package_fingerprint(Path(source) / "src/tollgate"),
    )
    return config


def owned_binding(bridge):
    task, metadata = binding(bridge)
    metadata["cwd"] = bridge.config.principals["local"].roots[0]
    with bridge.store.transaction():
        bridge.handoffs.save(metadata, task_id=task["id"], event="test.binding_fixture")
    return task, metadata


async def test_source_pin_failure_does_not_disable_ordinary_bridge(config, monkeypatch, tmp_path):
    configure(config, monkeypatch, tmp_path)
    config.workflow_control.source_package_sha256 = "0" * 64
    async with Bridge(config) as bridge:
        assert bridge.health("local")["dispatcher_active"]
        with pytest.raises(BridgeError) as error:
            bridge.workflow_control.check_configuration()
        assert error.value.code == "workflow_control_unavailable"
        assert not (tmp_path / "control-state").exists()


async def test_changed_or_recreated_journal_cannot_resume_old_binding(
    config, monkeypatch, tmp_path
):
    configure(config, monkeypatch, tmp_path)
    bridge = Bridge(config)
    try:
        task, metadata = owned_binding(bridge)
        async with bridge.workflow_control.bind_turn(task, metadata):
            assert (await terminal(bridge, task))["exit_code"] == 0
        stored = bridge.handoffs.get("local", "h-synthetic", 1)
        original = stored["control_assembly_ref"]
        config.workflow_control.state_root = str(tmp_path / "different-empty-state")
        changed = ConfiguredWorkflowControl(bridge)
        with pytest.raises(BridgeError) as error:
            async with changed.bind_turn(task, dict(stored)):
                pytest.fail("Different journal must not dispatch")
        assert error.value.code == "workflow_assembly_changed"
        config.workflow_control.state_root = str(tmp_path / "control-state")
        actual = bridge.workflow_control.adapters["synthetic"]
        actual.control._path(actual.scope(stored)).unlink()  # isolated deliberate loss
        with pytest.raises(BridgeError) as error:
            async with bridge.workflow_control.bind_turn(task, dict(stored)):
                pytest.fail("Recreated journal must not dispatch")
        assert error.value.code == "workflow_assembly_changed"
        assert bridge.handoffs.get("local", "h-synthetic", 1)["control_assembly_ref"] == original
    finally:
        bridge.store.close()


async def test_stop_routes_stored_scope_after_cwd_removed_and_disabled_history_cannot_resume(
    config,
    monkeypatch,
    tmp_path,
):
    configure(config, monkeypatch, tmp_path)
    bridge = Bridge(config)
    try:
        task, metadata = owned_binding(bridge)
        async with bridge.workflow_control.bind_turn(task, metadata):
            assert (await terminal(bridge, task))["exit_code"] == 0
        cwd = Path(metadata["cwd"])
        cwd.rename(cwd.with_name("renamed-workspace"))
        # A service restart reconstructs the router after the configured root
        # disappeared; existing journal scopes must remain stoppable.
        bridge.workflow_control = ConfiguredWorkflowControl(bridge)
        result = await bridge.workflow_control.stop("local", "h-synthetic", 1, "stop-missing-cwd")
        assert result["barrier"]["status"] == "EFFECTIVE"
        stored = bridge.handoffs.get("local", "h-synthetic", 1)
        bridge.workflow_control = None
        called = []

        async def forbidden(*args, **kwargs):
            called.append(True)
            pytest.fail("Disabled controlled history must not start an agent")

        monkeypatch.setattr(bridge.agents, "execute", forbidden)
        with pytest.raises(BridgeError) as error:
            await bridge.handoffs.turn(
                task, stored, "synthetic", 1, config.principals["local"], noop, noop
            )
        assert error.value.code == "workflow_stopped" and not called
    finally:
        bridge.store.close()


async def test_real_stop_task_uses_reserved_queue_and_terminates_only_owned_turn(
    config, monkeypatch, tmp_path
):
    configure(config, monkeypatch, tmp_path)
    config.concurrency = 1
    config.max_queued = 1
    for policy in config.principals.values():
        policy.approval_mode = "automatic"
    bridge = Bridge(config)
    task, metadata = owned_binding(bridge)

    async def running():
        async with bridge.workflow_control.bind_turn(task, metadata):
            return await terminal(bridge, task, 20)

    process = asyncio.create_task(running())
    try:
        await wait_session(bridge, task["id"])
        submit(
            bridge,
            request(
                "terminal.execute",
                {
                    "argv": [sys.executable, "-I", "-c", "import time;time.sleep(3)"],
                    "cwd": metadata["cwd"],
                    "timeout": 5,
                },
                task_id="busy-general",
            ),
        )
        bridge.prepare(
            "local",
            request(
                "workflow.stop",
                {
                    "handoff_id": "h-synthetic",
                    "revision": 1,
                    "stop_id": "stop-full-queue",
                },
                task_id="stop-full-queue",
            ),
        )
        async with bridge:
            async with asyncio.timeout(2):
                result = await bridge.tasks.wait("local", "stop-full-queue")
            assert result["state"] == "completed", result.get("error")
            assert result["result"]["barrier"]["status"] == "EFFECTIVE"
            assert result["result"]["process"]["items"] == [
                {"task_id": task["id"], "status": "exit_observed"}
            ]
            assert result["result"]["hard_cost_cap"] is False
            assert (await process)["exit_code"] != 0
            exported = export_workflow_observations(bridge, "local", task_ids=["stop-full-queue"])
            event = next(
                event
                for event in exported["events"]
                if event["event_type"] == "control.stop_effective"
            )
            assert event["bridge_task_id"] == "stop-full-queue"
            assert event["stop_state"] == "effective" and event["cost_kind"] == "unknown"
            assert event["project_id"] == "synthetic" and type(event["barrier_seq"]) is int
            provenance = next(
                item for item in exported["provenance"] if item["event_id"] == event["event_id"]
            )
            assert (
                provenance["execution_runtime"]["fingerprints"]["instance_id"]
                == (bridge.runtime["instance_id"])
            )
    finally:
        if not process.done():
            await bridge.terminal.terminate("local", task["id"])
            await process
        bridge.store.close()


async def test_missing_assembly_can_still_abort_owned_process_without_false_barrier(
    config, monkeypatch, tmp_path
):
    configure(config, monkeypatch, tmp_path)
    config.principals["local"].approval_mode = "automatic"
    bridge = Bridge(config)
    task, metadata = owned_binding(bridge)

    async def running():
        async with bridge.workflow_control.bind_turn(task, metadata):
            return await terminal(bridge, task, 20)

    process = asyncio.create_task(running())
    try:
        await wait_session(bridge, task["id"])
        config.workflow_control.source_package_sha256 = "0" * 64
        bridge.workflow_control = ConfiguredWorkflowControl(bridge)
        async with bridge:
            bridge.prepare(
                "local",
                request(
                    "workflow.stop",
                    {
                        "handoff_id": "h-synthetic",
                        "revision": 1,
                        "stop_id": "stop-missing-assembly",
                    },
                    task_id="stop-missing-assembly",
                ),
            )
            result = await bridge.tasks.wait("local", "stop-missing-assembly")
            assert result["state"] == "completed", result.get("error")
            assert result["result"]["barrier"]["status"] == "UNKNOWN"
            assert result["result"]["barrier"]["further_dispatch_blocked"] is False
            assert result["result"]["control_mode"] == "abort_only"
            assert result["result"]["process"]["items"][0]["status"] == "exit_observed"
            assert (await process)["exit_code"] != 0
            exported = export_workflow_observations(
                bridge, "local", task_ids=["stop-missing-assembly"]
            )
            event = next(
                event
                for event in exported["events"]
                if event["event_type"] == "control.stop_requested"
            )
            assert event["stop_state"] == "unknown"
            assert not {"project_id", "workflow_id", "control_ref", "barrier_seq"} & event.keys()
            # A later removal of the unavailable assembly cannot make an explicit
            # prior stop disappear and silently resume the old turn standalone.
            bridge.workflow_control = None
            stored = bridge.handoffs.get("local", "h-synthetic", 1)
            with pytest.raises(BridgeError) as error:
                await bridge.handoffs.turn(
                    task, stored, "synthetic", 1, config.principals["local"], noop, noop
                )
            assert error.value.code == "workflow_stopped"
            config.workflow_control.source_package_sha256 = metadata["control_source"][
                "source_package_sha256"
            ]
            bridge.workflow_control = ConfiguredWorkflowControl(bridge)
            async with asyncio.timeout(1):
                with pytest.raises(BridgeError) as error:
                    async with bridge.workflow_control.bind_turn(task, dict(stored)):
                        pytest.fail("Restored assembly must preserve explicit stop intent")
            assert error.value.code == "workflow_stopped"
    finally:
        if not process.done():
            await bridge.terminal.terminate("local", task["id"])
            await process
        bridge.store.close()


async def test_journal_wait_does_not_block_spawn_registration_or_owned_stop(
    config, monkeypatch, tmp_path
):
    configure(config, monkeypatch, tmp_path)
    bridge = Bridge(config)
    task, metadata = owned_binding(bridge)
    entered, release = asyncio.Event(), asyncio.Event()
    import kirabridge.terminal_manager as tm

    original_spawn = tm.spawn_process

    async def delayed_spawn(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original_spawn(*args, **kwargs)

    monkeypatch.setattr(tm, "spawn_process", delayed_spawn)

    async def running():
        async with bridge.workflow_control.bind_turn(task, metadata):
            return await terminal(bridge, task, 20)

    process = asyncio.create_task(running())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        stopping = asyncio.create_task(
            bridge.workflow_control.stop("local", "h-synthetic", 1, "stop-spawn-race")
        )
        # The journal lock is held across delayed_spawn. A synchronous lock wait
        # would prevent even this local coroutine from releasing the spawn.
        await asyncio.wait_for(asyncio.sleep(0.03), 0.2)
        assert not stopping.done()
        release.set()
        result = await asyncio.wait_for(stopping, 2)
        assert result["barrier"]["status"] == "EFFECTIVE"
        assert result["process"]["items"] == [{"task_id": task["id"], "status": "exit_observed"}]
        assert (await process)["exit_code"] != 0
    finally:
        release.set()
        if not process.done():
            if task["id"] in bridge.terminal.sessions:
                await bridge.terminal.terminate("local", task["id"])
            await process
        bridge.store.close()


async def test_actual_dispatch_rechecks_journal_epoch_after_assembly_check(
    config, monkeypatch, tmp_path
):
    configure(config, monkeypatch, tmp_path)
    bridge = Bridge(config)
    task, metadata = owned_binding(bridge)
    try:
        async with bridge.workflow_control.bind_turn(task, metadata):
            adapter = bridge.workflow_control.adapters["synthetic"]
            scope = adapter.scope(metadata)
            # Actual isolated journal replacement AFTER the router validated it.
            adapter.control._path(scope).unlink()
            replacement = adapter.control.control_identity(scope)
            assert replacement["journal_id"] != metadata["control_journal_id"]
            with pytest.raises(Exception) as failure:
                await terminal(bridge, task)
            assert getattr(failure.value, "code", None) == "JOURNAL_IDENTITY_CHANGED"
        assert not bridge.terminal.sessions
        assert adapter.control.status(scope)["attempts"] == []
    finally:
        bridge.store.close()


@pytest.mark.parametrize("change", ["root_mapping", "cwd_replaced"])
async def test_same_project_id_does_not_hide_changed_directory_binding(
    config, monkeypatch, tmp_path, change
):
    configure(config, monkeypatch, tmp_path)
    bridge = Bridge(config)
    task, metadata = owned_binding(bridge)
    try:
        async with bridge.workflow_control.bind_turn(task, metadata):
            assert (await terminal(bridge, task))["exit_code"] == 0
        if change == "root_mapping":
            config.workflow_control.projects = {"synthetic": [str(tmp_path)]}
        else:
            cwd = Path(metadata["cwd"])
            cwd.rename(cwd.with_name("previous-workspace"))
            cwd.mkdir()
        changed = ConfiguredWorkflowControl(bridge)
        stored = bridge.handoffs.get("local", "h-synthetic", 1)
        with pytest.raises(BridgeError) as error:
            async with changed.bind_turn(task, dict(stored)):
                pytest.fail("Project directory identity changed")
        assert error.value.code == "workflow_project_changed"
        assert not bridge.terminal.sessions
    finally:
        bridge.store.close()


async def test_stopped_answer_does_not_record_human_answer_or_change_waiting_binding(
    config, monkeypatch
):
    from kirabridge.bridge_core.config import AgentConfig
    from kirabridge.bridge_core.models import HandoffAnswerInput, digest
    from kirabridge.workflow_control_adapter import owned_stop

    config.agents["codex"] = AgentConfig(kind="codex", executable=sys.executable)
    bridge = Bridge(config)
    try:
        _, metadata = owned_binding(bridge)
        metadata.update(
            phase="awaiting_answer",
            question_id="q-synthetic",
            session_id="synthetic-session",
            turn_count=1,
            agent="codex",
            agent_profile_ref=digest(config.agents["codex"].model_dump()),
        )
        with bridge.store.transaction():
            bridge.handoffs.save(metadata, task_id="turn1", event="test.waiting_fixture")
        await owned_stop(
            bridge,
            "local",
            "h-synthetic",
            1,
            "stop-before-answer",
            scope=None,
            barrier={"status": "UNKNOWN", "further_dispatch_blocked": False},
        )
        before = bridge.handoffs.get("local", "h-synthetic", 1)
        calls = []

        async def forbidden(*args, **kwargs):
            calls.append(True)
            pytest.fail("Stopped human answer must not be recorded or sent to an agent")

        monkeypatch.setattr(bridge.handoffs, "rpc", forbidden)
        monkeypatch.setattr(bridge.agents, "execute", forbidden)
        args = HandoffAnswerInput(
            handoff_id="h-synthetic",
            revision=1,
            question_id="q-synthetic",
            answer_id="answer-after-stop",
            text="synthetic countercase",
        )
        answer = request("handoff.answer", args.model_dump(), task_id="answer-after-stop")
        submit(bridge, answer)
        task = bridge.store.claim("synthetic-worker", 30)
        with pytest.raises(BridgeError) as error:
            await bridge.handoffs.answer(task, args, noop, noop)
        assert error.value.code == "workflow_stopped" and calls == []
        assert bridge.handoffs.get("local", "h-synthetic", 1) == before
    finally:
        bridge.store.close()
