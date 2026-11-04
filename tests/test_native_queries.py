"""Native reads retain auth/target validation and never create task traffic."""

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_mcp import http_bridge  # noqa: F401

from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.native_queries import NATIVE_READ_OPERATIONS
from kirabridge.read_queries import ReadQueries, read_queries
from kirabridge.read_query import ReadQuery, read_query_async

SAMPLES = {
    "apps.list": {},
    "apps.inspect": {"pid": 222, "expected_started_at": 123.0},
    "windows.list": {},
    "windows.inspect": {"window_id": 42, "expected_pid": 222, "expected_start": "123.000000"},
    "accessibility.status": {},
    "accessibility.inspect": {"pid": 222, "expected_started_at": 123.0},
}


class FixtureTransport:
    """No OS access; pause at the same before-send auth boundary as real transport."""

    def __init__(self):
        self.calls = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.result = {"effect": "none", "fixture": "bounded owned native read"}
        self.timeout = 12

    def snapshot_metadata(self):
        return {"available": True, "revision": "fixture-v1", "keyboard_protocol": 1}

    async def request(self, operation, arguments, *, principal, before_send=None):
        self.entered.set()
        await self.release.wait()
        if before_send is not None:
            before_send()
        self.calls.append((principal, operation, arguments))
        return dict(self.result)

    async def close(self):
        pass


def native(bridge):
    fixture = FixtureTransport()
    bridge.system_modules.transport = fixture
    bridge.macos.capability_probe.facts.update(platform="darwin", os_version="15.7.4")
    for policy in bridge.config.principals.values():
        policy.permission_level = "full"
    return fixture


def query(operation="apps.list", arguments=None, **kwargs):
    return ReadQuery(
        operation="native.read",
        native_operation=operation,
        arguments=SAMPLES[operation] if arguments is None else arguments,
        **kwargs,
    )


def no_tasks(bridge):
    for table in ["tasks", "events", "completion_notices"]:
        assert bridge.store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("operation", sorted(NATIVE_READ_OPERATIONS))
async def test_native_reads_use_original_schema_and_worker_without_task_records(bridge, operation):
    fixture = native(bridge)
    result = await read_query_async(bridge, "local", query(operation))
    assert result == {
        "operation": "native.read",
        "native_operation": operation,
        "read_only": True,
        "result": fixture.result,
    }
    assert fixture.calls[0][:2] == ("local", operation)
    no_tasks(bridge)


@pytest.mark.parametrize(
    "overrides",
    [
        {"native_operation": "apps.launch", "arguments": {"app_path": "/Applications/Notes.app"}},
        {"native_operation": "accessibility.action", "arguments": {}},
        {"native_operation": "capture.window", "arguments": {}},
        {"native_operation": "system.permission_request", "arguments": {}},
        {"native_operation": "native.read", "arguments": {}},
        {"native_operation": "apps.inspect", "arguments": {"pid": 222}},
        {"arguments": {"principal": "other"}},
        {"arguments": {"operation": "apps.quit"}},
        {"path": "/unrelated"},
        {"task_id": "unrelated"},
        {"wait_seconds": 1},
        {
            "native_operation": "accessibility.inspect",
            "arguments": {
                **SAMPLES["accessibility.inspect"],
                "max_depth": 2,
                "max_tree_bytes": 524289,
            },
        },
    ],
)
def test_whitelist_and_inner_schema_are_validated_before_execution(overrides):
    values = {"operation": "native.read", "native_operation": "apps.list", "arguments": {}}
    with pytest.raises(ValidationError):
        ReadQuery.model_validate({**values, **overrides})


async def test_model_roundtrip_and_mixed_batch_preserve_native_queries(bridge, config):
    fixture = native(bridge)
    path = Path(config.principals["local"].roots[0]) / "owned.txt"
    path.write_text("same file")
    request = ReadQueries(queries=[query(), ReadQuery(operation="file.read", path=str(path))])
    result = await read_queries(bridge, "local", request)
    assert result["complete"] and result["read_only"]
    assert result["results"][0]["result"]["result"] == fixture.result
    assert result["results"][1]["result"]["text"] == "same file"
    no_tasks(bridge)


def test_larger_native_budget_preserves_file_and_batch_limits():
    assert query(max_bytes=524288).max_bytes == 524288
    with pytest.raises(ValidationError):
        ReadQuery(operation="file.read", path="/owned", max_bytes=65537)
    with pytest.raises(ValidationError):
        ReadQueries(queries=[query(max_bytes=262144), query(max_bytes=1)])
    with pytest.raises(ValidationError):
        query(max_bytes=524289)


async def test_native_tree_budget_is_capped_and_result_stays_complete_or_explicit(bridge):
    fixture = native(bridge)
    request = query(
        "accessibility.inspect",
        {**SAMPLES["accessibility.inspect"], "max_depth": 16, "max_tree_bytes": 524288},
        max_bytes=262144,
    )
    await read_query_async(bridge, "local", request)
    sent = fixture.calls[0][2]
    assert sent["max_tree_bytes"] == 262144 - 8192
    assert sent["max_depth"] == 16
    no_tasks(bridge)


