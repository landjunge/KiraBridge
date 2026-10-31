import asyncio
import base64
import hashlib
import os
import sqlite3
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from kirabridge.bridge_core.models import BridgeError, TerminalInput, UncertainExecution
from kirabridge.process_output_store import OutputRangeInput, ProcessOutputStore
from kirabridge.read_query import ReadQuery, read_query
from kirabridge.task_manager.store import Store
from kirabridge.terminal_manager import TerminalManager


@pytest.fixture
def output(tmp_path):
    store = Store(tmp_path / "state" / "bridge.sqlite3")
    streams = ProcessOutputStore(tmp_path / "state" / "output", store)
    yield streams
    store.close()


def test_exact_output_pages_hashes_owner_binding_and_restart(output):
    payload = b"a\xff\x00" + "🙂你好".encode() + b"z" * 43
    output.start("owner", "task")
    output.append("owner", "task", "stdout", payload)
    output.append("owner", "task", "stderr", b"separate\x80")
    output.finish("owner", "task", complete=True)
    database = output.store.db.execute("PRAGMA database_list").fetchone()[2]
    output.store.close()
    output.store = Store(__import__("pathlib").Path(database))
    restarted = ProcessOutputStore(output.root, output.store)
    position, chunks, identity = 0, [], None
    while True:
        page = restarted.read(
            "owner", "task", offset=position, max_bytes=4, expected_identity=identity
        )
        raw = base64.b64decode(page["data_base64"])
        assert page["content_sha256"] == hashlib.sha256(raw).hexdigest()
        assert page["stream_complete"] and page["capture_state"] == "complete"
        assert page["stream_sha256"] == hashlib.sha256(payload).hexdigest()
        identity = page["identity"]
        chunks.append(raw)
        position = page["next_offset"]
        if page["eof"]:
            break
    assert b"".join(chunks) == payload
    assert (
        restarted.read("owner", "task", "stderr", encoding="base64")["data_base64"]
        == base64.b64encode(b"separate\x80").decode()
    )
    with pytest.raises(BridgeError) as exc:
        restarted.read("other", "task")
    assert exc.value.code == "not_found"
    with pytest.raises(BridgeError) as exc:
        restarted.start("owner", "task")
    assert exc.value.code == "process_output_exists"


def test_live_eof_is_not_completion_and_restart_does_not_replay(output):
    output.start("owner", "task")
    output.append("owner", "task", "stdout", b"prefix")
    page = output.read("owner", "task")
    assert page["eof"] and not page["stream_complete"] and page["capture_state"] == "recording"
    restarted = ProcessOutputStore(output.root, output.store)
    assert restarted.read("owner", "task")["capture_state"] == "incomplete"
    output.append("owner", "task", "stdout", b"suffix")
    with pytest.raises(BridgeError) as exc:
        output.read("owner", "task", expected_identity=page["identity"])
    assert exc.value.code == "file_changed"


def test_duplicate_start_does_not_discard_live_writer(output):
    output.start("owner", "task")
    with pytest.raises(BridgeError):
        output.start("owner", "task")
    output.append("owner", "task", "stdout", b"still alive")
    assert output.read("owner", "task")["text"] == "still alive"


def test_resource_limit_preserves_prefix_and_exposes_contract(output):
    output.max_stream_bytes = 7
    output.start("owner", "task")
    output.append("owner", "task", "stdout", b"prefix")
    with pytest.raises(BridgeError) as exc:
        output.append("owner", "task", "stdout", b"overflow")
    assert exc.value.code == "process_output_limit"
    output.finish("owner", "task", complete=False, error=exc.value.code)
    page = output.read("owner", "task")
    assert page["text"] == "prefix" and not page["stream_complete"]
    assert page["capture_error"] == "process_output_limit"
    assert page["limits"]["automatic_deletion"] is False
    assert page["limits"]["max_stream_bytes"] == 7
    output.max_streams = 2
    with pytest.raises(BridgeError) as exc:
        output.start("owner", "second")
    assert exc.value.code == "process_output_limit"
    assert output.read("owner", "task")["text"] == "prefix"


