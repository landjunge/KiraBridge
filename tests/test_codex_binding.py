# Imported pytest fixture is provided through dependency injection.
# ruff: noqa: F811
import asyncio
import os
import threading

import pytest
from pydantic import ValidationError
from test_codex_state import record, rollout, write  # noqa: F401
from test_visible_handoff import visible  # noqa: F401

from kirabridge.bridge_core.config import VisibleTerminalBinding
from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.codex_state import CodexTurnState

THREAD = "12345678-1234-1234-1234-123456789abc"
ROLLOUT = "/explicitly/trusted/session.jsonl"


@pytest.mark.parametrize(
    "partial",
    [{"codex_thread_id": THREAD}, {"codex_rollout_path": ROLLOUT}],
)
def test_config_refuses_incomplete_protocol_binding_pair(partial):
    with pytest.raises(ValidationError, match="bound together"):
        VisibleTerminalBinding(
            pane_id="terminal:101:ttys002",
            expected_pid=124,
            agent_pid=457,
            ready_pattern=r"(?m)^›\s*$",
            **partial,
        )


@pytest.mark.parametrize("protocol", [{"state": "unknown"}, {"state": "unsupported"}, {}])
async def test_bound_unknown_protocol_cannot_release_codex_input(visible, monkeypatch, protocol):
    bridge, transport = visible
    binding = bridge.config.visible_handoffs.bindings["codex"]
    binding.codex_thread_id, binding.codex_rollout_path = THREAD, ROLLOUT
    transport["text"] = "›\n  GPT-6.1-Sol high · ~\n  ← for agents · ? for shortcuts\n"
    calls = []

    async def read(path, thread_id):
        calls.append((path, thread_id))
        return protocol

    monkeypatch.setattr(bridge.visible_handoffs.codex_state, "read", read)
    with pytest.raises(BridgeError) as exc:
        await bridge.visible_handoffs.check_target("chatgpt", "codex", binding, ready=True)
    assert exc.value.code == "visible_target_unknown"
    assert calls == [(ROLLOUT, THREAD)] and transport["calls"] == []


async def test_wrong_cli_pid_blocks_before_protocol_can_claim_idle(visible, monkeypatch):
    bridge, transport = visible
    binding = bridge.config.visible_handoffs.bindings["codex"]
    binding.codex_thread_id, binding.codex_rollout_path = THREAD, ROLLOUT
    transport["text"] = "›"

    async def selected(*args):
        return {"processes": [{"pid": binding.agent_pid + 1, "name": "codex"}]}

    async def forbidden(*args):
        raise AssertionError("An incorrect CLI PID cannot authorize reading another thread")

    monkeypatch.setattr(bridge.sessions, "selected", selected)
    monkeypatch.setattr(bridge.visible_handoffs.codex_state, "read", forbidden)
    with pytest.raises(BridgeError) as exc:
        await bridge.visible_handoffs.check_target("chatgpt", "codex", binding, ready=True)
    assert exc.value.code == "visible_target_changed" and transport["calls"] == []


async def test_cli_pid_changed_during_observation_is_a_domain_error(visible, monkeypatch):
    bridge, transport = visible
    binding = bridge.config.visible_handoffs.bindings["codex"]
    transport["text"] = "›"
    original = bridge.sessions.selected
    reads = 0

    async def selected(*args):
        nonlocal reads
        reads += 1
        if reads == 2:
            return {"processes": [{"pid": binding.agent_pid + 1, "name": "codex"}]}
        return await original(*args)

    monkeypatch.setattr(bridge.sessions, "selected", selected)
    with pytest.raises(BridgeError) as exc:
        await bridge.visible_handoffs.check_target("chatgpt", "codex", binding, ready=True)
    assert exc.value.code == "visible_target_changed" and transport["calls"] == []


