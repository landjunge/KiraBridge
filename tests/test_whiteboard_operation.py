import json

import pytest
from pydantic import ValidationError

from kirabridge.bridge_core.config import Config
from kirabridge.bridge_core.models import ThreadDeskManageInput, ThreadDeskReadInput
from kirabridge.threaddesk_manager import ThreadDeskManager


def _config(tmp_path):
    root = tmp_path / "desk"
    (root / "threads").mkdir(parents=True)
    (root / "whiteboard" / "board-1").mkdir(parents=True)
    (root / "threads" / "board-1.json").write_text(json.dumps({"id": "board-1", "title": "Probe"}))
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


async def test_content_page_returns_one_ordered_slice(tmp_path, monkeypatch):
    import kirabridge.whiteboard_read as reads

    monkeypatch.setattr(reads, "_PAGE_CONTENT_CHARS", 5)
    config = _config(tmp_path)
    board = tmp_path / "desk" / "whiteboard" / "board-1"
    for ordinal, text in ((1, "abcd"), (2, "zzzzzz"), (3, "end")):
        (board / f"e{ordinal}.json").write_text(
            json.dumps(
                {
                    "id": f"e{ordinal}",
                    "ordinal": ordinal,
                    "entry_type": "note",
                    "actor": "Grok",
                    "created_at": "2026-10-28T00:00:00Z",
                    "content": text,
                }
            )
        )
    manager = ThreadDeskManager(config)
    listed, _ = await _run(
        manager,
        ThreadDeskReadInput(tool="whiteboard_list", arguments={"id": "board-1"}),
    )
    assert "content" not in listed["value"]["entries"][0]
    page, _seen = await _run(
        manager,
        ThreadDeskReadInput(
            tool="whiteboard_list",
            arguments={"id": "board-1", "include_content": True, "offset": 0, "limit": 10},
        ),
    )
    assert page["evidence"]["peer_called"] is False
    assert page["value"]["total"] == 3
    assert [item["id"] for item in page["value"]["entries"]] == ["e1"]
    assert page["value"]["entries"][0]["content"] == "abcd"
    assert page["value"]["next_offset"] == 1
    assert page["value"]["complete"] is False
    rest, _ = await _run(
        manager,
        ThreadDeskReadInput(
            tool="whiteboard_list",
            arguments={
                "id": "board-1",
                "include_content": True,
                "offset": 1,
                "limit": 10,
            },
        ),
    )
    assert [item["id"] for item in rest["value"]["entries"]] == ["e2"]
    assert rest["value"]["next_offset"] == 2
    last, _ = await _run(
        manager,
        ThreadDeskReadInput(
            tool="whiteboard_list",
            arguments={
                "id": "board-1",
                "include_content": True,
                "offset": 2,
                "limit": 10,
            },
        ),
    )
    assert [item["content"] for item in last["value"]["entries"]] == ["end"]
    assert last["value"]["complete"] is True
    assert json.loads((tmp_path / "desk" / "state.json").read_text())["current_id"] == "other"


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
    with pytest.raises(ValidationError):
        ThreadDeskReadInput(tool="not_a_tool", arguments={})
