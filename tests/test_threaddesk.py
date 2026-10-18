import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError

from kirabridge.bridge_core.config import ThreadDeskConfig
from kirabridge.bridge_core.models import (
    BridgeError,
    TaskRequest,
    ThreadDeskManageInput,
    ThreadDeskReadInput,
    UncertainExecution,
)


def test_management_cannot_select_a_process_or_workspace():
    with pytest.raises(ValidationError):
        ThreadDeskManageInput(
            operation_id="x",
            action="create",
            expected_revision=0,
            data={"title": "test"},
            workspace="/elsewhere",
        )
    with pytest.raises(ValidationError):
        ThreadDeskReadInput(tool="thread_manage", arguments={})
    with pytest.raises(ValidationError):
        ThreadDeskManageInput(operation_id="x", action="delete", expected_revision=True)


def test_disabled_endpoint_does_not_extend_file_rights(bridge):
    with pytest.raises(BridgeError, match="not enabled"):
        bridge.threaddesk.check_configuration()
    assert not bridge.threaddesk.pool.sessions


def test_operation_receipts_are_namespaced_by_identity_and_workspace(bridge):
    manager = bridge.threaddesk
    first = manager.operation_id("local", "original-op")
    assert first == manager.operation_id("local", "original-op")
    assert first != manager.operation_id("other", "original-op")
    manager.settings.workspace = "/different-operator-store"
    assert first != manager.operation_id("local", "original-op")


def test_read_cannot_smuggle_mutations_or_invalid_flags(bridge):
    for tool, values in [
        ("list_threads", {"include_archived": "true"}),
        ("get_thread", {"id": "abc", "action": "delete"}),
        ("get_thread", {}),
        ("current_thread", {"workspace": "/tmp"}),
    ]:
        with pytest.raises(BridgeError):
            bridge.threaddesk.read_arguments(
                "local", ThreadDeskReadInput(tool=tool, arguments=values)
            )


def test_remote_error_projection_does_not_copy_reflected_error_text(bridge):
    response = CallToolResult(
        isError=True,
        content=[
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "code": "revision_conflict",
                        "error": "synthetic-secret-not-for-output",
                        "details": {
                            "expected_revision": 1,
                            "actual_revision": 2,
                            "unexpected": "synthetic-secret-not-for-output",
                        },
                    }
                ),
            )
        ],
    )
    ok, value = bridge.threaddesk.decode(response, mutation=True)
    assert not ok and value["error"]["details"]["actual_revision"] == 2
    assert "synthetic-secret" not in json.dumps(value)


def test_unparseable_write_response_is_unknown_not_retryable_failure(bridge):
    result = CallToolResult(content=[TextContent(type="text", text="not-json")])
    with pytest.raises(UncertainExecution):
        bridge.threaddesk.decode(result, mutation=True)


@pytest.mark.parametrize(
    "change", [{}, {"operation_id": "foreign"}, {"thread_id": "foreign"}, {"revision": True}]
)
def test_mutation_receipt_is_complete_and_matches_the_actual_operation(bridge, change):
    expected = {"operation_id": "kb_op", "action": "update", "id": "thread_1"}
    value = (
        {
            "operation_id": "kb_op",
            "action": "update",
            "thread_id": "thread_1",
            "revision": 2,
            "duplicate": False,
            "deleted": False,
            "thread": {"id": "thread_1", "revision": 2},
        }
        if change
        else {}
    )
    value.update(change)
    result = CallToolResult(content=[], structuredContent=value)
    with pytest.raises(UncertainExecution):
        bridge.threaddesk.decode(result, mutation=True, expected=expected)


