"""Read aggregation retains real MCP validation, identity and bounded partial results."""

import asyncio
import socket
import time
from typing import Any

import pytest
import pytest_asyncio
import uvicorn
from conftest import request
from mcp import types
from mcp.server.fastmcp import Context

import kirabridge.read_tool_batch as module
from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.http import AuthenticatedHTTP
from kirabridge.mcp_gateway.server import create_server
from kirabridge.mcp_gateway.timing import TIMING_KEY


def replace_tool(server, name, fn):
    server._tool_manager.remove_tool(name)
    server.add_tool(fn, name=name)


@pytest_asyncio.fixture
async def batch_http(bridge, monkeypatch):
    monkeypatch.setenv("BATCH_TEST_LOCAL_TOKEN", "local-batch-" + "a" * 40)
    monkeypatch.setenv("BATCH_TEST_OTHER_TOKEN", "other-batch-" + "b" * 40)
    bridge.config.principals["local"].token_env = "BATCH_TEST_LOCAL_TOKEN"
    bridge.config.principals["other"].token_env = "BATCH_TEST_OTHER_TOKEN"
    server = create_server(bridge, transport="http")

    @server.tool(name="test_read_tool_batch")
    async def batch(calls: list[dict], ctx: Context) -> dict[str, Any]:
        principal = bridge.security.authenticate(
            ctx.request_context.request.headers["authorization"][7:]
        )
        try:
            return await module.read_tool_batch(server, bridge, principal, calls)
        except BridgeError as error:
            return {"error": {"code": error.code}}

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(64)
    bridge.config.port = sock.getsockname()[1]
    app = AuthenticatedHTTP(server.streamable_http_app(), bridge)
    http = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    async with bridge:
        task = asyncio.create_task(http.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(10):
                while not http.started:
                    if task.done():
                        await task
                    await asyncio.sleep(0.01)
            yield bridge, f"http://127.0.0.1:{bridge.config.port}/mcp"
        finally:
            http.should_exit = True
            await asyncio.wait_for(task, 10)
            sock.close()


@pytest.mark.parametrize(
    "bad",
    [
        {"tool": "task_request", "arguments": {}},
        {"tool": "keyboard_system_inventory", "arguments": {}},
        {"tool": "visible_handoff_status", "arguments": {"handoff_id": "x"}},
        {"tool": "threaddesk_dynamic_call", "arguments": {}},
        {"tool": "read_queries", "arguments": {"queries": []}},
        {"tool": "read_tool_batch", "arguments": {"calls": []}},
        {"tool": "read_query", "arguments": {"query": {"operation": "read.batch"}}},
        {"tool": "read_query", "arguments": {"query": {"operation": "tool.batch"}}},
        {"tool": "task_events", "arguments": {"task_id": "x", "after": "invalid"}},
        {"tool": "task_get", "arguments": {}},
        {"tool": "clipboard_info", "arguments": {"ctx": {"principal": "other"}}},
        {"tool": "clipboard_info", "arguments": {}, "principal": "other"},
        {"tool": "clipboard_info", "arguments": None},
    ],
)
async def test_all_names_and_arguments_validate_before_first_read(bridge, monkeypatch, bad):
    server = create_server(bridge)
    seen = []
    monkeypatch.setattr(bridge.clipboard, "info", lambda: seen.append(True))
    with pytest.raises(BridgeError):
        await module.read_tool_batch(server, bridge, "local", [{"tool": "clipboard_info"}, bad])
    assert not seen and not bridge.store.db.execute("SELECT 1 FROM tasks").fetchone()


@pytest.mark.parametrize("calls", [[], [{"tool": "clipboard_info"}] * 9, {}])
async def test_count_bounds(bridge, calls):
    with pytest.raises(BridgeError, match="1–8"):
        await module.read_tool_batch(create_server(bridge), bridge, "local", calls)


async def test_utf8_argument_budget_before_any_read(bridge, monkeypatch):
    seen = []
    monkeypatch.setattr(bridge.clipboard, "info", lambda: seen.append(True))
    with pytest.raises(BridgeError, match="64 KiB"):
        await module.read_tool_batch(
            create_server(bridge),
            bridge,
            "local",
            [
                {"tool": "clipboard_info"},
                {"tool": "task_get", "arguments": {"task_id": "ä" * 33000}},
            ],
        )
    assert not seen


async def test_advisory_read_annotation_never_grants_batch_access(bridge):
    server = create_server(bridge)
    called = []

    @server.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def unreviewed_read() -> dict[str, Any]:
        called.append(True)
        return {}

    with pytest.raises(BridgeError, match="whitelist"):
        await module.read_tool_batch(server, bridge, "local", [{"tool": "unreviewed_read"}])
    assert not called


async def test_real_http_context_envelopes_and_foreign_task_checks(batch_http, config):
    bridge, endpoint = batch_http
    value = request(task_id="batch-owned", arguments={"path": config.principals["local"].roots[0]})
    bridge.submit("local", value, bridge.security.grant("local", value))
    await bridge.tasks.wait("local", value.task_id)
    async with MCPClientPool() as pool:
        await pool.connect(Peer("local", url=endpoint, token="local-batch-" + "a" * 40))
        await pool.connect(Peer("other", url=endpoint, token="other-batch-" + "b" * 40))
        for principal in ("local", "other"):
            result = await pool.call(
                principal,
                "test_read_tool_batch",
                {
                    "calls": [
                        {"tool": "bridge_health"},
                        {"tool": "task_get", "arguments": {"task_id": value.task_id}},
                        {"tool": "task_events", "arguments": {"task_id": value.task_id}},
                    ]
                },
            )
            assert not result.isError, result.content
            batch = result.structuredContent
            assert batch["complete"]
            children = [
                types.CallToolResult.model_validate(row["result"]) for row in batch["results"]
            ]
            assert children[0].structuredContent["discovery"]["principal"] == principal
            assert all(TIMING_KEY in child.meta for child in children)
            if principal == "local":
                assert batch["all_succeeded"] and batch["errors"] == 0
                assert children[1].structuredContent["state"] == "completed"
                assert children[2].structuredContent["events"]
            else:
                assert not batch["all_succeeded"] and batch["errors"] == 2
                assert all(
                    child.structuredContent["error"]["code"] == "not_found"
                    for child in children[1:]
                )


async def test_current_rights_and_results_are_not_cached(batch_http, monkeypatch):
    bridge, endpoint = batch_http
    seen = []

    def info():
        seen.append(True)
        bridge.config.principals["local"].capabilities.remove("clipboard.info")
        return {"content_read": False, "counter": len(seen)}

    monkeypatch.setattr(bridge.clipboard, "info", info)
    async with MCPClientPool() as pool:
        await pool.connect(Peer("local", url=endpoint, token="local-batch-" + "a" * 40))
        result = (
            await pool.call(
                "local",
                "test_read_tool_batch",
                {"calls": [{"tool": "clipboard_info"}] * 2},
            )
        ).structuredContent
    assert result["complete"] and not result["all_succeeded"] and len(seen) == 1
    assert result["results"][0]["result"]["structuredContent"]["counter"] == 1
    assert result["results"][1]["result"]["structuredContent"]["error"]["code"] == "forbidden"


async def test_duplicate_reads_are_executed_independently_without_result_cache(bridge):
    server, seen = create_server(bridge), []

    def info() -> dict[str, Any]:
        seen.append(True)
        return {"counter": len(seen)}

    replace_tool(server, "clipboard_info", info)
    result = await module.read_tool_batch(server, bridge, "local", [{"tool": "clipboard_info"}] * 2)
    assert result["complete"] and result["all_succeeded"]
    assert [row["result"]["structuredContent"]["counter"] for row in result["results"]] == [1, 2]


async def test_deadline_cancels_only_current_read_and_never_starts_next(bridge):
    server, seen = create_server(bridge), []

    async def slow() -> dict[str, Any]:
        seen.append("entered")
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            seen.append("cancelled")
            raise

    def next_read() -> dict[str, Any]:
        seen.append("next")
        return {}

    replace_tool(server, "clipboard_info", slow)
    replace_tool(server, "bridge_health", next_read)
    result = await module.read_tool_batch(
        server,
        bridge,
        "local",
        [{"tool": "clipboard_info"}, {"tool": "bridge_health"}],
        deadline_seconds=0.03,
    )
    assert not result["complete"] and not result["all_succeeded"]
    assert result["error"]["code"] == "read_timeout" and result["next_index"] == 1
    assert result["results"][0]["completed"] == "unknown"
    assert seen == ["entered", "cancelled"]


async def test_synchronous_overrun_is_reported_and_stops_following_reads(bridge):
    server, seen = create_server(bridge), []

    def slow() -> dict[str, Any]:
        seen.append(True)
        time.sleep(0.02)
        return {"complete_read": True}

    replace_tool(server, "clipboard_info", slow)
    result = await module.read_tool_batch(
        server,
        bridge,
        "local",
        [{"tool": "clipboard_info"}] * 2,
        deadline_seconds=0.005,
    )
    assert not result["complete"] and result["error"]["code"] == "read_timeout"
    assert len(result["results"]) == len(seen) == 1 and result["read_executed"]
    assert result["results"][0]["result"]["structuredContent"]["complete_read"]


async def test_response_limit_preserves_prior_results_and_marks_omitted_read(bridge, monkeypatch):
    server, seen = create_server(bridge), []

    def info() -> dict[str, Any]:
        seen.append(len(seen))
        return {"value": "small" if len(seen) == 1 else "ä" * 10000}

    replace_tool(server, "clipboard_info", info)
    monkeypatch.setattr(module, "MAX_RESULT_BYTES", 5000)
    result = await module.read_tool_batch(server, bridge, "local", [{"tool": "clipboard_info"}] * 3)
    assert not result["complete"] and not result["all_succeeded"]
    assert result["error"]["code"] == "read_result_limit" and result["omitted_index"] == 1
    assert result["omitted_read_executed"] and result["next_index"] == 2
    assert len(result["results"]) == 1 and seen == [0, 1]


async def test_images_stop_explicitly_and_original_tool_still_returns_native_image(bridge):
    server, seen = create_server(bridge), []

    def picture(task_id: str) -> dict[str, Any]:
        seen.append(task_id)
        return types.CallToolResult(
            content=[types.ImageContent(type="image", data="AA==", mimeType="image/png")],
            structuredContent={"id": task_id, "image_snapshot": True},
        )

    replace_tool(server, "task_get", picture)
    result = await module.read_tool_batch(
        server,
        bridge,
        "local",
        [
            {"tool": "task_get", "arguments": {"task_id": "saved-picture"}},
            {"tool": "task_get", "arguments": {"task_id": "never-read"}},
        ],
    )
    assert not result["complete"] and not result["all_succeeded"]
    assert result["error"]["code"] == "tool_batch_unsupported_content"
    assert result["results"][0]["read_executed"] and result["results"][0]["result_omitted"]
    assert seen == ["saved-picture"]
    native = await server._mcp_server.request_handlers[types.CallToolRequest](
        types.CallToolRequest(
            params=types.CallToolRequestParams(
                name="task_get", arguments={"task_id": "saved-picture"}
            )
        )
    )
    assert isinstance(native.root.content[0], types.ImageContent)
    assert native.root.content[0].data == "AA=="


async def test_normal_tool_error_remains_visible(bridge):
    server = create_server(bridge)

    def failed() -> dict[str, Any]:
        raise RuntimeError("controlled_read_failure")

    replace_tool(server, "clipboard_info", failed)
    result = await module.read_tool_batch(server, bridge, "local", [{"tool": "clipboard_info"}])
    assert result["complete"] and not result["all_succeeded"] and result["errors"] == 1
    assert result["results"][0]["result"]["isError"]


@pytest.mark.parametrize("deadline", [True, 0, -1, 13, float("inf"), float("nan")])
async def test_global_deadline_is_bounded_before_reads(bridge, monkeypatch, deadline):
    seen = []
    monkeypatch.setattr(bridge.clipboard, "info", lambda: seen.append(True))
    with pytest.raises(BridgeError, match="deadline"):
        await module.read_tool_batch(
            create_server(bridge),
            bridge,
            "local",
            [{"tool": "clipboard_info"}],
            deadline_seconds=deadline,
        )
    assert not seen


async def test_task_observe_wait_is_clamped_to_remaining_global_budget(bridge):
    server, waits = create_server(bridge), []

    async def observe(query: dict[str, Any]) -> dict[str, Any]:
        waits.append(query["wait_seconds"])
        return {"pending": True}

    replace_tool(server, "read_query", observe)
    arguments = {"query": {"operation": "task.observe", "task_id": "existing", "wait_seconds": 18}}
    result = await module.read_tool_batch(
        server,
        bridge,
        "local",
        [{"tool": "read_query", "arguments": arguments}],
        deadline_seconds=0.1,
    )
    assert result["complete"] and 0 <= waits[0] <= 0.1
    assert arguments["query"]["wait_seconds"] == 18


async def test_actual_dedicated_and_cached_schema_alias_over_real_http(batch_http):
    _, endpoint = batch_http
    calls = [{"tool": "bridge_health"}, {"tool": "clipboard_info"}]
    async with MCPClientPool() as pool:
        await pool.connect(Peer("local", url=endpoint, token="local-batch-" + "a" * 40))
        for name, arguments in [
            ("read_tools", {"calls": calls}),
            ("read_query", {"query": {"operation": "tool.batch", "calls": calls}}),
        ]:
            response = await pool.call("local", name, arguments)
            assert not response.isError, response.content
            result = response.structuredContent
            assert result["complete"] and result["all_succeeded"] and result["read_only"]
            assert len(result["results"]) == 2
            assert result["results"][1]["result"]["structuredContent"]["content_read"] is False
            assert all(TIMING_KEY in row["result"]["_meta"] for row in result["results"])
