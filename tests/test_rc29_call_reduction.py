from pathlib import Path

import pytest
from conftest import request
from pydantic import ValidationError
from test_mcp import http_bridge  # noqa: F401

from kirabridge.bridge_core.models import WriteInput
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.read_query import ReadQuery


async def test_selected_catalog_never_builds_unrequested_schemas(http_bridge, monkeypatch):  # noqa: F811
    _bridge, endpoint = http_bridge

    def unrequested(*args, **kwargs):
        raise AssertionError("Unrequested write schema must not be built")

    monkeypatch.setattr(WriteInput, "model_json_schema", unrequested)
    async with MCPClientPool() as pool:
        await pool.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        result = (
            await pool.call("local", "operation_catalog", {"operations": ["file.read"]})
        ).structuredContent
    assert set(result["operations"]) == {"file.read"}
    assert result["operations"]["file.read"]["arguments"]["properties"]["path"]
    assert result["selection"]["returned"] == ["file.read"]


async def test_catalog_selection_preserves_authorization_and_rejects_bad_names(http_bridge):  # noqa: F811
    bridge, endpoint = http_bridge
    bridge.config.principals["local"].capabilities.remove("file.write")
    async with MCPClientPool() as pool:
        await pool.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        result = (
            await pool.call(
                "local", "operation_catalog", {"operations": ["file.read", "file.write"]}
            )
        ).structuredContent
        assert "file.read" in result["operations"] and "file.write" not in result["operations"]
        for operations in [[], ["file.read"] * 2, ["unknown.operation"], ["file.read"] * 33]:
            result = (
                await pool.call("local", "operation_catalog", {"operations": operations})
            ).structuredContent
            assert result["error"]["code"] == "invalid_arguments"


async def test_cached_task_observation_combines_state_events_and_file_read(http_bridge):  # noqa: F811
    bridge, endpoint = http_bridge
    root = Path(bridge.config.principals["local"].roots[0])
    path = root / "observed.txt"
    path.write_text("one result")
    task = request("file.read", {"path": str(path)}, task_id="observation-contract")
    bridge.prepare("local", task)
    async with MCPClientPool() as pool:
        await pool.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        queries = [
            {"operation": "task.observe", "task_id": task.task_id, "wait_seconds": 18},
            {"operation": "file.read", "path": str(path)},
        ]
        result = (
            await pool.call(
                "local", "read_query", {"query": {"operation": "read.batch", "queries": queries}}
            )
        ).structuredContent
    observed = result["results"][0]["result"]
    assert observed["task"]["id"] == task.task_id
    assert observed["approval_required"] and observed["state"] == "created"
    assert observed["events"]["events"] and not observed["pending"]
    assert result["complete"] and result["results"][1]["result"]["text"] == "one result"
    assert bridge.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


@pytest.mark.parametrize(
    "query",
    [
        {"operation": "task.observe", "task_id": "one", "wait_seconds": float("nan")},
        {"operation": "task.observe", "task_id": "one", "wait_seconds": 19},
        {"operation": "task.observe", "task_id": "one", "events_after": True},
        {"operation": "task.observe", "task_id": "one", "path": "/no"},
        {"operation": "task.observe"},
        {"operation": "platform.status", "wait_seconds": 1},
        {"operation": "file.read", "path": "/no", "events_after": 1},
    ],
)
def test_observation_selectors_are_bounded_and_only_valid_for_task_observation(query):
    with pytest.raises(ValidationError):
        ReadQuery.model_validate(query)
