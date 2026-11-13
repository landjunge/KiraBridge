import asyncio
import json

import pytest
from conftest import request
from test_mcp import http_bridge  # noqa: F401

from kirabridge.bridge_core.models import BridgeError, State
from kirabridge.grok_connector.conversation import result_for_conversation
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.server import inline_task_timeout
from kirabridge.task_observation import observe_submitted_task, observe_task


def pending(bridge, config, *, task_id="observed", manual=False):
    config.principals["local"].approval_mode = "manual" if manual else "automatic"
    value = request(
        "file.write",
        {"path": str(config.principals["local"].roots[0]) + "/owned", "text": "owned"},
        task_id=task_id,
    )
    bridge.prepare("local", value)
    return value


def running(bridge, config):
    value = pending(bridge, config)
    bridge.store.claim_exact("observation-test", 30, value.task_id)
    bridge.store.transition(
        value.task_id, State.RUNNING, {"test": "observed"}, owner="observation-test"
    )
    return value


def finish(bridge, task_id):
    bridge.store.transition(
        task_id,
        State.COMPLETED,
        {"observed": True},
        result={"text": "finished once"},
        owner="observation-test",
    )


@pytest.mark.parametrize("wait", [-1, 18.01, True, "1", float("nan"), float("inf")])
async def test_observation_rejects_invalid_wait_without_task_access(bridge, wait):
    with pytest.raises(BridgeError, match="observation"):
        await observe_task(bridge, "local", "absent", wait_seconds=wait)


@pytest.mark.parametrize("after", [-1, True, 1.5, 2**63])
async def test_observation_rejects_invalid_event_cursor(bridge, after):
    with pytest.raises(BridgeError, match="observation"):
        await observe_task(bridge, "local", "absent", after=after)


async def test_task_owner_and_read_permission_checked_before_wait(bridge, config):
    value = pending(bridge, config)
    for principal, task_id in [("other", value.task_id), ("local", "absent")]:
        with pytest.raises(BridgeError, match="not found"):
            await observe_task(bridge, principal, task_id, wait_seconds=18)
    config.principals["local"].capabilities.remove("task.read")
    with pytest.raises(BridgeError, match="Capability"):
        await observe_task(bridge, "local", value.task_id, wait_seconds=18)


async def test_permission_revocation_during_wait_prevents_task_and_event_return(bridge, config):
    value = running(bridge, config)
    observer = asyncio.create_task(observe_task(bridge, "local", value.task_id, wait_seconds=1))
    await asyncio.sleep(0.01)
    config.principals["local"].capabilities.remove("task.read")
    with pytest.raises(BridgeError, match="Capability"):
        await observer
    assert bridge.store.get(value.task_id)["state"] == "running"


@pytest.mark.parametrize("state", [State.COMPLETED, State.UNKNOWN, State.BLOCKED])
async def test_terminal_unknown_and_approval_return_without_wait(
    bridge, config, monkeypatch, state
):
    value = running(bridge, config)
    if state == State.BLOCKED:
        value = pending(bridge, config, task_id="blocked")
        bridge.store.transition(value.task_id, state, {"test": "blocked"})
    else:
        bridge.store.transition(
            value.task_id, state, {"test": "terminal"}, owner="observation-test"
        )

    async def forbidden_sleep(_seconds):
        raise AssertionError("terminal or approval state must return immediately")

    monkeypatch.setattr("kirabridge.task_observation.asyncio.sleep", forbidden_sleep)
    result = await observe_task(bridge, "local", value.task_id, wait_seconds=18)
    assert result["state"] == state and result["complete"] and not result["pending"]
    assert result["execution_outcome_unknown"] is (state == State.UNKNOWN)
    assert not result["timed_out"]
    manual = pending(bridge, config, task_id="approval", manual=True)
    result = await observe_task(bridge, "local", manual.task_id, wait_seconds=18)
    assert result["state"] == "created" and result["approval_required"]
    assert not result["complete"] and not result["pending"] and not result["timed_out"]


