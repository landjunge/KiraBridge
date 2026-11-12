"""Only fresh owned children; no UI, production state, system_profiler or foreign signals."""

import asyncio
import json
import os
import signal
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import kirabridge.platform_adapters as platform
from kirabridge.bridge_core.models import TerminalInput, UncertainExecution
from kirabridge.process_output_store import ProcessOutputStore
from kirabridge.task_manager.store import Store
from kirabridge.terminal_manager import TerminalManager

CHILD = r"""
import json,os,signal,sys,time
from pathlib import Path
mode,metadata,release=sys.argv[1:]
forked=os.fork()
if forked:
    if mode=='publish_pause':os.waitpid(forked,0);os._exit(0)
    if mode=='redirect':time.sleep(.15);os._exit(0)
    time.sleep(15)
else:
    if mode=='escape':os.setsid()
    else:os.setpgid(0,0)
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    if mode=='redirect':
        fd=os.open(os.devnull,os.O_WRONLY);os.dup2(fd,1);os.dup2(fd,2);os.close(fd)
    pending=Path(metadata).with_suffix('.pending')
    if mode=='publish_pause':
        pending.touch()
        Path(metadata+'.publishing').touch()
        end=time.monotonic()+3
        while time.monotonic()<end and not Path(release).exists():time.sleep(.01)
    pending.write_text(json.dumps({'pid':os.getpid(),'pgid':os.getpgrp(),'sid':os.getsid(0),'uid':os.getuid()}))
    pending.replace(metadata)  # Existence now means the complete JSON has been closed.
    if mode=='group':os.write(2,b'x'*262144)
    end=time.monotonic()+12
    while time.monotonic()<end and not Path(release).exists():time.sleep(.02)
"""


@pytest.fixture
def owned_output(tmp_path):
    store = Store(tmp_path / "state/bridge.sqlite3")
    output = ProcessOutputStore(tmp_path / "state/output", store)
    yield output
    assert not output._writers
    store.close()


async def absent(pid):
    async with asyncio.timeout(3):
        while True:
            value = await asyncio.to_thread(
                subprocess.run,
                ["/bin/ps", "-p", str(pid), "-o", "stat="],
                capture_output=True,
                text=True,
                timeout=1,
            )
            if value.returncode == 1:
                return
            await asyncio.sleep(0.02)


async def metadata(path):
    async with asyncio.timeout(3):
        while not path.exists():
            await asyncio.sleep(0.01)
    return json.loads(path.read_text())


def arguments(tmp_path, mode, *, timeout=0.6):
    return TerminalInput(
        argv=[
            sys.executable,
            "-I",
            "-c",
            CHILD,
            mode,
            str(tmp_path / "metadata.json"),
            str(tmp_path / "exit.request"),
        ],
        cwd=str(tmp_path),
        timeout=timeout,
        max_output=16,
    )


async def test_child_metadata_is_not_published_during_empty_file_creation(tmp_path, owned_output):
    manager = TerminalManager(output_store=owned_output)
    execution = asyncio.create_task(
        manager.execute(
            "publish",
            "owner",
            arguments(tmp_path, "publish_pause", timeout=10),
            [str(tmp_path)],
            [sys.executable],
            AsyncMock(),
        )
    )
    reader = None
    try:
        async with asyncio.timeout(3):
            while not (tmp_path / "metadata.json.publishing").exists():
                await asyncio.sleep(0.01)
        assert (tmp_path / "metadata.pending").read_text() == ""
        assert not (tmp_path / "metadata.json").exists()
        reader = asyncio.create_task(metadata(tmp_path / "metadata.json"))
        await asyncio.sleep(0)
        assert not reader.done()
        (tmp_path / "exit.request").write_text("release only this fresh fixture")
        child = await reader
        result = await execution
        assert child["sid"] == result["pid"] and child["pgid"] != result["pid"]
        assert result["exit_code"] == 0 and not manager.sessions and not owned_output._writers
        await absent(result["pid"])
        await absent(child["pid"])
    finally:
        (tmp_path / "exit.request").write_text("release only this fresh fixture")
        if reader is not None and not reader.done():
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        if not execution.done():
            execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)