@pytest.mark.skipif(
    not os.environ.get("KIRABRIDGE_TEST_THREADDESK_SOURCE"),
    reason="Pinned external ThreadDesk source required for real integration",
)
async def test_real_threaddesk_roundtrip_and_reconnect(bridge, config, tmp_path):
    workspace = (tmp_path / "thread-workspace").resolve()
    workspace.mkdir(mode=0o700)
    source = Path(os.environ["KIRABRIDGE_TEST_THREADDESK_SOURCE"]).resolve()
    assert (source / "threaddesk/ui/mcp_stdio.py").is_file()
    settings = ThreadDeskConfig(
        enabled=True,
        command=sys.executable,
        args=["-m", "threaddesk.ui.mcp_stdio"],
        workspace=str(workspace),
        source_root=str(source),
    )
    bridge.threaddesk.settings = settings
    for policy in config.principals.values():
        policy.approval_mode = "automatic"
    index = 0

    async def call(operation, arguments, expected="completed"):
        nonlocal index
        index += 1
        tid = f"td-bridge-{index}"
        request = TaskRequest(
            task_id=tid, idempotency_key=tid, operation=operation, arguments=arguments
        )
        bridge.prepare("local", request)
        for _ in range(200):
            task = bridge.task("local", tid)
            if task["state"] not in {"created", "queued", "accepted", "running"}:
                break
            await asyncio.sleep(0.025)
        assert task["state"] == expected, task
        assert task["attempt"] == 1
        return task["result"]["value"]

    async with bridge:
        create = {
            "operation_id": "once-create",
            "action": "create",
            "expected_revision": 0,
            "data": {"title": "Synthetic integration thread"},
        }
        original = await call("threaddesk.manage", create)
        thread_id, revision = original["thread_id"], original["revision"]
        replay = await call("threaddesk.manage", create)
        assert replay["duplicate"] and replay["thread_id"] == thread_id
        conflict = await call(
            "threaddesk.manage", {**create, "data": {"title": "changed"}}, expected="failed"
        )
        assert conflict["error"]["code"] == "operation_conflict"
        for action, data in [
            ("update", {"title": "Updated synthetic thread"}),
            ("set_note", {"text": "Synthetic note"}),
            ("add_file", {"path": "synthetic-reference.txt"}),
            ("organize", {"related_thread_ids": []}),
            ("archive", {}),
            ("unarchive", {}),
        ]:
            changed = await call(
                "threaddesk.manage",
                {
                    "operation_id": "op-" + action,
                    "action": action,
                    "id": thread_id,
                    "expected_revision": revision,
                    "data": data,
                },
            )
            assert changed["revision"] > revision
            revision = changed["revision"]
        stale = await call(
            "threaddesk.manage",
            {
                "operation_id": "stale",
                "action": "update",
                "id": thread_id,
                "expected_revision": 0,
                "data": {"title": "must not overwrite"},
            },
            expected="failed",
        )
        assert stale["error"]["code"] == "revision_conflict"
        read = await call("threaddesk.read", {"tool": "get_thread", "arguments": {"id": thread_id}})
        assert read["title"] == "Updated synthetic thread" and "Synthetic note" in read["notes"]
        await bridge.threaddesk.pool.disconnect("threaddesk")
        receipt = await call(
            "threaddesk.read",
            {"tool": "thread_operation_status", "arguments": {"operation_id": "once-create"}},
        )
        assert receipt["found"] and receipt["result"]["thread_id"] == thread_id
        archived = await call(
            "threaddesk.manage",
            {
                "operation_id": "last-archive",
                "action": "archive",
                "id": thread_id,
                "expected_revision": revision,
                "data": {},
            },
        )
        deleted = await call(
            "threaddesk.manage",
            {
                "operation_id": "delete",
                "action": "delete",
                "id": thread_id,
                "expected_revision": archived["revision"],
                "data": {},
            },
        )
        assert deleted["deleted"]
        config.principals["other"].capabilities.remove("threaddesk.manage")
        with pytest.raises(BridgeError):
            bridge.prepare(
                "other",
                TaskRequest(
                    task_id="denied",
                    idempotency_key="denied",
                    operation="threaddesk.manage",
                    arguments=create,
                ),
            )