def test_partial_disk_failure_commits_actual_prefix(output, monkeypatch):
    output.start("owner", "task")
    write = os.write
    calls = []

    def partial(fd, data):
        calls.append(True)
        if len(calls) == 1:
            return write(fd, data[:3])
        raise OSError("disk full")

    monkeypatch.setattr(os, "write", partial)
    with pytest.raises(BridgeError) as exc:
        output.append("owner", "task", "stdout", b"abcdef")
    assert exc.value.code == "process_output_storage"
    output.finish("owner", "task", complete=False, error=exc.value.code)
    page = output.read("owner", "task")
    assert page["text"] == "abc" and page["stream_sha256"] == hashlib.sha256(b"abc").hexdigest()
    assert not page["stream_complete"]


@pytest.mark.parametrize("change", ["symlink", "hardlink", "bytes", "permissions"])
def test_spool_tampering_fails_closed(output, tmp_path, change):
    output.start("owner", "task")
    output.append("owner", "task", "stdout", b"private")
    path = output.root / output._row("owner", "task", "stdout")["file_name"]
    if change == "symlink":
        path.unlink()
        path.symlink_to(tmp_path / "elsewhere")
    elif change == "hardlink":
        os.link(path, tmp_path / "copy")
    elif change == "bytes":
        path.write_bytes(b"changed")
    else:
        path.chmod(0o644)
    with pytest.raises(BridgeError) as exc:
        output.read("owner", "task")
    assert exc.value.code == "process_output_changed"


def freeze_file_identity(monkeypatch):
    import kirabridge.file_ranges as files
    import kirabridge.process_output_store as streams

    monkeypatch.setattr(files, "_identity", lambda info: "f" * 64)
    monkeypatch.setattr(streams, "_identity", lambda info: "f" * 64)


@pytest.mark.parametrize("offset", [0, 2, 7])
def test_committed_digest_detects_same_size_rewrite_with_frozen_stat(output, monkeypatch, offset):
    freeze_file_identity(monkeypatch)
    output.start("owner", "task")
    output.append("owner", "task", "stdout", b"private")
    output.finish("owner", "task", complete=True)
    assert output.read("owner", "task", offset=offset, max_bytes=2)["stream_complete"]
    path = output.root / output._row("owner", "task", "stdout")["file_name"]
    path.write_bytes(b"changed")
    with pytest.raises(BridgeError) as exc:
        output.read("owner", "task", offset=offset, max_bytes=2)
    assert exc.value.code == "process_output_changed"


def test_page_bytes_are_bound_to_verified_digest_even_if_file_changes_back(output, monkeypatch):
    import kirabridge.process_output_store as streams

    freeze_file_identity(monkeypatch)
    output.start("owner", "task")
    output.append("owner", "task", "stdout", b"private")
    path = output.root / output._row("owner", "task", "stdout")["file_name"]
    original = streams.read_file_range

    def forged_page(*args, **kwargs):
        path.write_bytes(b"changed")
        page = original(*args, **kwargs)
        path.write_bytes(b"private")
        return page

    monkeypatch.setattr(streams, "read_file_range", forged_page)
    with pytest.raises(BridgeError) as exc:
        output.read("owner", "task", offset=2, max_bytes=2)
    assert exc.value.code == "process_output_changed"


def test_append_during_digest_observation_never_mix_snapshots(output, monkeypatch):
    import kirabridge.process_output_store as streams

    output.start("owner", "task")
    output.append("owner", "task", "stdout", b"prefix")
    original, calls = streams.os.pread, []

    def append_after_read(fd, size, position):
        data = original(fd, size, position)
        calls.append(True)
        # First pread belongs to file_ranges; second to the digest pass.
        if len(calls) == 2:
            output.append("owner", "task", "stdout", b"suffix")
        return data

    with monkeypatch.context() as scoped:
        scoped.setattr(streams.os, "pread", append_after_read)
        with pytest.raises(BridgeError) as exc:
            output.read("owner", "task")
        assert exc.value.code == "process_output_changed"
    page = output.read("owner", "task")
    assert page["text"] == "prefixsuffix" and page["capture_state"] == "recording"
    assert not page["stream_complete"]


def test_verification_observes_pinned_completion_metadata(output, monkeypatch):
    import kirabridge.process_output_store as streams

    output.start("owner", "task")
    output.append("owner", "task", "stdout", b"prefix")
    original = streams.read_file_range

    def finished(*args, **kwargs):
        page = original(*args, **kwargs)
        output.finish("owner", "task", complete=True)
        return page

    with monkeypatch.context() as scoped:
        scoped.setattr(streams, "read_file_range", finished)
        page = output.read("owner", "task")
    assert page["capture_state"] == "recording" and not page["stream_complete"]
    assert output.read("owner", "task")["stream_complete"]


