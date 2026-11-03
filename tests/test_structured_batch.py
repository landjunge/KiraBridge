import json
from typing import Any

import pytest
from mcp import types
from test_mcp import http_bridge  # noqa: F401
from test_read_tool_batch import replace_tool

import kirabridge.read_tool_batch as batch
from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.server import create_server
from kirabridge.mcp_gateway.timing import TIMING_KEY, equivalent_structured_text


def envelope(text, data, **block_fields):
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text, **block_fields)],
        structuredContent=data,
        _meta={"original": {"trace": "kept"}},
    )


@pytest.mark.parametrize(
    "text,data",
    [
        ('{"x":1.00000000000000001}', {"x": 1.0}),
        ('{"x":1,"x":2}', {"x": 2}),
        ('{"x":true}', {"x": 1}),
        ('{"x":1.0}', {"x": 1}),
        ('{"x":-0}', {"x": 0}),
        ('{"x":-0.0}', {"x": 0.0}),
        ('{"x":NaN}', {"x": None}),
    ],
)
def test_exact_equivalence_never_rounds_or_discards_custom_numeric_information(text, data):
    assert not equivalent_structured_text(envelope(text, data))


@pytest.mark.parametrize(
    "block_fields",
    [{}, {"annotations": {"audience": ["user"]}}, {"_meta": {"note": "keep"}}, {"extra": None}],
)
async def test_structured_mode_preserves_block_annotations_metadata_and_extra_fields(
    bridge, block_fields
):
    server = create_server(bridge)
    original = envelope('{"x":1}', {"x": 1}, **block_fields)

    def info() -> dict[str, Any]:
        return original

    replace_tool(server, "clipboard_info", info)
    response = await batch.read_tool_batch(
        server, bridge, "local", [{"tool": "clipboard_info"}], result_format="structured"
    )
    row = response["results"][0]
    assert row["result"]["structuredContent"] == {"x": 1}
    assert row["result"]["_meta"]["original"] == {"trace": "kept"}
    if block_fields:
        assert (
            row["result"]["content"] == original.model_dump(mode="json", by_alias=True)["content"]
        )
        assert "content_omitted" not in row
    else:
        assert row["result"]["content"] == []
        assert row["content_omitted"] == "equivalent_structured_json"


@pytest.mark.parametrize("format_name", [None, [], {}, True, "unknown"])
async def test_bad_result_format_rejected_before_any_tool_read(bridge, monkeypatch, format_name):
    calls = []
    monkeypatch.setattr(bridge.clipboard, "info", lambda: calls.append(True))
    with pytest.raises(BridgeError, match="full or structured"):
        await batch.read_tool_batch(
            create_server(bridge),
            bridge,
            "local",
            [{"tool": "clipboard_info"}],
            result_format=format_name,
        )
    assert not calls


def test_incremental_wire_budget_matches_real_mcp_encoding_with_unicode_floats_and_errors():
    rows, total = [], 0
    values = ['ä😀"\n\\', 1e-7, 1e-6, 1e20, -0.0, [True, 1, 1.0], {"error": {"code": "denied"}}]
    for i, value in enumerate(values):
        data = value if isinstance(value, dict) else {"value": value}
        row = {
            "index": i,
            "tool": "task_get",
            "result": envelope(json.dumps(data), data).model_dump(mode="json", by_alias=True),
        }
        total += batch._row_wire_bytes(row) + (2 if rows else 0)
        rows.append(row)
        expected = batch._response(rows, complete=True)
        base = batch._response([], complete=True)
        base.update(errors=expected["errors"], all_succeeded=expected["all_succeeded"])
        assert batch._wire_size(base) + total == batch._wire_size(expected)


async def test_structured_mode_fits_eight_complete_payloads_inside_original_budget(bridge):
    server = create_server(bridge)
    payload = "x" * 65536

    def get(task_id: str) -> dict[str, Any]:
        return {"id": task_id, "result": {"text": payload}}

    replace_tool(server, "task_get", get)
    calls = [{"tool": "task_get", "arguments": {"task_id": f"one_{i}"}} for i in range(8)]
    full = await batch.read_tool_batch(server, bridge, "local", calls)
    assert not full["complete"] and full["error"]["code"] == "read_result_limit"
    assert full["resume_index"] == full["omitted_index"]
    structured = await batch.read_tool_batch(
        server, bridge, "local", calls, result_format="structured"
    )
    assert structured["complete"] and len(structured["results"]) == 8
    assert batch._wire_size(structured) <= batch.MAX_RESULT_BYTES
    assert [r["result"]["structuredContent"]["result"]["text"] for r in structured["results"]] == [
        payload
    ] * 8


async def test_full_default_and_structured_cached_alias_over_real_http(http_bridge):  # noqa: F811
    _, endpoint = http_bridge
    calls = [{"tool": "clipboard_info"}]
    async with MCPClientPool() as pool:
        await pool.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        full = (await pool.call("local", "read_tools", {"calls": calls})).structuredContent
        compact = (
            await pool.call(
                "local",
                "read_query",
                {
                    "query": {
                        "operation": "tool.batch",
                        "calls": calls,
                        "result_format": "structured",
                    }
                },
            )
        ).structuredContent
    assert "result_format" not in full and full["results"][0]["result"]["content"]
    row = compact["results"][0]
    assert compact["all_succeeded"] and compact["result_format"] == "structured"
    assert row["result"]["content"] == []
    assert row["result"]["structuredContent"] == full["results"][0]["result"]["structuredContent"]
    assert TIMING_KEY in row["result"]["_meta"]
