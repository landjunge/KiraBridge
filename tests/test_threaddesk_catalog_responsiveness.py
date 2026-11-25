"""Large synthetic catalogs must not starve the MCP server event loop."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.types import Tool, ToolAnnotations

from kirabridge.threaddesk_dynamic import _fresh_tools


def _management_schema(index: int) -> dict:
    fields = {
        "create": {"title", "description", "project_id", "parent_thread_id"},
        "update": {"title", "description", "status"},
        "set_note": {"text", "append"},
        "add_file": {"path"},
        "remove_file": {"path"},
        "organize": {"project_id", "parent_thread_id", "related_thread_ids"},
        "archive": set(),
        "unarchive": set(),
        "delete": set(),
        "switch": set(),
        "snapshot": {"label"},
        "restore_snapshot": {"snapshot_id"},
    }
    properties = {
        "title": {"type": "string", "minLength": 1, "maxLength": 10000},
        "description": {"type": "string", "maxLength": 10000},
        "status": {"type": "string", "enum": ["idea", "active", "paused", "done"]},
        "text": {"type": "string", "maxLength": 100000},
        "append": {"type": "boolean"},
        "path": {"type": "string", "minLength": 1, "maxLength": 10000},
        "project_id": {"type": ["string", "null"], "pattern": "^[A-Za-z0-9_-]{1,128}$"},
        "parent_thread_id": {
            "type": ["string", "null"],
            "pattern": "^[A-Za-z0-9_-]{1,128}$",
        },
        "label": {"type": "string", "maxLength": 10000},
        "snapshot_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$"},
        "related_thread_ids": {
            "type": "array",
            "maxItems": 100,
            "uniqueItems": True,
            "items": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$"},
        },
    }
    required = {
        "create": ["title"],
        "set_note": ["text"],
        "add_file": ["path"],
        "remove_file": ["path"],
        "restore_snapshot": ["snapshot_id"],
    }
    variants = []
    for action, names in fields.items():
        data = {
            "type": "object",
            "additionalProperties": False,
            "properties": {key: properties[key] for key in sorted(names)},
        }
        if action in required:
            data["required"] = required[action]
        if action in {"update", "organize"}:
            data["minProperties"] = 1
        variant = {"properties": {"action": {"const": action}, "data": data}}
        if action in required or action in {"update", "organize"}:
            variant["required"] = ["data"]
        if action == "create":
            variant["properties"]["expected_revision"] = {"const": 0}
            variant["not"] = {"required": ["id"]}
        else:
            variant.setdefault("required", []).append("id")
        variants.append(variant)
    return {
        "type": "object",
        "additionalProperties": False,
        "description": f"synthetic schema {index}",
        "required": ["operation_id", "action", "expected_revision"],
        "properties": {
            "operation_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$"},
            "action": {"type": "string", "enum": list(fields)},
            "id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$"},
            "expected_revision": {"type": "integer", "minimum": 0},
            "data": {"type": "object"},
        },
        "oneOf": variants,
    }


@pytest.mark.asyncio
async def test_large_catalog_validation_yields_to_other_mcp_requests():
    tools = [
        Tool(
            name=f"thread_manage_{index}",
            description="Synthetic management tool",
            annotations=ToolAnnotations(
                readOnlyHint=True, destructiveHint=False, openWorldHint=False
            ),
            inputSchema=_management_schema(index),
        )
        for index in range(40)
    ]
    manager = SimpleNamespace(
        settings=SimpleNamespace(timeout=1),
        connect=AsyncMock(),
        read_catalog=AsyncMock(return_value=tools),
        note_success=lambda: None,
    )
    heartbeat = asyncio.Event()
    loop = asyncio.get_running_loop()
    scheduled = loop.time()
    observed_delay = []

    async def other_request():
        await asyncio.sleep(0)
        observed_delay.append(loop.time() - scheduled)
        heartbeat.set()

    pending = asyncio.create_task(other_request())
    approved = await _fresh_tools(manager)
    await asyncio.wait_for(heartbeat.wait(), timeout=2)
    await pending

    assert len(approved) == len(tools)
    assert observed_delay and observed_delay[0] < 1
    manager.read_catalog.assert_awaited_once()
