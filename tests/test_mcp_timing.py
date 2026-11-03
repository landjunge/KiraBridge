"""Standard response metadata describes local spans without changing tool results."""

import json

from mcp.types import CallToolResult, ImageContent, TextContent
from test_mcp import http_bridge  # noqa: F401

from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.proxy import DaemonConnection
from kirabridge.mcp_gateway.timing import TIMING_KEY, ToolSpan


def test_timing_preserves_images_errors_payload_and_previous_spans():
    original = CallToolResult(
        content=[
            TextContent(type="text", text="unchanged"),
            ImageContent(type="image", mimeType="image/png", data="AA=="),
        ],
        structuredContent={"private_input": "must not become timing metadata"},
        isError=True,
        _meta={"existing": 1},
    )
    daemon = ToolSpan().result(original, "daemon")
    proxy = ToolSpan().result(daemon, "stdio_proxy")
    assert proxy.content == original.content
    assert proxy.structuredContent == original.structuredContent and proxy.isError
    assert original.meta == {"existing": 1} and "stdio_proxy" not in daemon.meta[TIMING_KEY]
    timing = proxy.meta[TIMING_KEY]
    assert timing["trace_id"] == daemon.meta[TIMING_KEY]["trace_id"]
    assert 0 <= timing["daemon"]["duration_ms"] < 1000
    assert "private_input" not in json.dumps(timing)


async def test_real_http_and_proxy_expose_correlated_local_spans(http_bridge):  # noqa: F811
    _, endpoint = http_bridge
    async with MCPClientPool() as pool:
        connection = DaemonConnection(
            pool, Peer("timed", url=endpoint, token="local-test-" + "a" * 40)
        )
        result = await connection.call_tool("clipboard_info", {})
        timing = result.meta[TIMING_KEY]
        assert "daemon" in timing and "proxy_dispatch" in timing
        assert timing["proxy_dispatch"]["duration_ms"] >= timing["daemon"]["duration_ms"]
        assert timing["proxy_dispatch"]["catalog_ms"] >= 0
        assert TIMING_KEY not in result.structuredContent
        denied = await connection.call_tool("read_query", {"query": {"operation": "invalid"}})
        assert "daemon" in denied.meta[TIMING_KEY]
        assert denied.isError or denied.structuredContent.get("error")


def test_compaction_is_lossless_and_keeps_complete_json_fallback():
    from kirabridge.mcp_gateway.timing import compact_structured_text

    data = {"unicode": "ä 👩‍💻", "values": [{"name": "unchanged", "number": 12}] * 50}
    original = CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data, indent=2))], structuredContent=data
    )
    result = compact_structured_text(original)
    assert result.structuredContent == data and json.loads(result.content[0].text) == data
    assert len(result.content[0].text.encode()) < len(original.content[0].text.encode())
    assert original.content[0].text != result.content[0].text
    custom = original.model_copy(
        update={"content": [TextContent(type="text", text="custom summary")]}
    )
    assert compact_structured_text(custom) is custom


def test_compaction_keeps_json_types_of_custom_fallback():
    from kirabridge.mcp_gateway.timing import compact_structured_text

    for fallback, structured in [(True, 1), (1, 1.0), (False, 0)]:
        result = CallToolResult(
            content=[TextContent(type="text", text=json.dumps({"x": fallback}, indent=2))],
            structuredContent={"x": structured},
        )
        assert compact_structured_text(result) is result