@pytest.mark.parametrize("mode", ["group", "redirect"])
async def test_created_session_cleans_new_child_group_even_after_leader_exit(
    tmp_path, owned_output, mode, monkeypatch
):
    manager, handles, calls = TerminalManager(output_store=owned_output), [], []
    original = os.killpg

    def own_signal(group, value):
        pin = handles[0]._kirabridge_owned_session
        assert group != os.getpgrp() and pin.sid != os.getsid(0)
        # A live anchor must positively belong to this CREATED session.
        assert any(
            row[2] == group and row[3] == pin.sid
            for row in platform._session_members(handles[0], pin)
        )
        calls.append((group, value))
        return original(group, value)

    async def started(value):
        handles.append(manager.sessions["fixture"].process)
        assert handles[0]._kirabridge_owned_session.sid == value["pid"]

    monkeypatch.setattr(os, "killpg", own_signal)
    result = await manager.execute(
        "fixture",
        "owner",
        arguments(tmp_path, mode, timeout=3 if mode == "redirect" else 0.6),
        [str(tmp_path)],
        [sys.executable],
        started,
    )
    child = await metadata(tmp_path / "metadata.json")
    assert child["sid"] == result["pid"] and child["pgid"] != result["pid"]
    assert any(group == child["pgid"] for group, _ in calls)
    assert result["timed_out"] is (mode == "group")
    assert result["exit_code"] == (-signal.SIGTERM if mode == "group" else 0)
    assert not manager.sessions and handles[0].stdout.at_eof() and handles[0].stderr.at_eof()
    assert owned_output.read("owner", "fixture")["capture_state"] == (
        "incomplete" if mode == "group" else "complete"
    )
    await absent(result["pid"])
    await absent(child["pid"])


async def test_child_with_new_session_and_inherited_pipe_remains_unknown(tmp_path, owned_output):
    manager = TerminalManager(output_store=owned_output)
    try:
        with pytest.raises(UncertainExecution) as error:
            await manager.execute(
                "escape",
                "owner",
                arguments(tmp_path, "escape"),
                [str(tmp_path)],
                [sys.executable],
                AsyncMock(),
            )
        assert error.value.code == "process_cleanup_unknown"
        child = await metadata(tmp_path / "metadata.json")
        assert child["sid"] == child["pid"]
        assert os.getsid(child["pid"]) == child["sid"]  # Never signaled by our reaper.
        assert not manager.sessions
        assert owned_output.read("owner", "escape")["capture_error"] == "process_cleanup_unknown"
    finally:
        (tmp_path / "exit.request").write_text("exit only this fresh fixture")
        if (tmp_path / "metadata.json").exists():
            await absent((await metadata(tmp_path / "metadata.json"))["pid"])


async def test_repeated_cancellation_finishes_owned_session_and_durable_streams(
    tmp_path, owned_output, monkeypatch
):
    manager, entered, release = (
        TerminalManager(output_store=owned_output),
        asyncio.Event(),
        asyncio.Event(),
    )
    original = platform._owned_session_groups

    async def delayed(*args):
        entered.set()
        await release.wait()
        return await original(*args)

    monkeypatch.setattr(platform, "_owned_session_groups", delayed)
    execution = asyncio.create_task(
        manager.execute(
            "cancel",
            "owner",
            arguments(tmp_path, "group", timeout=10),
            [str(tmp_path)],
            [sys.executable],
            AsyncMock(),
        )
    )
    child = await metadata(tmp_path / "metadata.json")
    execution.cancel()
    await entered.wait()
    execution.cancel()
    await asyncio.sleep(0)
    assert not execution.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await execution
    assert not manager.sessions and not owned_output._writers
    assert owned_output.read("owner", "cancel")["capture_error"] == "CancelledError"
    await absent(child["pid"])


