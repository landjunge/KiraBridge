"""A real reserved-worker stop precedes the first binding; no model or network."""

import asyncio
import json
import sys

from conftest import archive_task, request

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import digest

HANDOFF = "synthetic-not-yet-bound"


def isolated_bridge(config, monkeypatch, calls):
    bridge = Bridge(config)
    # No peer connection is needed to cancel an owned queued first start. Only
    # endpoint readiness is synthetic; ownership, preflight and queue stay real.
    monkeypatch.setattr(bridge.threaddesk, "check_configuration", lambda: None)

    async def forbidden(*args, **kwargs):
        calls.append("agent_or_peer_called")
        raise AssertionError("A stopped first start must never reach a model or peer")

    monkeypatch.setattr(bridge.agents, "execute", forbidden)
    monkeypatch.setattr(bridge.handoffs, "rpc", forbidden)
    return bridge


async def stop_queued_first_start(config, monkeypatch, *, foreign=False):
    config.concurrency = 1
    config.max_queued = 2 if foreign else 1
    config.agents["codex"] = AgentConfig(kind="codex", executable=sys.executable)
    for policy in config.principals.values():
        policy.approval_mode = "automatic"
    calls = []
    bridge = isolated_bridge(config, monkeypatch, calls)
    occupied = asyncio.Event()
    release = asyncio.Event()
    original_executor = bridge.tasks.executor

    async def executor(task, running, progress):
        if task["id"] == "occupied-general-worker":
            await running({"synthetic_local_worker_blocker": True})
            occupied.set()
            await asyncio.wait_for(release.wait(), 3)
            return {"success": True, "evidence": {"synthetic_worker_released": True}}
        return await original_executor(task, running, progress)

    monkeypatch.setattr(bridge.tasks, "executor", executor)
    args = {
        "handoff_id": HANDOFF,
        "revision": 1,
        "cwd": config.principals["local"].roots[0],
    }
    async with bridge:
        bridge.prepare(
            "local",
            request(
                "file.list",
                {"path": args["cwd"]},
                task_id="occupied-general-worker",
            ),
        )
        await asyncio.wait_for(occupied.wait(), 2)
        archive_task(bridge, request("handoff.start", args, task_id="own-first-start"))
        if foreign:
            archive_task(
                bridge, request("handoff.start", args, task_id="foreign-first-start"), "other"
            )
        assert bridge.store.db.execute("SELECT COUNT(*) FROM handoff_bindings").fetchone()[0] == 0
        assert bridge.store.get("own-first-start", "local")["state"] == "queued"
        bridge.prepare(
            "local",
            request(
                "workflow.stop",
                {"handoff_id": HANDOFF, "revision": 1, "stop_id": "stop-before-binding"},
                task_id="stop-before-binding",
            ),
        )
        async with asyncio.timeout(2):
            stopped = await bridge.tasks.wait("local", "stop-before-binding")
        assert stopped["state"] == "completed", stopped.get("error")
        assert bridge.store.get("occupied-general-worker", "local")["state"] == "running"
        assert bridge.store.get("own-first-start", "local")["state"] == "cancelled"
        assert stopped["result"]["queued"]["cancelled"] == 1
        assert stopped["result"]["control_mode"] == "abort_only"
        assert stopped["result"]["barrier"]["status"] == "UNKNOWN"
        assert stopped["result"]["barrier"]["further_dispatch_blocked"] is False
        assert stopped["result"]["process"]["items"] == []
        assert not bridge.terminal.sessions and calls == []
        assert bridge.store.db.execute("SELECT COUNT(*) FROM handoff_bindings").fetchone()[0] == 0
        records = bridge.store.db.execute(
            "SELECT at,kind,principal,task_id,previous,hash,metadata FROM audit "
            "WHERE kind='workflow.stop' AND principal='local' ORDER BY seq"
        ).fetchall()
        assert records
        for row in records:
            metadata = json.loads(row["metadata"])
            original = {key: row[key] for key in ("at", "kind", "principal", "task_id", "previous")}
            assert digest({**original, "metadata": metadata}) == row["hash"]
            assert metadata["binding_ref"] == bridge.handoffs.identity("local", HANDOFF, 1)
            assert metadata["status"] == "UNKNOWN"
            assert not {"run_id", "session_id"}.intersection(metadata)
        if foreign:
            # Same handoff/revision is deliberately not enough to cancel another
            # principal. Explicit cleanup occurs only after this assertion.
            assert bridge.store.get("foreign-first-start", "other")["state"] == "queued"
            bridge.tasks.cancel_queued("other", "foreign-first-start")
        release.set()
        await bridge.tasks.wait("local", "occupied-general-worker", timeout=2)
    return args, calls


async def assert_restart_refuses(config, monkeypatch, args, calls):
    restarted = isolated_bridge(config, monkeypatch, calls)
    async with restarted:
        restarted.prepare(
            "local", request("handoff.start", args, task_id="new-explicit-start-after-stop")
        )
        async with asyncio.timeout(2):
            result = await restarted.tasks.wait("local", "new-explicit-start-after-stop")
        assert result["state"] == "failed", result.get("error")
        error = result.get("error") or ((result.get("result") or {}).get("value") or {}).get(
            "error"
        )
        assert error and error["code"] == "workflow_stopped", result
        assert (
            restarted.store.db.execute("SELECT COUNT(*) FROM handoff_bindings").fetchone()[0] == 0
        )
        assert calls == [] and not restarted.terminal.sessions


async def test_reserved_stop_cancels_only_owned_unbound_start_and_survives_restart(
    config, monkeypatch
):
    args, calls = await stop_queued_first_start(config, monkeypatch, foreign=True)
    await assert_restart_refuses(config, monkeypatch, args, calls)


async def test_unbound_stop_survives_restart_with_actual_control_assembly_activated(
    config, monkeypatch, tmp_path
):
    from test_configured_workflow import configure

    # Reuse the existing exact-package source pin contract, not a fake TG gate.
    # It skips only this optional-source case when the reviewed source is absent.
    configure(config, monkeypatch, tmp_path)
    config.workflow_control.enabled = False
    args, calls = await stop_queued_first_start(config, monkeypatch)
    config.workflow_control.enabled = True
    await assert_restart_refuses(config, monkeypatch, args, calls)
