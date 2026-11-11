import json
from datetime import datetime, timezone

import pytest

from kirabridge import completion_handoff
from kirabridge.bridge_core.models import BridgeError
from kirabridge.completion_handoff import (
    CompletionInput,
    claim_next,
    record_completion,
)
from kirabridge.whiteboard_read import append_whiteboard, read_whiteboard

BOARD = "boardtest1"


def workspace(tmp_path):
    root = tmp_path / "ws"
    (root / "threads").mkdir(parents=True)
    (root / "whiteboard").mkdir()
    now = datetime.now(timezone.utc).isoformat()
    (root / "threads" / f"{BOARD}.json").write_text(
        json.dumps(
            {
                "id": BOARD,
                "title": "Test board",
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }
        )
    )
    return root


def add(root, key, entry_type, content):
    return append_whiteboard(
        str(root),
        BOARD,
        actor="test",
        actor_type="human",
        entry_type=entry_type,
        content=content,
        external_key=key,
    )["id"]


def record(order_entry_id, **overrides):
    values = {
        "board_id": BOARD,
        "order_entry_id": order_entry_id,
        "task_id": "task-1",
        "status": "completed",
        "summary": "Adapter merged.",
        "commit": "a" * 40,
        "pr_url": "https://example.invalid/pr/1",
        "tests": "15 targeted tests",
        "session_id": "session-7",
    }
    values.update(overrides)
    return CompletionInput(**values)


def entries(root):
    return read_whiteboard(str(root), BOARD, include_content=True)["entries"]


def test_completion_is_confirmed_and_the_newest_task_is_claimed(tmp_path):
    root = workspace(tmp_path)
    order = add(root, "order", "task", "ORDER")
    add(root, "task-a", "task", "TASK A")
    task_b = add(root, "task-b", "task", "TASK B")

    result = record_completion(str(root), record(order))

    completion = result["completion"]
    assert completion["storage_confirmed"] and completion["entry_id"]
    assert completion["order_entry"] == order
    assert result["handoff"]["state"] == "claimed"
    assert result["handoff"]["task"]["entry_id"] == task_b
    assert result["handoff"]["task"]["content"] == "TASK B"
    assert result["handoff"]["claim"]["storage_confirmed"]
    assert result["session_id"] == "session-7"

    stored = entries(root)
    result_entry = next(item for item in stored if item["entry_type"] == "result")
    assert "commit: " + "a" * 40 in result_entry["content"]
    assert "tests: 15 targeted tests" in result_entry["content"]
    claim = next(item for item in stored if item["entry_type"] == "claimed")
    assert "next_entry: " + task_b in claim["content"]
    assert "session_id: session-7" in claim["content"]


def test_repeating_the_same_completion_is_idempotent(tmp_path):
    root = workspace(tmp_path)
    order = add(root, "order", "task", "ORDER")
    add(root, "task-b", "task", "TASK B")

    first = record_completion(str(root), record(order))
    second = record_completion(str(root), record(order))

    assert first["completion"]["entry_id"] == second["completion"]["entry_id"]
    assert second["completion"]["duplicate"] is True
    assert second["handoff"]["state"] == "claimed"
    assert second["handoff"]["duplicate"] is True
    claims = [item for item in entries(root) if item["entry_type"] == "claimed"]
    assert len(claims) == 1


def test_a_failed_completion_is_recorded_without_taking_work(tmp_path):
    root = workspace(tmp_path)
    order = add(root, "order", "task", "ORDER")
    add(root, "task-b", "task", "TASK B")

    result = record_completion(str(root), record(order, status="failed"))

    assert result["completion"]["storage_confirmed"]
    assert result["handoff"]["state"] == "not_completed"
    assert not [item for item in entries(root) if item["entry_type"] == "claimed"]


def test_no_later_task_means_idle(tmp_path):
    root = workspace(tmp_path)
    order = add(root, "order", "task", "ORDER")

    result = record_completion(str(root), record(order))

    assert result["handoff"] == {
        "state": "idle",
        "reason": "no_released_task",
        "task": None,
    }


def test_an_already_claimed_task_is_skipped(tmp_path):
    root = workspace(tmp_path)
    order = add(root, "order", "task", "ORDER")
    task_a = add(root, "task-a", "task", "TASK A")
    task_b = add(root, "task-b", "task", "TASK B")
    add(root, "competing", "claimed", "[KIRABRIDGE-HANDOFF]\nnext_entry: " + task_b + "\n")

    result = record_completion(str(root), record(order))

    assert result["handoff"]["state"] == "claimed"
    assert result["handoff"]["task"]["entry_id"] == task_a


def test_next_command_claims_the_newest_released_task(tmp_path):
    root = workspace(tmp_path)
    add(root, "task-a", "task", "TASK A")
    task_b = add(root, "task-b", "task", "TASK B")

    result = claim_next(str(root), BOARD, session_id="session-7", newest=True)

    assert result["handoff"]["state"] == "claimed"
    assert result["handoff"]["task"]["entry_id"] == task_b