def test_verified_binary_range_crosses_hash_chunks_without_collecting_whole_stream(output):
    payload = b"a" * 65535 + "🙂".encode() + b"b" * 131072
    output.start("owner", "task")
    for position in range(0, len(payload), 65536):
        output.append("owner", "task", "stdout", payload[position : position + 65536])
    output.finish("owner", "task", complete=True)
    page = output.read("owner", "task", offset=65534, max_bytes=6, encoding="base64")
    assert base64.b64decode(page["data_base64"]) == payload[65534:65540]
    assert page["stream_sha256"] == hashlib.sha256(payload).hexdigest()
    assert page["stream_complete"] and not page["eof"]


def test_stream_budget_cannot_exceed_bounded_full_digest_contract(output):
    from kirabridge.process_output_store import MAX_STREAM_BYTES

    with pytest.raises(ValueError, match="64 MiB"):
        ProcessOutputStore(output.root, output.store, max_stream_bytes=MAX_STREAM_BYTES + 1)


async def test_managed_child_drains_beyond_preview_and_can_read_both_streams(output, tmp_path):
    manager = TerminalManager(output_store=output)
    running = []

    async def started(value):
        running.append(value)

    result = await manager.execute(
        "child",
        "owner",
        TerminalInput(
            argv=[
                sys.executable,
                "-c",
                "import os; os.write(1,b'a'*200000); os.write(2,b'\\xff'*9000)",
            ],
            cwd=str(tmp_path),
            max_output=16,
        ),
        [str(tmp_path)],
        [sys.executable],
        started,
    )
    assert result["exit_code"] == 0 and result["truncated"]
    assert len(result["stdout"].encode()) + len(result["stderr"].encode()) <= 16
    assert result["output_ranges"]["streams"]["stdout"]["bytes"] == 200000
    assert result["output_ranges"]["streams"]["stderr"]["bytes"] == 9000
    assert manager.read_output("owner", "child", offset=199990)["text"] == "a" * 10
    assert (
        base64.b64decode(
            manager.read_output("owner", "child", "stderr", encoding="base64")["data_base64"]
        )
        == b"\xff" * 9000
    )
    assert len(running) == 1 and not manager.sessions


async def test_capture_limit_after_spawn_is_uncertain_and_child_is_reaped(output, tmp_path):
    output.max_stream_bytes = 4
    manager, pids = TerminalManager(output_store=output), []

    async def started(value):
        pids.append(value["pid"])

    with pytest.raises(UncertainExecution) as exc:
        await manager.execute(
            "limited",
            "owner",
            TerminalInput(
                argv=[
                    sys.executable,
                    "-c",
                    "import os,time; os.write(1,b'overflow'); time.sleep(30)",
                ],
                cwd=str(tmp_path),
            ),
            [str(tmp_path)],
            [sys.executable],
            started,
        )
    assert exc.value.code == "process_output_limit"
    assert not manager.sessions
    with pytest.raises(ProcessLookupError):
        os.kill(pids[0], 0)
    assert output.read("owner", "limited")["capture_error"] == "process_output_limit"


async def test_timeout_retains_explicitly_incomplete_output(output, tmp_path):
    manager = TerminalManager(output_store=output)

    async def started(value):
        pass

    result = await manager.execute(
        "timeout",
        "owner",
        TerminalInput(
            argv=[sys.executable, "-c", "import os,time; os.write(1,b'prefix'); time.sleep(30)"],
            cwd=str(tmp_path),
            timeout=0.3,
        ),
        [str(tmp_path)],
        [sys.executable],
        started,
    )
    page = output.read("owner", "timeout")
    assert result["timed_out"] and page["text"] == "prefix"
    assert not page["stream_complete"] and page["capture_error"] == "timeout"
    assert not manager.sessions


async def test_capture_database_failure_after_spawn_is_uncertain(output, tmp_path, monkeypatch):
    manager = TerminalManager(output_store=output)

    async def started(value):
        pass

    def failed(*args):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(output, "append", failed)
    with pytest.raises(UncertainExecution) as exc:
        await manager.execute(
            "db-failure",
            "owner",
            TerminalInput(argv=[sys.executable, "-c", "print('output')"], cwd=str(tmp_path)),
            [str(tmp_path)],
            [sys.executable],
            started,
        )
    assert exc.value.code == "process_output_storage"
    assert not manager.sessions
    assert output.read("owner", "db-failure")["capture_error"] == "process_output_storage"


