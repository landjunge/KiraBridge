"""Actual native transport awaits keep direct-read approval fresh; no OS child is run."""

import asyncio

import pytest
from test_macos_system_transport import CONTRACT, Child, response, transport

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.macos.system_transport import NativeSystemTransport
from kirabridge.read_query import ReadQuery, read_query_async


def configure_native_read(bridge, worker):
    bridge.system_modules.transport = worker
    bridge.macos.capability_probe.facts.update(platform="darwin", os_version="15.7.4")
    bridge.config.principals["local"].permission_level = "full"


def change_policy(bridge, change):
    policy = bridge.config.principals["local"]
    if change == "manual":
        policy.permission_level = "ask"
    else:
        policy.capabilities.remove("apps.list")


def restore_policy(bridge):
    policy = bridge.config.principals["local"]
    policy.permission_level = "full"
    if "apps.list" not in policy.capabilities:
        policy.capabilities.append("apps.list")


async def direct_read(bridge):
    return await read_query_async(
        bridge,
        "local",
        ReadQuery(operation="native.read", native_operation="apps.list", arguments={}),
    )


def no_task_traffic(bridge):
    for table in ("tasks", "events", "completion_notices"):
        assert bridge.store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("late_change", ["manual", "revoke"])
async def test_direct_read_rechecks_after_real_process_factory_await(
    bridge, monkeypatch, late_change
):
    entered, release = asyncio.Event(), asyncio.Event()
    child, launches = Child(response), []

    async def spawn(*args, **kwargs):
        launches.append((args, kwargs))
        entered.set()
        await release.wait()
        return child

    worker = NativeSystemTransport(process_factory=spawn)
    monkeypatch.setattr(worker, "snapshot_metadata", lambda: dict(CONTRACT))
    configure_native_read(bridge, worker)
    pending = asyncio.create_task(direct_read(bridge))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        change_policy(bridge, late_change)
        assert not child.requests
        release.set()
        with pytest.raises(BridgeError) as caught:
            await pending
        assert caught.value.code == (
            "approval_required" if late_change == "manual" else "forbidden"
        )
        # The newly spawned shared worker stays usable. The rejected operation
        # never reached Writer.write, so it neither consumed a request nor forced
        # a worker replacement with a new generation.
        assert worker.process is child and not child.killed and not child.stdin.closed
        assert child.requests == [] and len(launches) == 1
        assert bridge.native_queries.active == 0
        restore_policy(bridge)
        result = await direct_read(bridge)
        assert result["result"]["ok"] is True
        assert worker.process is child and len(launches) == len(child.requests) == 1
        assert child.requests[0]["operation"] == "apps.list"
        no_task_traffic(bridge)
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await worker.close()


@pytest.mark.parametrize("late_change", ["manual", "revoke"])
async def test_direct_read_rechecks_after_real_serial_lock_wait_without_replacing_worker(
    bridge, monkeypatch, late_change
):
    worker, child, launches = transport(monkeypatch, timeout=3)
    configure_native_read(bridge, worker)
    pending = None
    owns_lock = False
    try:
        first = await direct_read(bridge)
        generation = first["result"]["native_helper"]["generation"]
        await worker.lock.acquire()
        owns_lock = True
        pending = asyncio.create_task(direct_read(bridge))
        # The wrapper, provider, models and lock acquire contain no earlier
        # scheduling await: one turn reaches the held transport lock.
        await asyncio.sleep(0)
        assert bridge.native_queries.active == 1 and not pending.done()
        assert len(child.requests) == len(launches) == 1
        change_policy(bridge, late_change)
        worker.lock.release()
        owns_lock = False
        with pytest.raises(BridgeError) as caught:
            await pending
        assert caught.value.code == (
            "approval_required" if late_change == "manual" else "forbidden"
        )
        assert worker.process is child and worker.generation == generation
        assert not child.killed and not child.stdin.closed
        assert len(child.requests) == len(launches) == 1
        assert bridge.native_queries.active == 0
        restore_policy(bridge)
        result = await direct_read(bridge)
        assert result["result"]["native_helper"]["generation"] == generation
        assert len(launches) == 1 and len(child.requests) == 2
        assert [item["operation"] for item in child.requests] == ["apps.list", "apps.list"]
        no_task_traffic(bridge)
    finally:
        if owns_lock:
            worker.lock.release()
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await worker.close()