@pytest.mark.parametrize(
    "fault", ["foreign_uid", "foreign_sid", "caller_group", "reused_leader", "partial"]
)
def test_session_census_refuses_unknown_or_protected_members_without_signals(monkeypatch, fault):
    own_uid, sid, group, pid = os.geteuid(), 987654, 987655, 987656
    row = f"{pid} {own_uid} {group} S\n"
    if fault == "foreign_uid":
        row = f"{pid} {own_uid + 1} {group} S\n"
    if fault == "foreign_sid":
        row += f"987657 {own_uid} {group} S\n"
    if fault == "caller_group":
        group = os.getpgrp()
        row = f"{pid} {own_uid} {group} S\n"
    if fault == "reused_leader":
        row += f"{sid} {own_uid} {sid} Ss\n"
    if fault == "partial":
        row = "incomplete\n"
    row += f"{os.getpid()} {own_uid} {os.getpgrp()} S\n"
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=row, stderr="")
    )
    real_sid = os.getsid
    monkeypatch.setattr(
        os,
        "getsid",
        lambda value: real_sid(0) if value in {0, os.getpid()} else sid + (value == 987657),
    )
    monkeypatch.setattr(os, "getpgid", lambda value: sid if value == sid else group)
    monkeypatch.setattr(os, "killpg", lambda *args: pytest.fail("No uncertain session signal"))
    child = SimpleNamespace(pid=sid, returncode=0 if fault == "reused_leader" else None)
    with pytest.raises(UncertainExecution) as error:
        platform._session_members(child, platform._OwnedSession(sid, own_uid))
    assert error.value.code == "process_cleanup_unknown"
    assert error.value.cleanup_diagnostic["phase"] == "owned_session_census"
    assert error.value.cleanup_diagnostic["cause_type"] == "ValueError"


@pytest.mark.parametrize(
    "fault", ["empty", "no_caller", "stderr", "caller_uid", "caller_group", "caller_zombie"]
)
async def test_exited_leader_and_eof_never_turn_partial_census_into_empty_session(
    monkeypatch, fault
):
    sid, uid = 987654, os.geteuid()
    stdout = f"{os.getpid()} {uid} {os.getpgrp()} S\n"
    stderr = ""
    if fault == "empty":
        stdout = ""
    if fault == "no_caller":
        stdout = f"987658 {uid} 987658 S\n"
    if fault == "stderr":
        stderr = "ps: observation incomplete\n"
    if fault == "caller_uid":
        stdout = f"{os.getpid()} {uid + 1} {os.getpgrp()} S\n"
    if fault == "caller_group":
        stdout = f"{os.getpid()} {uid} 987659 S\n"
    if fault == "caller_zombie":
        stdout = f"{os.getpid()} {uid} {os.getpgrp()} Z\n"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=stdout, stderr=stderr),
    )
    eof = asyncio.StreamReader()
    eof.feed_eof()
    child = SimpleNamespace(
        pid=sid,
        returncode=0,
        stdout=eof,
        stderr=eof,
        wait=AsyncMock(return_value=0),
        _kirabridge_owned_session=platform._OwnedSession(sid, uid),
    )
    monkeypatch.setattr(os, "killpg", lambda *args: pytest.fail("No incomplete-census signal"))
    with pytest.raises(UncertainExecution) as error:
        await platform.stop_process(child)
    assert error.value.code == "process_cleanup_unknown"
    assert eof.at_eof()
    child.wait.assert_not_awaited()


def test_positive_live_caller_anchor_allows_observed_empty_created_session(monkeypatch):
    stdout = f"{os.getpid()} {os.geteuid()} {os.getpgrp()} S\n"
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    )
    assert (
        platform._session_members(
            SimpleNamespace(pid=987654, returncode=0), platform._OwnedSession(987654, os.geteuid())
        )
        == ()
    )


