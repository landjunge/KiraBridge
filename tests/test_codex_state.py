import json

import pytest

from kirabridge.platform_adapters.codex_state import CodexTurnState


def record(kind, turn="turn-one"):
    return {"type": "event_msg", "payload": {"type": kind, "turn_id": turn}}


def write(path, *records, append=False):
    with path.open("a" if append else "w") as stream:
        for item in records:
            stream.write(json.dumps(item) + "\n")


@pytest.fixture
def rollout(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir()
    path = root / "explicitly-bound.jsonl"
    header = {
        "type": "session_meta",
        "payload": {"id": "thread-one", "originator": "codex-tui", "source": "vscode"},
    }
    write(path, header)
    return root, path, header


@pytest.mark.parametrize(
    "end,reason", [("task_complete", "turn_completed"), ("turn_aborted", "turn_interrupted")]
)
async def test_matching_turn_start_and_terminal_event(rollout, end, reason):
    root, path, _ = rollout
    reader = CodexTurnState(root)
    write(path, record("task_started"), append=True)
    assert (await reader.read(str(path), "thread-one"))["state"] == "working"
    write(path, record(end), append=True)
    assert await reader.read(str(path), "thread-one") == {
        "state": "idle",
        "reason": reason,
        "last_event": end,
        "turn_id": "turn-one",
    }


async def test_requires_exact_header_and_explicit_binding(rollout):
    root, path, _ = rollout
    reader = CodexTurnState(root)
    write(path, record("task_started"), record("task_complete"), append=True)
    assert (await reader.read(None, "thread-one"))["state"] == "unknown"
    assert (await reader.read(str(path), "wrong-thread"))["reason"] == "session_header_mismatch"
    assert (await reader.read(str(path), "thread-one"))["state"] == "idle"


async def test_unmatched_complete_and_unrecognized_terminal_event_fail_closed(rollout):
    root, path, _ = rollout
    reader = CodexTurnState(root)
    write(path, record("task_started"), record("task_complete", "other-turn"), append=True)
    assert (await reader.read(str(path), "thread-one"))["state"] == "unknown"
    write(path, record("task_started", "next"), record("turn_mystery", "next"), append=True)
    assert (await reader.read(str(path), "thread-one"))["reason"] == "unsupported_turn_event"


async def test_tool_output_and_user_text_cannot_finish_turn(rollout):
    root, path, _ = rollout
    reader = CodexTurnState(root)
    fake = {
        "type": "response_item",
        "payload": {"type": "function_call_output", "output": record("task_complete")},
    }
    write(
        path,
        record("task_started"),
        fake,
        {
            "type": "event_msg",
            "payload": {"type": "user_message", "message": json.dumps(record("task_complete"))},
        },
        append=True,
    )
    result = await reader.read(str(path), "thread-one")
    assert result["state"] == "working" and "output" not in result


async def test_partial_append_is_unknown_until_entire_event_arrives(rollout):
    root, path, _ = rollout
    reader = CodexTurnState(root)
    write(path, record("task_started"), append=True)
    assert (await reader.read(str(path), "thread-one"))["state"] == "working"
    line = json.dumps(record("task_complete"))
    with path.open("a") as stream:
        stream.write(line[:20])
    assert (await reader.read(str(path), "thread-one"))["reason"] == "session_partial_line"
    with path.open("a") as stream:
        stream.write(line[20:] + "\n")
    assert (await reader.read(str(path), "thread-one"))["state"] == "idle"


@pytest.mark.parametrize(
    "change,reason",
    [
        ("truncate", "session_truncated"),
        ("replace", "session_replaced"),
        ("header", "session_header_changed"),
    ],
)
async def test_changed_source_does_not_reuse_previously_idle_state(rollout, change, reason):
    root, path, header = rollout
    reader = CodexTurnState(root)
    write(path, record("task_started"), record("task_complete"), append=True)
    assert (await reader.read(str(path), "thread-one"))["state"] == "idle"
    if change == "truncate":
        write(path, header)
    elif change == "replace":
        replacement = root / "replacement"
        write(replacement, header, record("task_started"), record("task_complete"))
        replacement.replace(path)
    else:
        header["payload"]["extra"] = "changed-header-more-bytes"
        write(path, header, record("task_started"), record("task_complete"))
    result = await reader.read(str(path), "thread-one")
    assert result["state"] == "unknown" and result["reason"] == reason
    assert (await reader.read(str(path), "thread-one"))["state"] == "unknown"


async def test_bounds_incremental_scan_and_never_accepts_unscanned_end(rollout):
    root, path, _ = rollout
    reader = CodexTurnState(root, max_bytes=512, max_line_bytes=256)
    write(
        path,
        record("task_started"),
        *[{"type": "response_item", "payload": "x" * 120}] * 8,
        record("task_complete"),
        append=True,
    )
    result = await reader.read(str(path), "thread-one")
    assert result["state"] == "unknown" and result["reason"] == "session_scan_incomplete"
    for _ in range(20):
        result = await reader.read(str(path), "thread-one")
        if result["state"] != "unknown":
            break
    assert result["state"] == "idle"


async def test_reconnect_recovers_turn_across_large_non_event_record(rollout):
    root, path, _ = rollout
    write(
        path,
        record("task_started"),
        {"type": "response_item", "payload": "x" * 1_500_000},
        record("task_complete"),
        append=True,
    )

    # A new reader has no in-memory cursor, matching a KiraBridge reconnect.
    result = await CodexTurnState(root).read(str(path), "thread-one")

    assert result["state"] == "idle"
    assert result["reason"] == "turn_completed"


async def test_oversized_line_parse_error_and_missing_turn_id_fail_closed(rollout):
    root, path, header = rollout
    reader = CodexTurnState(root, max_bytes=512, max_line_bytes=256)
    write(
        path,
        record("task_started"),
        {"type": "response_item", "payload": "x" * 400},
        record("task_complete"),
        append=True,
    )
    assert (await reader.read(str(path), "thread-one"))["reason"] == "session_line_limit"
    write(path, header, {"type": "event_msg", "payload": {"type": "task_complete"}})
    assert (await CodexTurnState(root).read(str(path), "thread-one"))["reason"] == "turn_id_missing"
    with path.open("a") as stream:
        stream.write("not-json\n")
    assert (await CodexTurnState(root).read(str(path), "thread-one"))[
        "reason"
    ] == "session_parse_error"


async def test_outside_root_and_symlink_escape_are_rejected(rollout, tmp_path):
    root, _, header = rollout
    outside = tmp_path / "outside.jsonl"
    write(outside, header, record("task_started"), record("task_complete"))
    alias = root / "alias.jsonl"
    alias.symlink_to(outside)
    reader = CodexTurnState(root)
    for path in [outside, alias]:
        assert (await reader.read(str(path), "thread-one"))["reason"] == "session_path_outside_root"


async def test_concurrent_append_during_scan_returns_unknown_then_reads_new_event(
    rollout, monkeypatch
):
    root, path, _ = rollout
    reader = CodexTurnState(root)
    write(path, record("task_started"), record("task_complete"), append=True)
    original = reader._event
    appended = False

    def append_during_scan(cursor, item):
        nonlocal appended
        original(cursor, item)
        if item.get("payload", {}).get("type") == "task_complete" and not appended:
            appended = True
            write(path, record("task_started", "new-turn"), append=True)

    monkeypatch.setattr(reader, "_event", append_during_scan)
    assert (await reader.read(str(path), "thread-one"))["reason"] == "session_changed_during_read"
    result = await reader.read(str(path), "thread-one")
    assert result["state"] == "working" and result["turn_id"] == "new-turn"


async def test_equal_size_rewrite_cannot_preserve_idle_result(rollout):
    root, path, _ = rollout
    reader = CodexTurnState(root)
    write(path, record("task_started"), record("task_complete"), append=True)
    assert (await reader.read(str(path), "thread-one"))["state"] == "idle"
    import os

    before = path.stat()
    raw = path.read_bytes().replace(b"task_complete", b"task_mystery!")
    assert len(raw) == before.st_size
    path.write_bytes(raw)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
    assert (await reader.read(str(path), "thread-one"))["reason"] == "session_rewritten"