async def test_body_rewrite_during_scan_never_leaves_reusable_idle_cursor(rollout, monkeypatch):
    root, path, _ = rollout
    reader = CodexTurnState(root)
    write(path, record("task_started"), record("task_complete"), append=True)
    original = reader._event
    rewritten = False

    def rewrite_after_completed_was_parsed(cursor, item):
        nonlocal rewritten
        original(cursor, item)
        if item.get("payload", {}).get("type") == "task_complete" and not rewritten:
            rewritten = True
            raw = path.read_bytes()
            changed = raw.replace(b"task_complete", b"task_mystery!")
            assert len(changed) == len(raw)
            path.write_bytes(changed)

    monkeypatch.setattr(reader, "_event", rewrite_after_completed_was_parsed)
    assert (await reader.read(str(path), "thread-one"))["state"] == "unknown"
    result = await reader.read(str(path), "thread-one")
    assert result["state"] == "unknown", "A changed body invalidates the previous idle cursor"


async def test_truncate_during_scan_invalidates_the_cached_turn(rollout, monkeypatch):
    root, path, header = rollout
    reader = CodexTurnState(root)
    write(path, record("task_started"), record("task_complete"), append=True)
    original = reader._event
    truncated = False

    def truncate_after_completion(cursor, item):
        nonlocal truncated
        original(cursor, item)
        if item.get("payload", {}).get("type") == "task_complete" and not truncated:
            truncated = True
            write(path, header)

    monkeypatch.setattr(reader, "_event", truncate_after_completion)
    assert (await reader.read(str(path), "thread-one"))["state"] == "unknown"
    # Restoring the old byte length cannot rehabilitate a cursor invalidated by truncation.
    write(path, record("task_started"), record("task_complete"), append=True)
    result = await reader.read(str(path), "thread-one")
    assert result["state"] == "unknown", "The already-scanned turn belongs to discarded bytes"


async def test_cancelled_scan_and_next_reader_do_not_mutate_cursor_concurrently(
    rollout, monkeypatch
):
    root, path, _ = rollout
    reader = CodexTurnState(root)
    write(path, record("task_started"), append=True)
    entered = threading.Event()
    release = threading.Event()
    second_attempt = threading.Event()
    original_locked, original_read = reader._read_locked, reader._read
    counts = {"active": 0, "maximum": 0, "attempts": 0}

    def locked(*args):
        counts["active"] += 1
        counts["maximum"] = max(counts["maximum"], counts["active"])
        try:
            if not entered.is_set():
                entered.set()
                assert release.wait(3), "The test must release the bounded reader"
            return original_locked(*args)
        finally:
            counts["active"] -= 1

    def attempted(*args):
        counts["attempts"] += 1
        if counts["attempts"] == 2:
            second_attempt.set()
        return original_read(*args)

    monkeypatch.setattr(reader, "_read_locked", locked)
    monkeypatch.setattr(reader, "_read", attempted)
    first = asyncio.create_task(reader.read(str(path), "thread-one"))
    second = None
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(reader.read(str(path), "thread-one"))
        assert await asyncio.to_thread(second_attempt.wait, 2)
        assert counts["active"] == 1
    finally:
        release.set()
        if second:
            result = await asyncio.wait_for(second, 3)
    assert result["state"] == "working" and counts["maximum"] == 1


async def test_bound_fifo_is_rejected_without_blocking_all_future_reads(rollout):
    root, path, _ = rollout
    fifo = root / "not-a-rollout.jsonl"
    os.mkfifo(fifo)
    reader = CodexTurnState(root)
    try:
        result = await asyncio.wait_for(reader.read(str(fifo), "thread-one"), 1)
        assert result["state"] == "unknown" and result["reason"] == "session_not_regular"
    finally:
        # If nonblocking open regresses, release the timed-out reader thread so
        # the negative test fails cleanly rather than hanging pytest shutdown.
        try:
            writer = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        except OSError:
            pass
        else:
            os.close(writer)
    write(path, record("task_started"), append=True)
    result = await asyncio.wait_for(reader.read(str(path), "thread-one"), 1)
    assert result["state"] == "working"
