import json

import pytest

from kirabridge.bridge_core.config import Config
from kirabridge.bridge_core.models import ThreadDeskManageInput, ThreadDeskReadInput
from kirabridge.threaddesk_manager import ThreadDeskManager


def _config(tmp_path):
    root = tmp_path / "desk"
    (root / "threads").mkdir(parents=True)
    (root / "whiteboard" / "board-1").mkdir(parents=True)
    (root / "threads" / "board-1.json").write_text(
        json.dumps({"id": "board-1", "title": "Probe"})
    )
    (root / "state.json").write_text(json.dumps({"current_id": "other"}))
    return Config(
        data_dir=str(tmp_path / "state"),
        threaddesk={
            "enabled": True,
            "command": "/usr/bin/true",
            "workspace": str(root),
        },
    )


async def _run(manager, args):
    seen = []

    async def running(evidence):
        seen.append(evidence)

    async def connect():
        raise AssertionError("peer was called")

    manager.connect = connect
    result = await manager.execute({"id": "task-1", "principal": "chatgpt"}, args, running)
    return result, seen


async def test_listed_entries_do_not_call_the_peer(tmp_path):
    manager = ThreadDeskManager(_config(tmp_path))
    args = ThreadDeskReadInput(tool="whiteboard_list", arguments={"id": "board-1"})
    result, seen = await _run(manager, args)
    assert result["success"] is True
    assert result["evidence"]["peer_called"] is False
    assert result["value"]["entries"] == []
    assert seen[0]["tool"] == "whiteboard_list"


async def test_append_operation_roundtrip_and_duplicate(tmp_path):
    config = _config(tmp_path)
    manager = ThreadDeskManager(config)
    args = ThreadDeskManageInput(
        operation_id="probe-op-1",
        action="whiteboard_append",
        id="board-1",
        expected_revision=0,
        data={
            "entry_type": "note",
            "content": "Ueber die Operation",
            "actor": "ChatGPT",
            "actor_type": "chatgpt",
        },
    )
    created, _ = await _run(manager, args)
    again, _ = await _run(manager, args)
    assert created["value"]["duplicate"] is False
    assert again["value"]["duplicate"] is True
    assert again["value"]["id"] == created["value"]["id"]
    read_args = ThreadDeskReadInput(
        tool="whiteboard_get",
        arguments={"id": "board-1", "entry_id": created["value"]["id"]},
    )
    read, _ = await _run(manager, read_args)
    assert read["value"]["entry"]["content"] == "Ueber die Operation"
    state = json.loads((tmp_path / "desk" / "state.json").read_text())
    assert state["current_id"] == "other"


def test_catalog_schema_names_the_whiteboard_tools():
    read = str(ThreadDeskReadInput.model_json_schema())
    manage = str(ThreadDeskManageInput.model_json_schema())
    assert "whiteboard_list" in read and "whiteboard_get" in read
    assert "whiteboard_append" in manage
    with pytest.raises(Exception):
        ThreadDeskReadInput(tool="not_a_tool", arguments={})
