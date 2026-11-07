"""Invalid terminal selectors must fail equally on cached and direct clients."""

import pytest
from test_mcp import http_bridge  # noqa: F401

from kirabridge.mcp_gateway.client import MCPClientPool, Peer


@pytest.mark.parametrize(
    "arguments",
    [
        {"pane_id": "terminal:123:ttys001", "expected_pid": 0},
        {"pane_id": "terminal:123:ttys001", "expected_pid": -1},
        {"pane_id": "terminal:123:wrong-tty", "expected_pid": 123},
    ],
)
async def test_invalid_selector_has_one_error_before_any_terminal_probe(
    http_bridge,  # noqa: F811
    config,
    monkeypatch,
    arguments,
):
    bridge, endpoint = http_bridge
    config.principals["local"].capabilities += ["session.inspect"]
    config.principals["local"].permission_level = "full"
    calls = []

    async def catalog(principal, *, transport=None):
        calls.append("catalog")
        return {"sessions": [], "status": "available"}

    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        values = [
            ("session_read", arguments),
            ("read_query", {"query": {"operation": "session.read", **arguments}}),
            (
                "task_request",
                {
                    "request": {
                        "task_id": "invalid-target",
                        "idempotency_key": "invalid-target",
                        "operation": "session.read",
                        "arguments": arguments,
                    }
                },
            ),
        ]
        for tool, value in values:
            result = (await clients.call("local", tool, value)).structuredContent
            assert result["error"]["code"] == "invalid_arguments", (tool, result)
    assert not calls
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