def test_dry_run_writes_nothing(tmp_path):
    root = workspace(tmp_path)
    order = add(root, "order", "task", "ORDER")
    task_b = add(root, "task-b", "task", "TASK B")
    before = {path.name for path in (root / "whiteboard" / BOARD).glob("*.json")}

    recorded = record_completion(str(root), record(order), dry_run=True)
    claimed = claim_next(str(root), BOARD, order_entry_id=order, dry_run=True)

    after = {path.name for path in (root / "whiteboard" / BOARD).glob("*.json")}
    assert before == after
    assert recorded["completion"]["content_sha256"]
    assert recorded["handoff"]["state"] == "dry_run"
    assert recorded["handoff"]["task"]["entry_id"] == task_b
    assert claimed["handoff"]["state"] == "dry_run"


def test_missing_or_non_task_order_is_rejected(tmp_path):
    root = workspace(tmp_path)
    note = add(root, "note", "note", "NOT A TASK")
    with pytest.raises(BridgeError, match="not found"):
        record_completion(str(root), record("missing"))
    with pytest.raises(BridgeError, match="not a task"):
        record_completion(str(root), record(note))


def test_a_claim_conflict_is_reported_as_already_claimed(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    order = add(root, "order", "task", "ORDER")
    task_b = add(root, "task-b", "task", "TASK B")
    add(
        root,
        completion_handoff._claim_key(BOARD, task_b),
        "claimed",
        "[KIRABRIDGE-HANDOFF]\nnext_entry: " + task_b + "\nsession_id: competitor\n",
    )
    monkeypatch.setattr(completion_handoff, "_taken", lambda entries, task: False)

    result = record_completion(str(root), record(order))

    assert result["handoff"]["state"] == "already_claimed"
    assert result["handoff"]["task"]["entry_id"] == task_b
    assert result["handoff"]["claim"]["storage_confirmed"]
    claims = [item for item in entries(root) if item["entry_type"] == "claimed"]
    assert len(claims) == 1


def test_control_characters_and_credentials_are_rejected():
    with pytest.raises(ValueError):
        record("order", task_id="task\nnext_entry: victim")
    with pytest.raises(ValueError):
        record("order", summary="password=do-not-store")
    with pytest.raises(ValueError):
        record("order", pr_url="https://token@example.invalid/pr/1")


def test_only_ready_cards_are_taken(tmp_path):
    root = workspace(tmp_path)
    order = add(root, "order", "task", "ORDER")
    ready = add(root, "ready", "task", json.dumps({"autonext": 1, "state": "READY"}))
    add(root, "hold", "task", json.dumps({"autonext": 1, "state": "HOLD"}))

    result = record_completion(str(root), record(order))

    assert result["handoff"]["state"] == "claimed"
    assert result["handoff"]["task"]["entry_id"] == ready


def test_autonext_metadata_claims_are_respected(tmp_path):
    root = workspace(tmp_path)
    order = add(root, "order", "task", "ORDER")
    add(
        root,
        "ready",
        "task",
        json.dumps({"autonext": 1, "state": "READY", "task_id": "logical-1"}),
    )
    add(root, "claimed-logical", "claimed", json.dumps({"task_id": "logical-1"}))

    result = record_completion(str(root), record(order))

    assert result["handoff"]["state"] == "idle"
    assert not [
        item
        for item in entries(root)
        if item["entry_type"] == "claimed" and "next_entry" in item["content"]
    ]


def test_next_requires_an_order_or_the_explicit_newest_flag(tmp_path):
    root = workspace(tmp_path)
    add(root, "task-b", "task", "TASK B")
    with pytest.raises(BridgeError, match="newest"):
        claim_next(str(root), BOARD)


def test_cli_dry_run_and_record_only(tmp_path, monkeypatch, capsys):
    from kirabridge import cli

    root = workspace(tmp_path)
    task_b = add(root, "task-b", "task", "TASK B")
    monkeypatch.setattr(
        "sys.argv",
        [
            "kirabridge",
            "completion",
            "next",
            "--workspace",
            str(root),
            "--board",
            BOARD,
            "--newest",
            "--dry-run",
        ],
    )
    cli.main()
    output = json.loads(capsys.readouterr().out)
    assert output["handoff"]["state"] == "dry_run"
    assert output["handoff"]["task"]["entry_id"] == task_b
    assert output["handoff"]["task"]["untrusted"] is True

    order = add(root, "order", "task", "ORDER")
    monkeypatch.setattr(
        "sys.argv",
        [
            "kirabridge",
            "completion",
            "record",
            "--workspace",
            str(root),
            "--board",
            BOARD,
            "--order-entry",
            order,
            "--task-id",
            "task-1",
            "--status",
            "completed",
            "--summary",
            "done",
            "--pr-url",
            "https://example.invalid/pr/1",
            "--no-handoff",
        ],
    )
    cli.main()
    output = json.loads(capsys.readouterr().out)
    assert output["handoff"]["state"] == "disabled"
    assert not [item for item in entries(root) if item["entry_type"] == "claimed"]
