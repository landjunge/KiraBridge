"""Reserved capacity and identical rights for new and cached terminal tools."""

import asyncio
import sys
import time

import pytest
from conftest import request, submit
from test_mcp import http_bridge  # noqa: F401

from kirabridge.bridge_core.bridge import INPUTS
from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.operations import OPERATIONS
from kirabridge.permissions import decision
from kirabridge.read_query import ReadQuery, read_query_async

TARGET = {"pane_id": "terminal:123:ttys004", "expected_pid": 345}
# Declared before running the test: no normal-worker task may delay these reads
# beyond 2 s in the isolated integration fixture (the production read budget is 8 s).
SATURATED_NORMAL_BUDGET = 2.0


@pytest.fixture
def terminal_reads(bridge, config, monkeypatch):
    policy = config.principals["local"]
    policy.capabilities += ["session.inspect"]
    policy.permission_level = "medium"
    calls = []

    async def catalog(principal):
        bridge.security.principal(principal, "session.inspect")
        calls.append("catalog")
        return {"status": "available", "sessions": [TARGET]}

    async def read(principal, pane_id, expected_pid, *, max_bytes=65536):
        bridge.security.principal(principal, "session.inspect")
        if (pane_id, expected_pid) != (TARGET["pane_id"], TARGET["expected_pid"]):
            raise BridgeError("session_selection_changed", "Select exact current target")
        calls.append("read")
        return {**TARGET, "text": "EXACT EXISTING OUTPUT"[-max_bytes:]}

    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    monkeypatch.setattr(bridge.sessions, "read_observed", read)
    return calls


def test_registry_covers_all_operations_and_preserves_real_read_capability(config):
    assert set(OPERATIONS) == set(INPUTS)
    policy = config.principals["local"]
    policy.capabilities = ["session.inspect"]
    policy.permission_level = "medium"
    for name in ("session.catalog", "session.read"):
        spec = OPERATIONS[name]
        assert (spec.capability, spec.effect, spec.execution_class) == (
            "session.inspect",
            "read",
            "read",
        )
        assert decision(config, "local", name)["automatic"]
    policy.capabilities = ["session.catalog", "session.read"]
    assert not decision(config, "local", "session.read")["authorized"]


async def wait_running(bridge, ids):
    async with asyncio.timeout(3):
        while not all(bridge.store.get(identifier)["state"] == "running" for identifier in ids):
            await asyncio.sleep(0.01)


async def test_real_http_new_and_cached_tools_survive_all_normal_slots_busy(
    http_bridge,  # noqa: F811
    config,
    terminal_reads,
):
    bridge, endpoint = http_bridge
    ids = []
    for index in range(config.concurrency):
        identifier = f"occupy-normal-{index}"
        ids.append(identifier)
        submit(
            bridge,
            request(
                "terminal.execute",
                {
                    "argv": [sys.executable, "-c", "import time;time.sleep(60)"],
                    "cwd": config.principals["local"].roots[0],
                },
                task_id=identifier,
            ),
        )
    await wait_running(bridge, ids)
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        before = time.monotonic()
        for operation, args, tool in [
            ("session.catalog", {}, "session_catalog"),
            ("session.read", TARGET, "session_read"),
        ]:
            direct = (await clients.call("local", tool, args)).structuredContent
            query = (
                await clients.call(
                    "local", "read_query", {"query": {"operation": operation, **args}}
                )
            ).structuredContent
            task = request(operation, args, task_id="cached-" + operation.replace(".", "-"))
            queued = (
                await clients.call("local", "task_request", {"request": task.model_dump()})
            ).structuredContent
            assert queued["id"] == task.task_id
            legacy = await bridge.tasks.wait("local", task.task_id, SATURATED_NORMAL_BUDGET)
            assert legacy["state"] == "completed", legacy
            assert legacy["result"] == direct
            assert {key: value for key, value in query.items() if key != "operation"} == direct
        assert time.monotonic() - before < SATURATED_NORMAL_BUDGET
        assert all(bridge.store.get(identifier)["state"] == "running" for identifier in ids)
        for index, identifier in enumerate(ids):
            submit(
                bridge,
                request("process.terminate", {"task_id": identifier}, task_id=f"stop-{index}"),
            )
            assert (await bridge.tasks.wait("local", f"stop-{index}", 2))["state"] == "completed"


