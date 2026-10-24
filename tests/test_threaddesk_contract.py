"""Targeted Whiteboard preflight and actual MCP byte/readback/uncertain-write boundaries."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult, TextContent

from kirabridge.bridge_core.models import (
    ThreadDeskManageInput,
    ThreadDeskReadInput,
    UncertainExecution,
)
from kirabridge.threaddesk_contract import validate_management
from kirabridge.threaddesk_manager import ThreadDeskManager


def values(action="create", **data):
    return {
        "operation_id": "original",
        "action": action,
        **({} if action == "create" else {"id": "thread-one"}),
        "expected_revision": 0 if action == "create" else 1,
        "data": data,
    }


def declared(action, field, limit):
    return {
        "oneOf": [
            {
                "properties": {
                    "action": {"const": action},
                    "data": {
                        "type": "object",
                        "properties": {field: {"type": "string", "maxLength": limit}},
                        "required": [field],
                    },
                }
            }
        ]
    }


@pytest.mark.parametrize("field,limit", [("description", 10000), ("text", 100000)])
def test_exact_character_boundaries_and_utf8_not_confused(field, limit):
    action = "create" if field == "description" else "set_note"
    body = {field: "🧠" * limit}
    if action == "create":
        body["title"] = "synthetic"
    assert validate_management(values(action, **body), None) is None
    body[field] += "ä"
    error = validate_management(values(action, **body), None)
    assert error["details"]["characters"] == limit + 1
    assert error["details"]["utf8_bytes"] == limit * 4 + 2
    assert error["details"]["limit_source"] == "kirabridge_legacy_compatibility"
    assert "🧠" not in json.dumps(error, ensure_ascii=False)


def test_current_declared_peer_limits_override_legacy_fallback():
    packet = values("set_note", text="Grüße🧠")
    assert validate_management(packet, declared("set_note", "text", 6)) is None
    error = validate_management(packet, declared("set_note", "text", 5))
    assert error["details"]["limit"] == 5
    assert error["details"]["limit_source"] == "peer_tools_list"
    assert not error["details"]["request_sent"]


@pytest.mark.parametrize(
    "packet",
    [
        values(title="ok", unsupported="original"),
        values("set_note", text="ok", append="true"),
        values("update"),
        values("organize", related_thread_ids=["one", "one"]),
        {**values(title="ok"), "id": "not-allowed"},
    ],
)
def test_invalid_field_types_and_action_shape_return_content_free_errors(packet):
    assert validate_management(packet, None)["code"] == "threaddesk_validation"


async def test_preflight_rejects_before_running_or_mutation(config):
    manager = ThreadDeskManager(config)
    manager.available_tools = {"thread_manage"}

    async def connect():
        pass

    manager.connect = connect

    async def tools(_):
        return [SimpleNamespace(name="thread_manage", inputSchema=declared("set_note", "text", 3))]

    manager.pool.list_tools = tools

    async def forbidden(*args, **kwargs):
        raise AssertionError("No mutation/running after local field rejection")

    manager.pool.call = forbidden
    result = await manager.execute(
        {"id": "test", "principal": "local"},
        ThreadDeskManageInput(**values("set_note", text="four")),
        forbidden,
    )
    assert not result["success"] and not result["evidence"]["request_sent"]
    assert result["value"]["error"]["details"]["limit"] == 3


def test_peer_error_keeps_numeric_limit_details_but_no_secret_message(config):
    manager = ThreadDeskManager(config)
    manager.tool_schemas["thread_manage"] = declared("set_note", "text", 12)
    result = CallToolResult(
        isError=True,
        content=[],
        structuredContent={
            "code": "validation_error",
            "error": "secret source body",
            "details": {"actual_length": 13, "max_length": 12, "content": "secret source body"},
        },
    )
    ok, value = manager.decode(result, mutation=True)
    assert not ok and value["error"]["details"]["max_length"] == 12
    assert "secret source body" not in str(value)


@pytest.fixture
def receiver(config, tmp_path):
    workspace = tmp_path / "whiteboard-receiver"
    workspace.mkdir(mode=0o700)
    config.threaddesk.enabled = True
    config.threaddesk.workspace = str(workspace)
    config.threaddesk.command = sys.executable
    config.threaddesk.args = [str(Path(__file__).with_name("whiteboard_mcp_fixture.py"))]
    return config, workspace


async def invoke(manager, args, identity="task"):
    evidence = []

    async def running(value):
        evidence.append(value)

    return await manager.execute({"id": identity, "principal": "local"}, args, running)


@pytest.mark.parametrize(
    "body",
    ["short", '長い記録 🧠 ä\n"quoted"\\slash\r\n' * 4000, "🧠" * 100000],
    ids=["short", "long-unicode", "max-100000"],
)
async def test_actual_mcp_complete_long_unicode_note_and_readback(receiver, body):
    config, workspace = receiver
    manager = ThreadDeskManager(config)
    try:
        created = await invoke(manager, ThreadDeskManageInput(**values(title="synthetic")))
        identifier, rev = created["value"]["thread_id"], created["value"]["revision"]
        note = values("set_note", text=body, append=False)
        note.update(id=identifier, expected_revision=rev, operation_id="note")
        saved = await invoke(manager, ThreadDeskManageInput(**note))
        assert saved["success"] and saved["evidence"]["mutation_receipt_validated"]
        read = await invoke(
            manager, ThreadDeskReadInput(tool="get_thread", arguments={"id": identifier})
        )
        assert read["value"]["notes"] == body
        disk = json.loads((workspace / "whiteboard-fixture.json").read_text())
        assert disk["threads"][identifier]["notes"] == body
    finally:
        await manager.close()


async def test_actual_lost_create_receipt_reconciles_without_second_create(receiver):
    config, workspace = receiver
    config.threaddesk.args.append("--lose-receipt")
    manager = ThreadDeskManager(config)
    args = ThreadDeskManageInput(**values(title="once"))
    try:
        with pytest.raises(UncertainExecution, match="receipt"):
            await invoke(manager, args)
        # A read reconnects; no automatic mutation replay.
        state = await invoke(
            manager,
            ThreadDeskReadInput(
                tool="thread_operation_status", arguments={"operation_id": "original"}
            ),
        )
        assert state["value"]["found"]
        assert len(json.loads((workspace / "whiteboard-fixture.json").read_text())["threads"]) == 1
    finally:
        await manager.close()


def test_oversized_mutation_response_is_unknown_not_a_success(config):
    config.threaddesk.max_result_bytes = 1024
    manager = ThreadDeskManager(config)
    with pytest.raises(UncertainExecution) as failure:
        manager.decode(
            CallToolResult(
                content=[TextContent(type="text", text=json.dumps({"notes": "🧠" * 1024}))]
            ),
            mutation=True,
        )
    assert failure.value.code == "threaddesk_result_limit"


def test_invalid_unicode_reports_no_content_and_never_encodes_transport():
    error = validate_management(values("set_note", text="\ud800"), None)
    assert error["details"]["utf8_bytes"] is None
    assert error["details"]["characters"] == 1
    assert error["details"]["constraint"] == "valid UTF-8 required"


async def test_removed_tool_during_schema_refresh_is_not_called(config):
    manager = ThreadDeskManager(config)
    manager.available_tools = {"thread_manage"}

    async def connect():
        pass

    async def listed(_):
        return []

    async def forbidden(*args, **kwargs):
        raise AssertionError("Removed operation cannot be sent")

    manager.connect, manager.pool.list_tools, manager.pool.call = connect, listed, forbidden
    with pytest.raises(Exception) as error:
        await manager.execute(
            {"id": "test", "principal": "local"},
            ThreadDeskManageInput(**values(title="safe")),
            forbidden,
        )
    assert error.value.code == "threaddesk_version"


def test_incomplete_peer_field_limit_uses_explicit_bounded_compatibility():
    schema = declared("set_note", "text", 3)
    del schema["oneOf"][0]["properties"]["data"]["properties"]["text"]["maxLength"]
    error = validate_management(values("set_note", text="a" * 100001), schema)
    assert error["details"]["limit"] == 100000
    assert error["details"]["limit_source"] == "kirabridge_legacy_compatibility"


async def test_catalog_timeout_is_bounded_before_any_mutation(config):
    import asyncio

    config.threaddesk.timeout = 0.01
    manager = ThreadDeskManager(config)
    manager.available_tools = {"thread_manage"}

    async def connect():
        pass

    async def delayed(_):
        await asyncio.sleep(1)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Timed-out preflight cannot send a mutation")

    manager.connect, manager.pool.list_tools, manager.pool.call = connect, delayed, forbidden
    with pytest.raises(Exception) as error:
        await manager.execute(
            {"id": "test", "principal": "local"},
            ThreadDeskManageInput(**values(title="safe")),
            forbidden,
        )
    assert error.value.code == "threaddesk_catalog_timeout"


@pytest.mark.parametrize("details", [None, [], "private contents", 1])
def test_malformed_peer_error_details_do_not_hide_rejection(config, details):
    manager = ThreadDeskManager(config)
    ok, result = manager.decode(
        CallToolResult(
            isError=True, content=[], structuredContent={"code": "tool_error", "details": details}
        ),
        mutation=True,
    )
    assert not ok and result["error"]["code"] == "tool_error"
    assert result["error"]["details"] == {}


@pytest.mark.parametrize(
    "schema",
    [
        [],
        {"oneOf": 3},
        {"oneOf": [None]},
        {"oneOf": [{"properties": []}]},
        {"oneOf": [{"properties": {"action": []}}]},
        {"oneOf": [{"properties": {"action": {"const": "set_note"}, "data": []}}]},
        {"oneOf": [{"properties": {"action": {"const": "set_note"}, "data": {"properties": []}}}]},
        {
            "oneOf": [
                {
                    "properties": {
                        "action": {"const": "set_note"},
                        "data": {"properties": {"text": {"type": [{}]}}},
                    }
                }
            ]
        },
        {"$ref": "https://untrusted.invalid/schema"},
        {"properties": []},
        {"oneOf": [{"$ref": "https://untrusted.invalid/action"}]},
        {
            "oneOf": [
                {
                    "properties": {
                        "action": {"const": "set_note"},
                        "data": {"$ref": "#/definitions/data"},
                    }
                }
            ]
        },
    ],
)
def test_malformed_peer_schema_fails_closed_without_resolving_anything(schema):
    error = validate_management(values("set_note", text="safe"), schema)
    assert error["code"] == "threaddesk_contract_schema"
    assert not error["details"]["request_sent"]


@pytest.mark.parametrize(
    "schema",
    [
        {"metadata": [None] * 4096},
        {"metadata": [[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[None]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]},
    ],
    ids=["node-budget", "depth-budget"],
)
def test_peer_schema_resource_limits_fail_closed(schema):
    assert (
        validate_management(values("set_note", text="safe"), schema)["code"]
        == "threaddesk_contract_schema"
    )


async def test_actual_mcp_create_update_description_boundary_without_truncation(receiver):
    config, _ = receiver
    manager = ThreadDeskManager(config)
    try:
        created = await invoke(
            manager, ThreadDeskManageInput(**values(title="synthetic", description="長" * 10000))
        )
        identifier = created["value"]["thread_id"]
        assert created["value"]["thread"]["description"] == "長" * 10000
        update = values("update", description="🧠" * 10000)
        update.update(
            id=identifier,
            expected_revision=created["value"]["revision"],
            operation_id="description-update",
        )
        changed = await invoke(manager, ThreadDeskManageInput(**update))
        assert changed["success"]
        read = await invoke(
            manager, ThreadDeskReadInput(tool="get_thread", arguments={"id": identifier})
        )
        assert read["value"]["description"] == "🧠" * 10000
    finally:
        await manager.close()


def test_untrusted_schema_field_names_are_not_echoed_as_diagnostics():
    private_field = "private-schema-content"
    schema = declared("set_note", private_field, 3)
    error = validate_management(values("set_note", **{private_field: "too long"}), schema)
    assert error["details"]["field"] == "data"
    assert private_field not in str(error)