async def test_pending_wait_has_fresh_redacted_snapshot_and_does_not_resubmit(bridge, config):
    value = running(bridge, config)
    before = bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0]
    result = await observe_task(bridge, "local", value.task_id, wait_seconds=0.01)
    assert result["state"] == "running" and result["pending"] and result["timed_out"]
    assert not {"lease_owner", "lease_until", "idem"} & result["task"].keys()
    assert not result["complete"]
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == before


async def test_wait_resolves_output_once_at_return_instead_of_every_state_poll(
    bridge, config, monkeypatch
):
    value = running(bridge, config)
    reads = []
    original = bridge.store.get

    def counted(*args, **kwargs):
        reads.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(bridge.store, "get", counted)
    result = await observe_task(bridge, "local", value.task_id, wait_seconds=0.16)
    assert result["pending"]
    # Rights/owner/state polling never resolves full output; the final snapshot does once.
    assert reads == [value.task_id]


async def test_wait_returns_completion_and_events_with_page_cursor(bridge, config):
    value = running(bridge, config)
    first = await observe_task(bridge, "local", value.task_id)

    async def completion():
        await asyncio.sleep(0.02)
        finish(bridge, value.task_id)

    writer = asyncio.create_task(completion())
    result = await observe_task(
        bridge, "local", value.task_id, wait_seconds=1, after=first["next_after"]
    )
    await writer
    assert result["complete"] and not result["pending"] and not result["timed_out"]
    assert result["task"]["result"]["text"] == "finished once"
    assert [event["state"] for event in result["events"]["events"]] == ["completed"]
    assert result["next_after"] > first["next_after"] and not result["has_more_events"]
    empty = await observe_task(bridge, "local", value.task_id, after=result["next_after"])
    assert empty["events"] == {"events": []} and empty["next_after"] == result["next_after"]


async def test_event_paging_preserves_more_than_one_thousand_existing_events(bridge, config):
    value = running(bridge, config)
    initial = await observe_task(bridge, "local", value.task_id)
    with bridge.store.transaction():
        bridge.store.db.executemany(
            "INSERT INTO events(task_id,at,state,evidence) VALUES(?,1,'running',?)",
            [(value.task_id, json.dumps({"index": index})) for index in range(1001)],
        )
    first = await observe_task(bridge, "local", value.task_id, after=initial["next_after"])
    assert len(first["events"]["events"]) == 1000 and first["has_more_events"]
    second = await observe_task(bridge, "local", value.task_id, after=first["next_after"])
    assert len(second["events"]["events"]) == 1 and not second["has_more_events"]
    assert second["events"]["events"][0]["evidence"]["index"] == 1000


async def test_observer_cancellation_leaves_original_worker_running_once(bridge, config):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def executor(task, started, progress):
        calls.append(task["id"])
        await started({"test": True})
        entered.set()
        await release.wait()
        return {"text": "finished once"}

    bridge.tasks.executor = executor
    async with bridge:
        value = pending(bridge, config)
        await entered.wait()
        observer = asyncio.create_task(observe_task(bridge, "local", value.task_id, 18))
        await asyncio.sleep(0)
        observer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await observer
        assert bridge.store.get(value.task_id)["state"] == "running"
        release.set()
        completed = await bridge.tasks.wait("local", value.task_id, 2)
        assert completed["state"] == "completed" and calls == [value.task_id]


async def test_submit_observation_shares_native_and_inline_budget_without_cancelling_attempt(
    bridge, config, monkeypatch
):
    value = running(bridge, config)
    release, completed = asyncio.Event(), asyncio.Event()

    async def attempt():
        await release.wait()
        finish(bridge, value.task_id)
        completed.set()

    native = asyncio.create_task(attempt())

    async def wait_delivery(_task_id):
        await asyncio.shield(completed.wait())
        return bridge.store.get(value.task_id)

    monkeypatch.setattr(bridge.tasks, "wait_delivery", wait_delivery)
    monkeypatch.setattr(bridge.tasks.native, "native", lambda _task: True)
    deadline = asyncio.get_running_loop().time() + 0.02
    result = await observe_submitted_task(
        bridge, "local", bridge.store.get(value.task_id), wait_seconds=13, deadline=deadline
    )
    assert result["state"] == "running" and not native.done()
    assert not {"lease_owner", "lease_until", "idem"} & result.keys()
    release.set()
    await native
    assert bridge.store.get(value.task_id)["state"] == "completed"