async def test_invalid_later_native_read_prevents_entire_batch(bridge):
    fixture = native(bridge)
    with pytest.raises(ValidationError):
        ReadQueries(
            queries=[
                query(),
                {"operation": "native.read", "native_operation": "apps.quit", "arguments": {}},
            ]
        )
    assert not fixture.calls
    no_tasks(bridge)


@pytest.mark.parametrize("late_change", ["manual", "revoke"])
async def test_policy_is_rechecked_after_transport_wait_before_sending(bridge, late_change):
    fixture = native(bridge)
    fixture.release.clear()
    task = asyncio.create_task(read_query_async(bridge, "local", query()))
    await fixture.entered.wait()
    policy = bridge.config.principals["local"]
    if late_change == "manual":
        policy.permission_level = "ask"
    else:
        policy.capabilities.remove("apps.list")
    fixture.release.set()
    with pytest.raises(BridgeError) as caught:
        await task
    assert caught.value.code == ("approval_required" if late_change == "manual" else "forbidden")
    assert not fixture.calls and bridge.native_queries.active == 0
    no_tasks(bridge)


async def test_manual_approval_denied_before_worker_or_slot(bridge):
    fixture = native(bridge)
    bridge.config.principals["local"].permission_level = "ask"
    with pytest.raises(BridgeError) as caught:
        await read_query_async(bridge, "local", query())
    assert caught.value.code == "approval_required" and not fixture.entered.is_set()
    assert bridge.native_queries.active == 0
    no_tasks(bridge)


async def test_read_slot_saturation_and_cancel_are_bounded_without_replay(bridge):
    fixture = native(bridge)
    fixture.release.clear()
    bridge.native_queries.slots = 1
    task = asyncio.create_task(read_query_async(bridge, "local", query()))
    await fixture.entered.wait()
    with pytest.raises(BridgeError) as caught:
        await read_query_async(bridge, "local", query())
    assert caught.value.code == "native_read_busy"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert bridge.native_queries.active == 0 and not fixture.calls
    no_tasks(bridge)


async def test_timeout_includes_transport_wait_and_releases_slot(bridge, monkeypatch):
    import kirabridge.native_queries as module

    fixture = native(bridge)
    fixture.release.clear()
    monkeypatch.setattr(module, "NATIVE_READ_SECONDS", 0.01)
    with pytest.raises(BridgeError) as caught:
        await read_query_async(bridge, "local", query())
    assert caught.value.code == "native_read_timeout"
    assert bridge.native_queries.active == 0 and not fixture.calls
    no_tasks(bridge)


async def test_oversized_read_is_explicit_and_does_not_create_task(bridge):
    fixture = native(bridge)
    fixture.result["fixture"] = "ä" * 100
    with pytest.raises(BridgeError) as caught:
        await read_query_async(bridge, "local", query(max_bytes=100))
    assert caught.value.code == "native_read_result_limit" and len(fixture.calls) == 1
    no_tasks(bridge)


@pytest.mark.parametrize("host_platform", ["linux", "win32"])
async def test_native_capability_unavailable_never_dispatches(bridge, host_platform):
    fixture = native(bridge)
    bridge.macos.capability_probe.facts.update(platform=host_platform)
    with pytest.raises(BridgeError) as caught:
        await read_query_async(bridge, "local", query())
    assert caught.value.code == "macos_capability_unavailable" and not fixture.calls


async def test_cached_native_read_and_both_batches_through_real_http(http_bridge):  # noqa: F811
    bridge, endpoint = http_bridge
    fixture = native(bridge)
    request = query().model_dump(exclude_unset=True)
    async with MCPClientPool() as pool:
        await pool.connect(Peer("caller", url=endpoint, token="local-test-" + "a" * 40))
        single = (await pool.call("caller", "read_query", {"query": request})).structuredContent
        batch = (
            await pool.call(
                "caller", "read_query", {"query": {"operation": "read.batch", "queries": [request]}}
            )
        ).structuredContent
        mixed = (
            await pool.call(
                "caller",
                "read_query",
                {
                    "query": {
                        "operation": "tool.batch",
                        "calls": [{"tool": "read_query", "arguments": {"query": request}}],
                        "result_format": "structured",
                    }
                },
            )
        ).structuredContent
        assert single["result"] == fixture.result
        assert batch["complete"] and batch["results"][0]["result"] == single
        assert mixed["complete"] and mixed["all_succeeded"]
        assert mixed["results"][0]["result"]["structuredContent"] == single
        invalid_later = (
            await pool.call(
                "caller",
                "read_query",
                {
                    "query": {
                        "operation": "tool.batch",
                        "calls": [
                            {"tool": "read_query", "arguments": {"query": request}},
                            {
                                "tool": "read_query",
                                "arguments": {
                                    "query": {
                                        "operation": "native.read",
                                        "native_operation": "apps.quit",
                                        "arguments": SAMPLES["apps.inspect"],
                                    }
                                },
                            },
                        ],
                    }
                },
            )
        ).structuredContent
        assert invalid_later["error"]["code"] == "invalid_arguments"
        assert len(fixture.calls) == 3  # The first read in an invalid batch never ran.
        bridge.config.principals["local"].permission_level = "ask"
        denied = (await pool.call("caller", "read_query", {"query": request})).structuredContent
        assert denied["error"]["code"] == "approval_required"
    assert len(fixture.calls) == 3
    no_tasks(bridge)
