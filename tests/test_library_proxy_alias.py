"""The retained Apps library alias uses the same live read contract end to end."""

import base64
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from test_mcp import http_bridge  # noqa: F401

import kirabridge
from kirabridge.mcp_gateway.proxy import dynamic_catalog_names, dynamic_compatibility_aliases


@pytest.mark.parametrize(
    "changed",
    [
        {"readOnly": False},
        {"requires_operation_id": True},
        {"annotations": {"destructiveHint": True}},
        {"name": "writer"},
        {"readOnly": None},
        {"annotations": {"destructiveHint": False}},
    ],
)
def test_legacy_alias_never_reclassifies_or_guesses_a_peer(changed):
    item = {
        "name": "td_library_uquery",
        "readOnly": True,
        "requires_operation_id": False,
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    }
    assert dynamic_compatibility_aliases({"td_library_uquery": item}) == {
        "td_td_library_uquery": item
    }
    assert not dynamic_compatibility_aliases({"td_library_uquery": {**item, **changed}})
    assert not dynamic_compatibility_aliases({"td_library_umanage": item})
    assert not dynamic_compatibility_aliases({})


def test_ambiguous_or_occupied_alias_is_not_advertised():
    item = {
        "name": "td_library_uquery",
        "readOnly": True,
        "requires_operation_id": False,
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {"type": "object"},
    }
    names = dynamic_catalog_names([item])
    assert names["td_td_library_uquery"] is item
    assert not dynamic_catalog_names([])
    ambiguous = dynamic_catalog_names([item, {**item, "name": "library_uquery"}])
    assert "td_library_uquery" not in ambiguous and "td_td_library_uquery" not in ambiguous
    occupied = dynamic_catalog_names(
        [
            item,
            {
                **item,
                "name": "td_td_library_uquery",
                "requires_operation_id": True,
                "readOnly": False,
            },
        ]
    )
    assert "td_library_uquery" in occupied and "td_td_library_uquery" not in occupied


async def test_real_stdio_proxy_library_discovery_calls_and_revocation(
    http_bridge,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    # Both transports are real: MCP client -> stdio proxy -> HTTP daemon ->
    # ThreadDesk stdio process. Only temporary stores and a synthetic token.
    from threaddesk.api.service import ThreadService
    from threaddesk.services import mcp as td_mcp
    from threaddesk.storage.json_store import JsonStore

    bridge, _ = http_bridge
    workspace = tmp_path / "desk"
    service = ThreadService(JsonStore(workspace))
    thread = service.create("Synthetic library read")
    owner = td_mcp.McpBridge(service)
    content = "Verified full text: ä\n" * 50
    data = content.encode()
    for args in (
        {
            "action": "begin",
            "transfer_id": "library-read",
            "thread_id": thread.id,
            "filename": "read.txt",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        {
            "action": "append",
            "transfer_id": "library-read",
            "offset": 0,
            "data_base64": base64.b64encode(data).decode(),
        },
        {"action": "commit", "transfer_id": "library-read"},
    ):
        received = owner.call("library_receive", args)
        assert received["ok"], received
    record = received["result"]["receipt"]["record_id"]
    workspace_id = owner.commands.application.catalog(limit=1)["workspace_id"]
    settings = bridge.config.threaddesk
    settings.enabled = settings.dynamic_read_proxy = True
    settings.command = sys.executable
    settings.args = ["-m", "threaddesk.ui.mcp_stdio"]
    settings.workspace = str(workspace)
    settings.source_root = str(Path(td_mcp.__file__).resolve().parents[2])
    settings.timeout = 10
    policy = bridge.config.principals["local"]
    policy.approval_mode = "automatic"
    config = tmp_path / "proxy.toml"
    config.write_text(
        f"data_dir = {json.dumps(str(tmp_path / 'proxy-state'))}\n"
        f"port = {bridge.config.port}\n[principals.local]\n"
        'token_env = "BRIDGE_TEST_TOKEN"\n'
    )
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "kirabridge.cli", "--config", str(config), "connect"],
        env={
            "PYTHONPATH": str(Path(kirabridge.__file__).resolve().parent.parent),
            "BRIDGE_TEST_TOKEN": "local-test-" + "a" * 40,
        },
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        names = ("td_library_query", "td_library_uquery", "td_td_library_uquery")
        assert set(names) <= tools.keys()
        assert "td_td_library_umanage" not in tools
        for name in names:
            for action in ("info", "preview"):
                inner = {"action": action, "id": record}
                args = (
                    inner
                    if name == names[0]
                    else {"workspace_id": workspace_id, "arguments": inner}
                )
                response = await session.call_tool(name, args)
                assert not response.isError, response
                value = response.structuredContent
                assert value["success"], value
                result = value["value"] if name == names[0] else value["value"]["result"]
                assert result["integrity"] == "verified"
                if action == "preview":
                    assert result["text"] == content and result["truncated"] is False
        for name in names[1:]:
            wrong = await session.call_tool(
                name, {"workspace_id": thread.id, "arguments": {"action": "preview", "id": record}}
            )
            assert wrong.isError or wrong.structuredContent["success"] is False
            assert wrong.structuredContent["value"]["error"]["code"] == "workspace_mismatch"
            invalid = await session.call_tool(
                name,
                {
                    "workspace_id": workspace_id,
                    "arguments": {"action": "preview", "id": record, "thread_id": thread.id},
                },
            )
            assert invalid.isError
        invalid = await session.call_tool(
            names[0], {"action": "preview", "id": record, "workspace_id": workspace_id}
        )
        assert invalid.isError
        calls = AsyncMock(wraps=bridge.threaddesk.pool.call)
        monkeypatch.setattr(bridge.threaddesk.pool, "call", calls)
        policy.capabilities.remove("threaddesk.read")
        denied = await session.call_tool(
            names[2],
            {"workspace_id": workspace_id, "arguments": {"action": "preview", "id": record}},
        )
        assert denied.isError
        calls.assert_not_awaited()