@pytest.mark.parametrize("tool", ["task_request", "action_request", "task_submit", "action_submit"])
async def test_all_submit_aliases_finish_fast_general_operation_in_one_http_call(
    http_bridge,  # noqa: F811
    config,
    tool,  # noqa: F811
):
    bridge, endpoint = http_bridge
    calls = []

    async def executor(task, started, progress):
        calls.append(task["id"])
        await started({"test": True})
        await asyncio.sleep(0.02)
        return {"text": "fast general result"}

    bridge.tasks.executor = executor
    config.principals["local"].approval_mode = "automatic"
    value = request(
        "file.write",
        {"path": config.principals["local"].roots[0] + "/result", "text": "test"},
    )
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        result = (
            await clients.call("local", tool, {"request": value.model_dump()})
        ).structuredContent
    assert result["state"] == "completed" and result["result"]["text"] == "fast general result"
    assert not {"lease_owner", "lease_until", "idem"} & result.keys()
    assert calls == [value.task_id]


@pytest.mark.parametrize("tool", ["task_request", "action_request", "task_submit", "action_submit"])
async def test_write_only_submit_is_refused_before_task_creation_or_execution(
    http_bridge,  # noqa: F811
    config,
    tool,
):
    bridge, endpoint = http_bridge
    config.principals["local"].approval_mode = "automatic"
    config.principals["local"].capabilities.remove("task.read")
    value = request(
        "file.write",
        {"path": config.principals["local"].roots[0] + "/result", "text": "test"},
    )
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        result = (
            await clients.call("local", tool, {"request": value.model_dump()})
        ).structuredContent
    assert result["error"]["code"] == "forbidden"
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


async def test_post_submission_revocation_keeps_original_id_without_replay(
    http_bridge,  # noqa: F811
    config,
):
    bridge, endpoint = http_bridge
    config.principals["local"].approval_mode = "automatic"
    calls = []
    release = asyncio.Event()

    async def executor(task, started, progress):
        calls.append(task["id"])
        await started({"test": True})
        config.principals["local"].capabilities.remove("task.read")
        await release.wait()
        return {"text": "finished once"}

    bridge.tasks.executor = executor
    value = request(
        "file.write",
        {"path": config.principals["local"].roots[0] + "/result", "text": "test"},
    )
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        result = (
            await clients.call("local", "task_request", {"request": value.model_dump()})
        ).structuredContent
    assert result["error"]["code"] == "forbidden" and result["id"] == value.task_id
    assert result["observation_failed"] and result["automatic_retry"] is False
    assert bridge.store.get(value.task_id)["state"] == "running"
    release.set()
    assert (await bridge.tasks.wait("local", value.task_id, 2))["state"] == "completed"
    assert calls == [value.task_id]


