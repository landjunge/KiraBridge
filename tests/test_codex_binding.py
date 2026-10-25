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
    from kirabridge.session_manager import SessionInput, SessionManager

    bridge, transport = visible
    binding = bridge.config.visible_handoffs.bindings["codex"]
    transport["text"] = "›"
    original_selected, original_read = bridge.sessions.selected, bridge.sessions.read
    reads, identities = [], []
    changed = False

    async def selected(*args):
        row = await original_selected(*args)
        reads.append(args)
        return {
            **row,
            "transport": "terminal_app",
            "tty": "/dev/ttys002",
            "processes": [
                {"pid": binding.expected_pid, "ppid": 900, "name": "zsh", "image": "/bin/zsh"},
                {
                    "pid": binding.agent_pid + int(changed),
                    "ppid": binding.expected_pid,
                    "name": "codex",
                    "image": "/bin/codex",
                },
            ],
        }

    async def identity(pid, **kwargs):
        identities.append(pid)
        parent, image = (
            (900, "/bin/zsh")
            if pid == binding.expected_pid
            else (binding.expected_pid, "/bin/codex")
        )
        return f"{os.getuid()} ttys002 Sun Oct 25 12:00:00 2026 {parent} {image}"

    async def read_then_replace_agent(*args, **kwargs):
        nonlocal changed
        output = await original_read(*args, **kwargs)
        changed = True  # Actual replacement after observation, independent of probe count.
        return output

    async def forbidden_transport(*args, **kwargs):
        raise AssertionError("Changed PID must be rejected before any native read or input")

    monkeypatch.setattr(bridge.sessions, "selected", selected)
    monkeypatch.setattr(bridge.sessions, "read", read_then_replace_agent)
    monkeypatch.setattr(bridge.sessions.terminal_app, "process_identity", identity)
    monkeypatch.setattr(bridge.sessions.terminal_app, "read", forbidden_transport)
    monkeypatch.setattr(bridge.sessions.terminal_app, "insert", forbidden_transport)
    async with bridge.sessions.agent_selection("chatgpt", "codex", binding):
        await bridge.visible_handoffs.check_target("chatgpt", "codex", binding, ready=True)
        # Readiness is an observation, not input authority. Scoped reads share one
        # snapshot; the next input boundary must independently select the live PID.
        assert len(reads) == 2 and changed and not transport["calls"]
        with pytest.raises(BridgeError) as exc:
            await SessionManager.insert(
                bridge.sessions,
                "chatgpt",
                SessionInput(
                    pane_id=binding.pane_id,
                    expected_pid=binding.expected_pid,
                    text="MUST_NOT_BE_INSERTED",
                    submit=False,
                ),
            )
        assert exc.value.code == "visible_target_changed"
    assert len(reads) == 3 and set(identities) == {binding.expected_pid, binding.agent_pid}
    assert transport["calls"] == [] and bridge.sessions.current_selection() is None


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
            before = path.stat()
            raw = path.read_bytes()
            changed = raw.replace(b"task_complete", b"task_mystery!")
            assert len(changed) == len(raw)
            path.write_bytes(changed)
            # Reproduce equal/coarse filesystem timestamps deterministically.
            # The guard must inspect consumed bytes, not rely on clock progress.
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))

    monkeypatch.setattr(reader, "_event", rewrite_after_completed_was_parsed)
    changed = await reader.read(str(path), "thread-one")
    assert changed["state"] == "unknown" and changed["reason"] == "session_rewritten"
    result = await reader.read(str(path), "thread-one")
    assert result["state"] == "unknown", "A changed body invalidates the previous idle cursor"
    assert result["reason"] == "session_rewritten"


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


async def test_failed_unbuffered_verification_never_reuses_the_parsed_idle_turn(
    rollout, monkeypatch
):
    root, path, _ = rollout
    reader = CodexTurnState(root)
    write(path, record("task_started"), record("task_complete"), append=True)
    original = os.pread

    def unavailable(*args):
        raise OSError("Synthetic verification failure")

    monkeypatch.setattr(os, "pread", unavailable)
    assert (await reader.read(str(path), "thread-one"))["state"] == "unknown"
    monkeypatch.setattr(os, "pread", original)
    result = await reader.read(str(path), "thread-one")
    assert result["state"] == "unknown"
    assert result["reason"] == "session_verification_incomplete"


@pytest.mark.parametrize("premature_eof", [False, True], ids=["short-read", "incomplete-read"])
async def test_unbuffered_verification_handles_short_reads_and_rejects_incomplete_bytes(
    rollout, monkeypatch, premature_eof
):
    root, path, _ = rollout
    reader = CodexTurnState(root)
    write(path, record("task_started"), record("task_complete"), append=True)
    header_size = len(path.read_bytes().splitlines(keepends=True)[0])
    original = os.pread

    def short_read(fd, size, offset):
        if premature_eof and offset >= header_size:
            return b""
        return original(fd, min(size, 7), offset)

    monkeypatch.setattr(os, "pread", short_read)
    result = await reader.read(str(path), "thread-one")
    assert result["state"] == ("unknown" if premature_eof else "idle")
    monkeypatch.setattr(os, "pread", original)
    if premature_eof:
        assert result["reason"] == "session_rewritten"
        assert (await reader.read(str(path), "thread-one"))["state"] == "unknown"
