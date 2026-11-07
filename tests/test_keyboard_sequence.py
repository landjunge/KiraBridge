"""Physical key ordering, partial outcomes and durable single-RPC admission."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from test_keyboard_control import setup
from test_mcp import http_bridge  # noqa: F401 -- real authenticated HTTP fixture

from kirabridge.bridge_core.models import BridgeError, TaskRequest, UncertainExecution
from kirabridge.keyboard_sequence import KeyboardSequenceInput
from kirabridge.mcp_gateway.client import MCPClientPool, Peer


def steps(text="Stern am"):
    return [
        {
            "key": {"named": "space"} if c == " " else {"character": c.lower()},
            "modifiers": ["shift"] if c.isupper() else [],
        }
        for c in text
    ]


async def execute(bridge, value=None, *, task_id="sequence", progress=None):
    return await bridge.execute(
        {
            "id": task_id,
            "principal": "local",
            "operation": "keyboard.sequence",
            "args": value or {"app": "Editor", "steps": steps()},
        },
        AsyncMock(),
        progress or AsyncMock(),
    )


async def test_sequence_posts_eight_real_key_pairs_with_fresh_targets(bridge, config):
    calls, _, _ = setup(bridge, config)
    progress = AsyncMock()
    result = await execute(bridge, progress=progress)
    assert result["requested_steps"] == result["completed_steps"] == 8
    assert result["post_calls_returned"] == 16
    assert result["physical_key_events"] and not result["app_processing_confirmed"]
    assert result["automatic_retry"] is False
    assert [op for op, _ in calls] == ["apps.list"] + [
        op
        for index in range(8)
        for op in (
            "keyboard.inspect",
            "keyboard.chord" if index == 0 else "keyboard.key",
        )
    ]
    assert not any(op.startswith("keyboard.text") for op, _ in calls)
    assert [s["index"] for s in result["steps"]] == list(range(8))
    assert len({s["step_id"] for s in result["steps"]}) == 8
    assert not bridge.sessions.lock.locked()
    completions = [
        c.args[0]
        for c in progress.await_args_list
        if c.args[0]["evidence_type"] == "keyboard_sequence_step_completed"
    ]
    assert [x["completed_steps"] for x in completions] == list(range(1, 9))


async def test_partial_unknown_stops_before_remaining_keys_and_records_completed_prefix(
    bridge,
    config,
):
    calls, _, native = setup(bridge, config)
    count = 0

    async def uncertain(operation, arguments, **kwargs):
        nonlocal count
        result = await native(operation, arguments, **kwargs)
        if operation in {"keyboard.key", "keyboard.chord"}:
            count += 1
            if count == 3:
                raise UncertainExecution("test_pair_unknown", "Uncertain pair; never replay")
        return result

    bridge.keyboard.transport.request.side_effect = uncertain
    with pytest.raises(UncertainExecution) as observed:
        await execute(bridge)
    assert count == 3 and len(calls) == 7
    assert observed.value.provider_error == {
        "step_index": 2,
        "completed_steps": 2,
        "requested_steps": 8,
        "cause_code": "test_pair_unknown",
        "automatic_retry": False,
    }
    assert not bridge.sessions.lock.locked()


@pytest.mark.parametrize("change", ["foreground", "generation", "permission"])
async def test_sequence_does_not_refocus_or_follow_replaced_target(bridge, config, change):
    calls, app, native = setup(bridge, config)
    count = 0

    async def changed(operation, arguments, **kwargs):
        nonlocal count
        result = await native(operation, arguments, **kwargs)
        if operation in {"keyboard.key", "keyboard.chord"}:
            count += 1
            if change == "foreground":
                app["active"] = False
            elif change == "generation":
                app["started_at"] += 1
            else:
                config.principals["local"].capabilities.remove("keyboard.execute")
        return result

    bridge.keyboard.transport.request.side_effect = changed
    with pytest.raises(UncertainExecution) as observed:
        await execute(bridge)
    assert count == 1 and observed.value.provider_error["completed_steps"] == 1
    assert not any(op == "app.focus" for op, _ in calls)


@pytest.mark.parametrize(
    "change", ["target-pid", "target-start", "bundle_id", "app_path", "executable", "closed"]
)
async def test_sequence_fresh_inspection_rejects_replaced_or_closed_application(
    bridge, config, change
):
    calls, _, native = setup(bridge, config)
    inspections = 0

    async def altered(operation, arguments, **kwargs):
        nonlocal inspections
        result = await native(operation, arguments, **kwargs)
        if operation == "keyboard.inspect":
            inspections += 1
            if inspections == 2:
                if change == "closed":
                    raise BridgeError("macos_target_changed", "Selected process exited")
                if change.startswith("target-"):
                    field = "pid" if change == "target-pid" else "expected_started_at"
                    result["target"][field] += 1
                else:
                    result["application"][change] += ".replacement"
        return result

    bridge.keyboard.transport.request.side_effect = altered
    with pytest.raises(UncertainExecution) as observed:
        await execute(bridge)
    assert observed.value.provider_error["completed_steps"] == 1
    assert sum(op == "apps.list" for op, _ in calls) == 1
    assert sum(op == "keyboard.inspect" for op, _ in calls) == 2
    assert sum(op in {"keyboard.key", "keyboard.chord"} for op, _ in calls) == 1
    assert not any(op == "app.focus" for op, _ in calls)


async def test_sequence_rechecks_permission_after_each_fresh_inspection(bridge, config):
    calls, _, native = setup(bridge, config)
    inspections = 0

    async def revoked(operation, arguments, **kwargs):
        nonlocal inspections
        result = await native(operation, arguments, **kwargs)
        if operation == "keyboard.inspect":
            inspections += 1
            if inspections == 2:
                config.principals["local"].capabilities.remove("keyboard.execute")
        return result

    bridge.keyboard.transport.request.side_effect = revoked
    with pytest.raises(UncertainExecution) as observed:
        await execute(bridge)
    assert observed.value.provider_error["completed_steps"] == 1
    assert inspections == 2
    assert sum(op in {"keyboard.key", "keyboard.chord"} for op, _ in calls) == 1


async def test_whole_sequence_owns_desktop_lock_without_interleaving(bridge, config):
    calls, _, native = setup(bridge, config)

    async def slow(operation, arguments, **kwargs):
        result = await native(operation, arguments, **kwargs)
        if operation == "keyboard.key":
            await asyncio.sleep(0.001)
        return result

    bridge.keyboard.transport.request.side_effect = slow
    await asyncio.gather(
        execute(bridge, {"steps": steps("ab")}, task_id="first"),
        execute(bridge, {"steps": steps("cd")}, task_id="second"),
    )
    keys = [args["key"]["character"] for op, args in calls if op == "keyboard.key"]
    assert keys in [list("abcd"), list("cdab")]


@pytest.mark.parametrize(
    "value",
    [
        {"steps": []},
        {"steps": steps("a") * 33},
        {"steps": [{"key": {"character": "a"}, "repeat": 20}] * 2},
        {"steps": [{"text": "Stern am"}]},
        {"steps": [{"key": {"character": "a"}, "repeat": True}]},
        {"steps": [{"key": {"character": "a"}, "modifiers": ["shift", "shift"]}]},
        {"steps": steps("a"), "text": "wrong path"},
        {"steps": steps("a"), "scope": "system"},
        {"steps": steps("a"), "submit": True},
        {"steps": steps("a"), "app": "Editor", "pid": 1, "expected_started_at": 1.0},
        {"steps": steps("a"), "pid": 1},
    ],
)
def test_sequence_rejects_text_system_unbounded_or_ambiguous_intents(value):
    with pytest.raises(ValidationError):
        KeyboardSequenceInput.model_validate(value)


async def test_sequence_mcp_admits_one_durable_task_and_duplicate_posts_nothing(
    http_bridge,  # noqa: F811 -- imported HTTP fixture
    config,
    monkeypatch,
):
    bridge, endpoint = http_bridge
    calls, _, _ = setup(bridge, config)
    config.principals["local"].approval_mode = "automatic"
    monkeypatch.setattr(bridge.tasks, "preflight", None)
    value = {
        "request": {"app": "Editor", "steps": steps()},
        "task_id": "http-sequence",
        "idempotency_key": "http-sequence",
    }
    async with MCPClientPool() as pool:
        await pool.connect(Peer("caller", url=endpoint, token="local-test-" + "a" * 40))
        catalog = {t.name: t for t in await pool.list_tools("caller")}
        assert "keyboard_sequence" in catalog
        first = (await pool.call("caller", "keyboard_sequence", value)).structuredContent
        assert first["state"] == "completed" and first["result"]["completed_steps"] == 8
        duplicate = (await pool.call("caller", "keyboard_sequence", value)).structuredContent
        assert duplicate["state"] == "completed" and duplicate["id"] == first["id"]
    assert sum(op in {"keyboard.key", "keyboard.chord"} for op, _ in calls) == 8
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1


async def test_legacy_catalog_action_request_runs_one_idempotent_physical_sequence(
    http_bridge,  # noqa: F811
    config,
    monkeypatch,
):
    bridge, endpoint = http_bridge
    calls, _, _ = setup(bridge, config)
    config.principals["local"].approval_mode = "automatic"
    monkeypatch.setattr(bridge.tasks, "preflight", None)
    request = TaskRequest(
        task_id="legacy-apps-sequence",
        idempotency_key="legacy-apps-sequence",
        operation="keyboard.sequence",
        arguments={"app": "Editor", "steps": steps()},
    )
    async with MCPClientPool() as pool:
        await pool.connect(Peer("caller", url=endpoint, token="local-test-" + "a" * 40))
        # An old Apps snapshot exposes the generic action tool but no dedicated
        # sequence tool. The unchanged generic request schema carries its intent.
        legacy_catalog = {
            tool.name: tool
            for tool in await pool.list_tools("caller")
            if tool.name == "action_request"
        }
        assert "keyboard_sequence" not in legacy_catalog
        assert legacy_catalog["action_request"].inputSchema["required"] == ["request"]

        async def legacy_call():
            assert "action_request" in legacy_catalog
            return (
                await pool.call("caller", "action_request", {"request": request.model_dump()})
            ).structuredContent

        first = await legacy_call()
        assert first["state"] == "completed" and first["result"]["completed_steps"] == 8
        before_duplicate = list(calls)
        duplicate = await legacy_call()
        assert duplicate["id"] == first["id"] and duplicate["state"] == "completed"
        assert calls == before_duplicate
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
    assert sum(op == "apps.list" for op, _ in calls) == 1
    assert sum(op == "keyboard.inspect" for op, _ in calls) == 8
    assert sum(op in {"keyboard.key", "keyboard.chord"} for op, _ in calls) == 8
    assert not any(op.startswith("keyboard.text") for op, _ in calls)


async def test_partial_http_sequence_is_not_replayed_by_same_request(
    http_bridge,  # noqa: F811
    config,
    monkeypatch,
):
    bridge, endpoint = http_bridge
    _, _, native = setup(bridge, config)
    config.principals["local"].approval_mode = "automatic"
    monkeypatch.setattr(bridge.tasks, "preflight", None)
    count = 0

    async def uncertain(operation, arguments, **kwargs):
        nonlocal count
        result = await native(operation, arguments, **kwargs)
        if operation in {"keyboard.key", "keyboard.chord"}:
            count += 1
            if count == 2:
                raise UncertainExecution("test_pair_unknown", "Unknown output")
        return result

    bridge.keyboard.transport.request.side_effect = uncertain
    value = {"request": {"steps": steps()}, "task_id": "partial", "idempotency_key": "partial"}
    async with MCPClientPool() as pool:
        await pool.connect(Peer("caller", url=endpoint, token="local-test-" + "a" * 40))
        result = (await pool.call("caller", "keyboard_sequence", value)).structuredContent
        assert result["state"] == "unknown"
        assert result["evidence"]["provider_error"]["completed_steps"] == 1
        duplicate = (await pool.call("caller", "keyboard_sequence", value)).structuredContent
        assert duplicate["state"] == "unknown" and count == 2
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1


async def test_sequence_deadline_stops_remaining_events_without_retry(bridge, config):
    calls, _, native = setup(bridge, config)
    bridge.desktop_input.timeout = 0.02

    async def stalled(operation, arguments, **kwargs):
        result = await native(operation, arguments, **kwargs)
        if operation in {"keyboard.key", "keyboard.chord"}:
            await asyncio.sleep(1)
        return result

    bridge.keyboard.transport.request.side_effect = stalled
    with pytest.raises(UncertainExecution) as error:
        await execute(bridge)
    assert error.value.code == "desktop_input_unknown"
    assert sum(op in {"keyboard.key", "keyboard.chord"} for op, _ in calls) == 1
    assert not bridge.sessions.lock.locked()


async def test_completed_sequence_receipt_survives_bridge_restart(bridge, config):
    from kirabridge.bridge_core.bridge import Bridge
    from kirabridge.bridge_core.models import TaskRequest

    calls, _, _ = setup(bridge, config)
    config.principals["local"].approval_mode = "automatic"
    bridge.tasks.preflight = None
    request = TaskRequest(
        task_id="restart-sequence",
        idempotency_key="restart-sequence",
        operation="keyboard.sequence",
        arguments={"steps": steps()},
    )
    async with bridge:
        bridge.prepare("local", request)
        finished = await bridge.tasks.wait("local", request.task_id, timeout=3)
        assert finished["state"] == "completed"
    assert sum(op in {"keyboard.key", "keyboard.chord"} for op, _ in calls) == 8
    reopened = Bridge(config)
    try:
        # No workers/transport need to start to reconcile a completed request.
        repeated = reopened.prepare("local", request)
        assert repeated["state"] == "completed"
        assert repeated["result"]["completed_steps"] == 8
        assert reopened.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
    finally:
        reopened.store.close()