async def test_chatgpt_cached_task_get_waits_but_other_identity_returns_pending(
    http_bridge,  # noqa: F811
    config,
    monkeypatch,  # noqa: F811
):
    bridge, endpoint = http_bridge
    monkeypatch.setenv("CHATGPT_OBSERVE_TEST_TOKEN", "chatgpt-observe-" + "x" * 40)
    config.principals["chatgpt"] = config.principals["local"].model_copy(deep=True)
    config.principals["chatgpt"].token_env = "CHATGPT_OBSERVE_TEST_TOKEN"
    config.principals["chatgpt"].approval_mode = "automatic"
    entered, release = asyncio.Event(), asyncio.Event()

    async def executor(task, started, progress):
        await started({"test": True})
        entered.set()
        await release.wait()
        return {"text": "same task"}

    bridge.tasks.executor = executor
    value = request(
        "file.write", {"path": config.principals["local"].roots[0] + "/result", "text": "test"}
    )
    bridge.prepare("chatgpt", value)
    await entered.wait()
    config.principals["local"].approval_mode = "automatic"
    other_value = request("file.write", value.arguments, task_id="local-still-running")
    bridge.prepare("local", other_value)
    async with MCPClientPool() as clients:
        await clients.connect(Peer("chatgpt", url=endpoint, token="chatgpt-observe-" + "x" * 40))
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        immediate = (
            await clients.call("local", "task_get", {"task_id": other_value.task_id})
        ).structuredContent
        assert immediate["state"] in {"queued", "accepted", "running"}
        waiting = asyncio.create_task(
            clients.call("chatgpt", "task_get", {"task_id": value.task_id})
        )
        await asyncio.sleep(0.03)
        assert not waiting.done()
        release.set()
        result = (await waiting).structuredContent
    assert result["state"] == "completed" and result["result"]["text"] == "same task"


async def test_grok_zero_remaining_budget_still_returns_pending_conversation(bridge, config):
    value = running(bridge, config)
    config.grok_connector.enabled = True
    config.grok_connector.principal = "local"
    result = await result_for_conversation(
        bridge, "local", bridge.task("local", value.task_id), wait_seconds=0
    )
    assert result["state"] == "running"
    assert result["conversation_return"]["continue_required"]
    assert not result["conversation_return"]["final"]
    assert result["conversation_return"]["next_call"]["arguments"]["task_id"] == value.task_id


async def test_grok_submit_native_and_conversation_wait_share_one_response_budget(
    http_bridge,  # noqa: F811
    config,
    monkeypatch,
):
    bridge, endpoint = http_bridge
    config.principals["local"].approval_mode = "automatic"
    config.grok_connector.enabled = True
    config.grok_connector.principal = "local"
    monkeypatch.setattr("kirabridge.task_observation.MAX_WAIT_SECONDS", 0.06)
    release = asyncio.Event()
    calls = []

    async def executor(task, started, progress):
        calls.append(task["id"])
        await started({"test": True})
        await release.wait()
        return {"text": "after observation"}

    async def native_wait(task_id):
        await asyncio.sleep(0.04)
        return bridge.store.get(task_id)

    bridge.tasks.executor = executor
    monkeypatch.setattr(bridge.tasks, "wait_delivery", native_wait)
    monkeypatch.setattr(bridge.tasks.native, "native", lambda _task: True)
    value = request(
        "file.write",
        {"path": config.principals["local"].roots[0] + "/result", "text": "test"},
    )
    try:
        async with MCPClientPool() as clients:
            await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
            # Generous hang guard: the shared response budget under test is the
            # 60ms MAX_WAIT_SECONDS above, not this outer deadline. A tight 0.25s
            # guard raced the MCP round-trip plus the 40ms native wait under host
            # load and timed out spuriously.
            async with asyncio.timeout(2.0):
                result = (
                    await clients.call("local", "task_request", {"request": value.model_dump()})
                ).structuredContent
        assert result["state"] == "running"
        assert result["conversation_return"]["continue_required"]
        assert not result["conversation_return"]["final"]
        assert calls == [value.task_id]
    finally:
        release.set()
    assert (await bridge.tasks.wait("local", value.task_id, 2))["state"] == "completed"


def test_inline_grace_covers_general_operations_and_respects_desktop_and_long_work():
    assert inline_task_timeout("file.write") == 2
    assert inline_task_timeout("apps.list") == 2
    assert inline_task_timeout("keyboard.control") == 13
    assert inline_task_timeout("keyboard.sequence") == 13
    assert inline_task_timeout("apps.launch") == 13
    assert inline_task_timeout("session.read") == 9
    assert inline_task_timeout("agent.execute") == 1
    assert inline_task_timeout("terminal.execute") == 1
