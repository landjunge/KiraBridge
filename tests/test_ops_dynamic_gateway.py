"""Gateway additions preserve response-mode wiring and keep peer prose private."""

from unittest.mock import AsyncMock

import pytest

from kirabridge.mcp_gateway.server import create_server


@pytest.mark.parametrize("name", ["threaddesk_dynamic_catalog", "threaddesk_dynamic_call"])
async def test_dynamic_gateway_never_echoes_unexpected_peer_exception(bridge, monkeypatch, name):
    failure = RuntimeError("synthetic private peer response /private/example token-example")
    handler = AsyncMock(side_effect=failure)
    target = "catalog" if name.endswith("catalog") else "call"
    monkeypatch.setattr(f"kirabridge.threaddesk_dynamic.{target}", handler)
    arguments = {} if target == "catalog" else {"name": "get_thread", "arguments": {"id": "one"}}
    _, result = await create_server(bridge).call_tool(name, arguments)
    assert result["error"] == {
        "code": "threaddesk_peer_failure",
        "message": "ThreadDesk peer failed: RuntimeError",
    }
    assert result["diagnostic"]["automatic_retry"] is False
    assert str(failure) not in str(result)


async def test_dynamic_gateway_passes_explicit_compact_mode(bridge, monkeypatch):
    handler = AsyncMock(return_value={"success": True})
    monkeypatch.setattr("kirabridge.threaddesk_dynamic.call", handler)
    arguments = {"id": "one"}
    _, result = await create_server(bridge).call_tool(
        "threaddesk_dynamic_call",
        {
            "name": "thread_manage",
            "arguments": arguments,
            "operation_id": "op-one",
            "compact_response": True,
        },
    )
    assert result["success"] is True
    handler.assert_awaited_once_with(
        bridge, "local", "thread_manage", arguments, "op-one", compact_response=True
    )