async def test_read_flood_does_not_take_stop_capacity(bridge, config, terminal_reads, monkeypatch):
    started = 0
    all_read_slots = asyncio.Event()
    release = asyncio.Event()

    async def held_catalog(principal):
        nonlocal started
        started += 1
        if started == config.read_concurrency:
            all_read_slots.set()
        await release.wait()
        return {"sessions": [TARGET]}

    monkeypatch.setattr(bridge.sessions, "catalog", held_catalog)
    config.max_read_queued = config.read_concurrency
    async with bridge:
        normal = request(
            "terminal.execute",
            {
                "argv": [sys.executable, "-c", "import time;time.sleep(60)"],
                "cwd": config.principals["local"].roots[0],
            },
            task_id="normal",
        )
        submit(bridge, normal)
        await wait_running(bridge, [normal.task_id])
        for index in range(config.read_concurrency):
            bridge.prepare("local", request("session.catalog", {}, task_id=f"held-{index}"))
        await asyncio.wait_for(all_read_slots.wait(), 2)
        for index in range(config.max_read_queued):
            bridge.prepare("local", request("session.catalog", {}, task_id=f"queued-{index}"))
        with pytest.raises(BridgeError, match="capacity"):
            bridge.prepare("local", request("session.catalog", {}, task_id="read-overflow"))
        with pytest.raises(BridgeError) as error:
            await bridge.terminal_queries.execute("local", "session.catalog", {})
        assert error.value.code == "terminal_read_busy"
        submit(bridge, request("process.terminate", {"task_id": normal.task_id}, task_id="stop"))
        stopped = await bridge.tasks.wait("local", "stop", 2)
        assert stopped["state"] == "completed" and not release.is_set()
        release.set()
        for index in range(config.read_concurrency):
            assert (await bridge.tasks.wait("local", f"held-{index}", 2))["state"] == "completed"


@pytest.mark.parametrize("level", ["full", "medium", "ask"])
async def test_direct_and_queued_reads_share_capability_and_approval_decision(
    bridge, config, terminal_reads, level
):
    policy = config.principals["local"]
    policy.permission_level = level
    query = ReadQuery(operation="session.catalog")
    if level == "ask":
        with pytest.raises(BridgeError) as error:
            await read_query_async(bridge, "local", query)
        assert error.value.code == "approval_required"
    else:
        assert (await read_query_async(bridge, "local", query))["sessions"] == [TARGET]
    async with bridge:
        value = request("session.catalog", {}, task_id="read-approval")
        pending = bridge.prepare("local", value)
        if level == "ask":
            assert pending["state"] == "created"
            bridge.tasks.approve(value.task_id)
        assert (await bridge.tasks.wait("local", value.task_id, 2))["state"] == "completed"
    policy.capabilities.remove("session.inspect")
    for action in (
        lambda: bridge.prepare("local", request("session.catalog", {}, task_id="forbidden")),
        lambda: bridge.security.authorize("local", "session.catalog"),
    ):
        with pytest.raises(BridgeError) as error:
            action()
        assert error.value.code == "forbidden"
    with pytest.raises(BridgeError) as error:
        await read_query_async(bridge, "local", query)
    assert error.value.code == "forbidden"


async def test_stale_target_and_read_timeout_have_same_code_on_both_routes(
    bridge, config, terminal_reads, monkeypatch
):
    async with bridge:
        wrong = {**TARGET, "expected_pid": 999}
        with pytest.raises(BridgeError) as error:
            await bridge.terminal_queries.execute("local", "session.read", wrong)
        bridge.prepare("local", request("session.read", wrong, task_id="stale"))
        final = await bridge.tasks.wait("local", "stale", 2)
        assert final["state"] == "failed" and final["error"]["code"] == error.value.code
        monkeypatch.setattr("kirabridge.terminal_queries.TERMINAL_QUERY_SECONDS", 0.03)
        cancelled = []

        async def blocked(principal):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

        monkeypatch.setattr(bridge.sessions, "catalog", blocked)
        with pytest.raises(BridgeError) as error:
            await bridge.terminal_queries.execute("local", "session.catalog", {})
        assert error.value.code == "terminal_read_timeout"
        bridge.prepare("local", request("session.catalog", {}, task_id="timeout"))
        final = await bridge.tasks.wait("local", "timeout", 2)
        assert final["state"] == "failed" and final["error"]["code"] == error.value.code
        assert cancelled == [True, True] and bridge.terminal_queries.active == 0
