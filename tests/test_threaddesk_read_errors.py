"""Content-free lifecycle errors and operation-bound size diagnostics."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mcp.types import CallToolResult, TextContent

from kirabridge.threaddesk_dynamic import call
from kirabridge.threaddesk_manager import ThreadDeskManager


def contract(limit=3):
    return {
        "oneOf": [
            {
                "properties": {
                    "action": {"const": "set_note"},
                    "data": {
                        "type": "object",
                        "properties": {"text": {"type": "string", "maxLength": limit}},
                        "required": ["text"],
                    },
                }
            }
        ]
    }


def error(code, **extra):
    return CallToolResult(content=[], isError=True, structuredContent={"code": code, **extra})


def request(**data):
    return {
        "operation_id": "size-rejection-only",
        "id": "synthetic",
        "action": "set_note",
        "expected_revision": 1,
        "data": data,
    }


@pytest.mark.parametrize(
    "code", ["object_in_trash", "object_changed_in_trash", "lifecycle_conflict"]
)
def test_lifecycle_code_preserved_without_write_limits_or_peer_contents(config, code):
    manager = ThreadDeskManager(config)
    manager.tool_schemas["thread_manage"] = contract()
    ok, value = manager.decode(
        error(
            code,
            message="PRIVATE_PEER_BODY",
            details={"object_id": "PRIVATE_ID", "max_length": 3, "actual_length": 4},
        ),
        mutation=False,
    )
    assert not ok and value["error"]["code"] == code
    assert value["error"]["details"] == {}
    assert "PRIVATE" not in str(value)
    assert "limit" not in value["error"]["message"].lower()


def test_read_size_error_keeps_valid_numeric_pair_without_write_contract(config):
    manager = ThreadDeskManager(config)
    manager.tool_schemas["thread_manage"] = contract()
    ok, value = manager.decode(
        error("validation_error", details={"max_bytes": 3, "actual_bytes": 4}), mutation=False
    )
    assert not ok
    assert value["error"]["details"] == {"max_bytes": 3, "actual_bytes": 4}


@pytest.mark.parametrize(
    ("tool", "mutation", "code", "expected"),
    [
        ("library_search", False, "index_stale", "index_stale"),
        ("library_search", False, "PRIVATE_UNKNOWN_CODE", "threaddesk_rejected"),
        ("library_search", True, "index_stale", "threaddesk_rejected"),
        ("library_query", False, "index_stale", "threaddesk_rejected"),
        (None, False, "index_stale", "threaddesk_rejected"),
    ],
)
def test_library_search_index_error_is_scoped_and_content_free(
    config, tool, mutation, code, expected
):
    raw_error = {
        "code": code,
        "error": "PRIVATE_PEER_TEXT",
        "details": {"path": "PRIVATE_PEER_PATH", "actual_revision": 3},
    }
    response = CallToolResult(
        content=[TextContent(type="text", text=json.dumps(raw_error))], isError=True
    )
    ok, value = ThreadDeskManager(config).decode(
        response, mutation=mutation, verified_read_tool=tool
    )
    assert not ok and value["error"]["code"] == expected
    assert value["error"]["details"] == {}
    assert "PRIVATE" not in str(value)


@pytest.mark.parametrize("mutation", [False, True])
@pytest.mark.parametrize("unknown", ["PRIVATE_UNKNOWN_CODE", ["PRIVATE"], {"PRIVATE": "CODE"}])
def test_unknown_error_stays_redacted_without_invented_size_hints(config, mutation, unknown):
    manager = ThreadDeskManager(config)
    manager.tool_schemas["thread_manage"] = contract()
    ok, value = manager.decode(
        error(
            unknown,
            message="PRIVATE_PEER_BODY",
            details={"actual_length": 4, "max_length": 3, "body": "PRIVATE_BODY"},
        ),
        mutation=mutation,
    )
    assert not ok and value["error"]["code"] == "threaddesk_rejected"
    assert value["error"]["details"] == {}
    assert "PRIVATE" not in str(value)
    assert "limit" not in value["error"]["message"].lower()


def test_real_write_size_context_explains_only_the_relevant_field(config):
    manager = ThreadDeskManager(config)
    manager.tool_schemas["thread_manage"] = contract()
    # The pinned legacy TD peer reports validation_error without numeric details.
    ok, value = manager.decode(
        error("validation_error", message="PRIVATE_REJECTED_TEXT"),
        mutation=True,
        management_request=request(text="four"),
    )
    assert not ok and value["error"]["code"] == "validation_error"
    assert value["error"]["details"] == {
        "actual_length": 4,
        "max_length": 3,
        "text_max_characters": 3,
        "limit_source": "peer_tools_list",
    }
    assert "PRIVATE" not in str(value)


@pytest.mark.parametrize("schema", [contract(), {"$ref": "https://PRIVATE.invalid/schema"}])
def test_other_write_validation_and_invalid_schema_do_not_invent_size_hints(config, schema):
    manager = ThreadDeskManager(config)
    manager.tool_schemas["thread_manage"] = schema
    ok, value = manager.decode(
        error("validation_error", details={"actual_length": True, "max_length": -1}),
        mutation=True,
        management_request=request(text="ok"),
    )
    assert not ok and value["error"]["details"] == {}
    assert "PRIVATE" not in str(value)
    assert "limit" not in value["error"]["message"].lower()


@pytest.mark.skipif(
    not os.environ.get("KIRABRIDGE_TEST_THREADDESK_SOURCE"),
    reason="Pinned ThreadDesk source required for the actual isolated MCP peer",
)
async def test_actual_td_get_thread_trash_valid_window_and_size_rejection(bridge, config, tmp_path):
    source = Path(os.environ["KIRABRIDGE_TEST_THREADDESK_SOURCE"]).resolve()
    workspace = tmp_path / "isolated-td-errors"
    workspace.mkdir(mode=0o700)
    # Real owner API, only in this temporary workspace; no operator IDs or data.
    prepared = await asyncio.to_thread(
        subprocess.run,
        [
            sys.executable,
            "-I",
            "-c",
            "import sys,json; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
            "from threaddesk.api.service import ThreadService; "
            "from threaddesk.storage.json_store import JsonStore; "
            "from threaddesk.services.trash import TrashService; "
            "store=JsonStore(Path(sys.argv[2])); svc=ThreadService(store); "
            "live=svc.create('Live fixture'); dead=svc.create('Trashed fixture'); "
            "TrashService(store).move(kind='thread',object_id=dead.id,"
            "expected_revision=dead.revision,operation_id='own-fixture-trash'); "
            "print(json.dumps({'live':live.id,'dead':dead.id,'revision':live.revision}))",
            str(source),
            str(workspace),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    ids = json.loads(prepared.stdout)
    protected = [workspace / "threads" / f"{ids[key]}.json" for key in ("live", "dead")]
    protected += list((workspace / "trash").glob("*.json"))
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    settings = config.threaddesk
    config.principals["local"].approval_mode = "automatic"
    settings.enabled = settings.dynamic_read_proxy = True
    settings.command, settings.args = sys.executable, ["-m", "threaddesk.ui.mcp_stdio"]
    settings.workspace, settings.source_root = str(workspace), str(source)
    try:
        live = await call(bridge, "local", "get_thread", {"id": ids["live"], "max_chars": 12000})
        assert live["success"] and live["value"]["id"] == ids["live"]
        trashed = await call(bridge, "local", "get_thread", {"id": ids["dead"], "max_chars": 12000})
        assert not trashed["success"]
        assert trashed["value"]["error"]["code"] == "object_in_trash"
        assert trashed["value"]["error"]["details"] == {}
        oversized = {
            **request(text="X" * 100001),
            "id": ids["live"],
            "expected_revision": ids["revision"],
        }
        # Exercise the actual peer rejection below the KB preflight, which would
        # correctly reject the same oversized request without sending it.
        response = await bridge.threaddesk.pool.call("threaddesk", "thread_manage", oversized)
        assert response.isError
        ok, value = bridge.threaddesk.decode(response, mutation=True, management_request=oversized)
        assert not ok and value["error"]["code"] == "validation_error"
        assert value["error"]["details"]["actual_length"] == 100001
        assert value["error"]["details"]["text_max_characters"] == 100000
        assert "description_max_characters" not in value["error"]["details"]
        assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected} == before
    finally:
        await bridge.threaddesk.close()