async def test_last_group_anchor_exiting_never_signals_stale_pgid(monkeypatch):
    sid, group, pid = 987654, 987655, 987656
    child = SimpleNamespace(pid=sid, returncode=-15)
    monkeypatch.setattr(
        platform,
        "_owned_session_groups",
        AsyncMock(return_value=[(pid, os.geteuid(), group, sid, "S")]),
    )
    original_sid = os.getsid

    def observed(value):
        if value == 0:
            return original_sid(0)
        raise ProcessLookupError

    monkeypatch.setattr(os, "getsid", observed)
    monkeypatch.setattr(os, "killpg", lambda *args: pytest.fail("Stale PGID must not be signaled"))
    await platform._signal_owned_session(
        child, platform._OwnedSession(sid, os.geteuid()), signal.SIGTERM
    )


async def test_unpinned_legacy_process_never_gains_session_scope(monkeypatch):
    async def forbidden(*args):
        pytest.fail("Unpinned child gained session-wide authority")

    monkeypatch.setattr(platform, "_stop_owned_session", forbidden)
    monkeypatch.setattr(os, "killpg", lambda *args: (_ for _ in ()).throw(ProcessLookupError()))
    child = SimpleNamespace(pid=987654, wait=AsyncMock())
    await platform.stop_process(child)
    child.wait.assert_awaited_once()


async def test_double_cancellation_during_spawn_adopts_handle_before_owned_cleanup(
    tmp_path, monkeypatch
):
    entered, release = asyncio.Event(), asyncio.Event()
    child = SimpleNamespace(pid=987654)

    async def factory(*args, **kwargs):
        entered.set()
        await release.wait()
        return child

    cleanup = AsyncMock()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", factory)
    monkeypatch.setattr(platform, "_pin_owned_session", lambda process: None)
    monkeypatch.setattr(platform, "reap_process", cleanup)
    descriptor = os.open(tmp_path, os.O_RDONLY)
    try:
        creation = asyncio.create_task(
            platform.spawn_process(["fake"], descriptor, {}, stdin=None, stdout=None, stderr=None)
        )
        await entered.wait()
        creation.cancel()
        await asyncio.sleep(0)
        creation.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await creation
        cleanup.assert_awaited_once_with(child)
    finally:
        os.close(descriptor)


async def test_unknown_census_closes_only_owned_transport_and_finalizes_output(
    tmp_path, owned_output, monkeypatch
):
    manager, handles = TerminalManager(output_store=owned_output), []

    def unavailable(*args):
        raise UncertainExecution("process_cleanup_unknown", "synthetic incomplete census")

    async def started(value):
        handles.append(manager.sessions["census-failure"].process)

    monkeypatch.setattr(platform, "_session_members", unavailable)
    monkeypatch.setattr(os, "killpg", lambda *args: pytest.fail("No uncertain group signal"))
    with pytest.raises(UncertainExecution) as error:
        await manager.execute(
            "census-failure",
            "owner",
            TerminalInput(
                argv=[
                    sys.executable,
                    "-c",
                    "import time; print('owned',flush=True);time.sleep(15)",
                ],
                cwd=str(tmp_path),
                timeout=0.3,
            ),
            [str(tmp_path)],
            [sys.executable],
            started,
        )
    assert error.value.code == "process_cleanup_unknown"
    async with asyncio.timeout(2):
        await handles[0].wait()
    assert not manager.sessions and not owned_output._writers
    for stream in ["stdout", "stderr"]:
        page = owned_output.read("owner", "census-failure", stream)
        assert page["capture_state"] == "incomplete"
        assert page["capture_error"] == "process_cleanup_unknown"
    await absent(handles[0].pid)


async def test_group_reaper_itself_preserves_repeated_cancellation(monkeypatch):
    entered, release, events = asyncio.Event(), asyncio.Event(), []

    async def stopped(child):
        entered.set()
        await release.wait()
        child.returncode = -9
        events.append("finished-own-cleanup")

    monkeypatch.setattr(platform, "stop_process", stopped)
    child = SimpleNamespace(returncode=None, stdin=None, stdout=None, stderr=None)
    reaping = asyncio.create_task(platform.reap_process(child))
    await entered.wait()
    reaping.cancel()
    await asyncio.sleep(0)
    reaping.cancel()
    await asyncio.sleep(0)
    assert not reaping.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await reaping
    assert events == ["finished-own-cleanup"]