async def test_cancellation_reaps_child_and_finalizes_incomplete_streams(output, tmp_path):
    manager, ready, pids = TerminalManager(output_store=output), asyncio.Event(), []

    async def started(value):
        pids.append(value["pid"])
        ready.set()

    execution = asyncio.create_task(
        manager.execute(
            "cancelled",
            "owner",
            TerminalInput(
                argv=[sys.executable, "-c", "import time; time.sleep(30)"], cwd=str(tmp_path)
            ),
            [str(tmp_path)],
            [sys.executable],
            started,
        )
    )
    await ready.wait()
    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution
    assert not manager.sessions and not output._writers
    with pytest.raises(ProcessLookupError):
        os.kill(pids[0], 0)
    for stream in ("stdout", "stderr"):
        page = output.read("owner", "cancelled", stream)
        assert page["capture_state"] == "incomplete" and not page["stream_complete"]
        assert page["capture_error"] == "CancelledError"


async def test_repeated_cancellation_cannot_interrupt_child_cleanup(output, tmp_path, monkeypatch):
    import kirabridge.terminal_manager as terminal

    manager = TerminalManager(output_store=output)
    ready, reaping, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_reap, pids = terminal.reap_process, []

    async def delayed_reap(process):
        reaping.set()
        await release.wait()
        await original_reap(process)

    async def started(value):
        pids.append(value["pid"])
        ready.set()

    monkeypatch.setattr(terminal, "reap_process", delayed_reap)
    execution = asyncio.create_task(
        manager.execute(
            "cancelled-twice",
            "owner",
            TerminalInput(
                argv=[sys.executable, "-c", "import time; time.sleep(30)"], cwd=str(tmp_path)
            ),
            [str(tmp_path)],
            [sys.executable],
            started,
        )
    )
    await ready.wait()
    execution.cancel()
    await reaping.wait()
    execution.cancel()
    await asyncio.sleep(0)
    assert not execution.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await execution
    assert not manager.sessions and not output._writers
    with pytest.raises(ProcessLookupError):
        os.kill(pids[0], 0)
    assert output.read("owner", "cancelled-twice")["capture_state"] == "incomplete"


@pytest.mark.parametrize("flag", ["truncated", "output_truncated", "output_ref"])
def test_legacy_terminal_output_preserves_source_truncation(flag):
    source = {"stdout": "short", flag: {"truncated": True} if flag == "output_ref" else True}
    bridge = SimpleNamespace(
        security=SimpleNamespace(principal=lambda *args: None),
        task=lambda *args: {
            "operation": "terminal.execute",
            "state": "completed",
            "result": source,
        },
        terminal=SimpleNamespace(inspect=lambda *args: source),
    )
    assert read_query(bridge, "owner", ReadQuery(operation="terminal.output", task_id="x"))[
        "truncated"
    ]


def test_process_query_checks_owner_and_does_not_dispatch(output):
    output.start("owner", "task")
    output.append("owner", "task", "stdout", b"exact\x80")
    output.finish("owner", "task", complete=True)
    calls = []

    def task(owner, task_id):
        calls.append((owner, task_id))
        if owner != "owner":
            raise BridgeError("not_found", "Owned task not found")
        return {"operation": "terminal.execute", "state": "completed"}

    bridge = SimpleNamespace(
        security=SimpleNamespace(principal=lambda *args: None),
        task=task,
        terminal=TerminalManager(output_store=output),
    )
    result = read_query(
        bridge,
        "owner",
        ReadQuery(
            operation="process.output", task_id="task", offset=2, max_bytes=2, encoding="base64"
        ),
    )
    assert base64.b64decode(result["data_base64"]) == b"ac" and result["next_offset"] == 4
    assert calls == [("owner", "task")]
    with pytest.raises(BridgeError):
        read_query(bridge, "other", ReadQuery(operation="process.output", task_id="task"))


def test_output_range_validation():
    for selectors in (
        {"offset": -1},
        {"offset": True},
        {"stream": "combined"},
        {"max_bytes": 65537},
    ):
        with pytest.raises(ValidationError):
            OutputRangeInput(task_id="x", **selectors)
    with pytest.raises(ValidationError):
        ReadQuery(operation="terminal.output", task_id="x", expected_identity="a" * 64)
    with pytest.raises(ValidationError):
        ReadQuery(operation="process.output", task_id="x", tail=True)
