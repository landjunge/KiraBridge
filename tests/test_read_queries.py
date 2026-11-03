from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from test_mcp import http_bridge  # noqa: F401

from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.read_queries import ReadQueries, read_queries


@pytest.mark.parametrize(
    "queries",
    [
        [],
        [{}] * 9,
        [{"operation": "file.write", "path": "/no", "text": "no"}],
        [{"operation": "platform.status", "max_bytes": 65536}] * 5,
        [{"operation": "file.list", "path": "/no", "limit": 101}],
    ],
)
def test_batch_validates_whole_readonly_contract(queries):
    with pytest.raises(ValidationError):
        ReadQueries(queries=queries)


async def test_authorization_is_fresh_for_each_read(bridge, config, monkeypatch):
    import kirabridge.read_queries as module

    root = Path(config.principals["local"].roots[0])
    file = root / "one.txt"
    file.write_text("literal")
    original = module.read_query_async
    calls = []

    async def read(b, principal, query):
        calls.append(query.operation)
        value = await original(b, principal, query)
        config.principals["local"].capabilities.remove("file.read")
        return value

    monkeypatch.setattr(module, "read_query_async", read)
    q = {"operation": "file.read", "path": str(file)}
    result = await read_queries(bridge, "local", ReadQueries(queries=[q, q]))
    assert result["results"][0]["result"]["text"] == "literal"
    assert result["results"][1]["result"]["error"]["code"] == "forbidden"
    assert calls == ["file.read", "file.read"]
    assert not bridge.store.db.execute("SELECT 1 FROM tasks").fetchone()


async def test_response_limit_stops_before_next_read(bridge, monkeypatch):
    import kirabridge.read_queries as module

    monkeypatch.setattr(module, "MAX_RESULT_BYTES", 8)
    read = AsyncMock(return_value={"value": "x" * 20})
    monkeypatch.setattr(module, "read_query_async", read)
    result = await read_queries(
        bridge,
        "local",
        ReadQueries(queries=[{"operation": "platform.status"}, {"operation": "platform.status"}]),
    )
    assert result["complete"] is False and result["omitted_read_executed"] is True
    assert read.await_count == 1


async def test_async_deadline_cancels_only_current_read_and_never_starts_next(bridge, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import kirabridge.read_queries as module

    loop = asyncio.get_running_loop()
    actual_timeout_at = asyncio.timeout_at
    monkeypatch.setattr(
        module,
        "asyncio",
        SimpleNamespace(
            get_running_loop=asyncio.get_running_loop,
            timeout_at=lambda deadline: actual_timeout_at(min(deadline, loop.time() + 0.01)),
        ),
    )
    entered, cancelled = [], []

    async def waiting(_bridge, _principal, query):
        entered.append(query.operation)
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.append(query.operation)
            raise

    monkeypatch.setattr(module, "read_query_async", waiting)
    result = await module.read_queries(
        bridge,
        "local",
        ReadQueries(queries=[{"operation": "platform.status"}] * 2),
    )
    assert not result["complete"] and result["read_only"]
    assert result["next_index"] == 1
    assert result["results"][0]["error"]["code"] == "read_timeout"
    assert entered == cancelled == ["platform.status"]
    assert not bridge.store.db.execute("SELECT 1 FROM tasks").fetchone()


async def test_batch_real_http_matches_individual_results(http_bridge):  # noqa: F811
    bridge, endpoint = http_bridge
    path = Path(bridge.config.principals["local"].roots[0]) / "fixture.txt"
    path.write_text("one read")
    queries = [
        {"operation": "file.read", "path": str(path)},
        {"operation": "file.list", "path": str(path.parent)},
    ]
    async with MCPClientPool() as pool:
        await pool.connect(Peer("caller", url=endpoint, token="local-test-" + "a" * 40))
        singles = [
            (await pool.call("caller", "read_query", {"query": q})).structuredContent
            for q in queries
        ]
        batch = (await pool.call("caller", "read_queries", {"queries": queries})).structuredContent
        assert batch["complete"] and batch["read_only"]
        assert [v["result"] for v in batch["results"]] == singles
        cached = (
            await pool.call(
                "caller", "read_query", {"query": {"operation": "read.batch", "queries": queries}}
            )
        ).structuredContent
        assert cached == batch
        denied = (
            await pool.call(
                "caller",
                "read_queries",
                {"queries": [queries[0], {"operation": "file.write", "path": str(path)}]},
            )
        ).structuredContent
        assert denied["error"]["code"] == "invalid_arguments"
    assert path.read_text() == "one read"
    assert not bridge.store.db.execute("SELECT 1 FROM tasks").fetchone()


async def test_expired_batch_never_starts_next_synchronous_read(bridge, monkeypatch):
    import time

    import kirabridge.read_queries as module

    monkeypatch.setattr(module, "READ_BATCH_SECONDS", 0.01)
    calls = []

    async def read(*args):
        calls.append(1)
        time.sleep(0.02)  # noqa: ASYNC251 - deliberately simulate a sync OS read.
        return {"one": 1}

    monkeypatch.setattr(module, "read_query_async", read)
    result = await read_queries(
        bridge, "local", ReadQueries(queries=[{"operation": "platform.status"}] * 2)
    )
    assert len(calls) == 1 and not result["complete"] and result["next_index"] == 1
