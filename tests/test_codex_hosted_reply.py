"""Codex >= 0.169: the app-server daemon, not the terminal process, writes the rollout."""

import asyncio
import time
from datetime import datetime
from types import SimpleNamespace

import pytest
from test_codex_reply import BODY, THREAD, Pipe, append, events

from kirabridge.bridge_core.config import VisibleTerminalBinding
from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters import codex_reply


def stamp(offset):
    return datetime.fromtimestamp(time.time() + offset).strftime("%a %b %d %H:%M:%S %Y")


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    home = tmp_path / "codex"
    root = home / "sessions"
    day = datetime.now()
    folder = root / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"
    folder.mkdir(parents=True)
    daemon = home / "packages" / "app-server-daemon" / "releases" / "x" / "bin" / "codex"
    state = SimpleNamespace(
        root=root,
        folder=folder,
        tmp=tmp_path,
        daemon=daemon,
        host_exe=str(daemon),
        host_pid=200,
        started=stamp(-30),
        holders={},
        reaped=[],
    )
    state.terminal = lambda: f"501 ttys001 {state.started} 100 /usr/local/bin/codex"
    state.host_identity = lambda: f"501 ?? {stamp(-3000)} 1 {state.host_exe}"

    def rollout(name="rollout-a.jsonl", thread=THREAD, cwd=None):
        path = folder / name
        append(
            path,
            [
                {
                    "type": "session_meta",
                    "payload": {
                        "id": thread,
                        "originator": "codex-tui",
                        "cwd": str(cwd or tmp_path),
                    },
                }
            ],
        )
        state.holders[path] = state.host_pid
        return path

    state.rollout = rollout

    async def process_identity(pid, *, detailed):
        assert detailed is True
        if pid == 101:
            return state.terminal()
        if pid == state.host_pid:
            return state.host_identity()
        raise BridgeError("visible_target_changed", "gone")

    async def process_factory(*argv, **options):
        if argv[:3] == ("/usr/sbin/lsof", "-a", "-p"):
            raw = f"p101\0\nfcwd\0tDIR\0n{tmp_path}\0\n".encode()
        else:
            assert argv[:4] == ("/usr/sbin/lsof", "-F0pfaDint", "--", argv[3])
            path = next(p for p in state.holders if str(p) == argv[3])
            info = path.stat()
            raw = (
                f"p{state.holders[path]}\0\nf9\0aw\0tREG\0D{hex(info.st_dev)}\0"
                f"i{info.st_ino}\0n{path}\0\n"
            ).encode()
        child = SimpleNamespace(stdout=Pipe(raw), returncode=0)

        async def wait():
            return 0

        child.wait = wait
        return child

    async def reap(child, *, process_group):
        state.reaped.append(child)

    monkeypatch.setattr(codex_reply, "reap_process", reap)
    state.identity = process_identity
    state.observer = codex_reply.CodexReplyObserver(root, process_factory=process_factory)
    state.binding = VisibleTerminalBinding(
        pane_id="terminal:101:ttys001",
        expected_pid=100,
        agent_pid=101,
        ready_pattern=r"(?m)^›\s*$",
    )
    return state


async def prepare(state):
    return await state.observer.prepare(
        state.binding,
        process_identity=state.identity,
        expected_identity=state.terminal(),
        body=BODY,
        cwd=str(state.tmp),
    )


async def test_daemon_written_rollout_is_discovered_and_the_exact_reply_observed(hosted):
    path = hosted.rollout()
    result = await prepare(hosted)
    assert result["state"] == "ready", result
    cursor = result["cursor"]
    assert cursor["binding_origin"] == "hosted_writer_discovery" and cursor["host_pid"] == 200
    append(path, events())
    answer = await hosted.observer.observe(
        cursor, hosted.binding, body=BODY, process_identity=hosted.identity
    )
    assert answer["state"] == "completed" and answer["text"] == "Observed final answer"
    assert answer["evidence"]["protocol_binding"]["origin"] == "hosted_writer_discovery"


async def test_writer_outside_the_codex_daemon_directory_is_refused(hosted):
    hosted.rollout()
    hosted.host_exe = "/usr/bin/other-writer"
    result = await prepare(hosted)
    assert result["state"] == "unavailable"


async def test_writer_must_be_the_versioned_release_codex_binary(hosted):
    hosted.rollout()
    host_root = hosted.root.parent / "packages" / "app-server-daemon"
    hosted.host_exe = str(host_root / "helper" / "x")
    assert (await prepare(hosted))["state"] == "unavailable"
    hosted.host_exe = str(host_root / "releases" / "0.169.1-x86_64-apple-darwin" / "bin" / "codex")
    result = await prepare(hosted)
    assert result["state"] == "ready"


async def test_two_hosted_candidates_are_ambiguous(hosted):
    hosted.rollout("rollout-a.jsonl")
    hosted.rollout("rollout-b.jsonl", thread="01a192b9-64f2-7d22-8429-cabd5faf1999")
    result = await prepare(hosted)
    assert result["state"] == "unavailable" and "ambiguous" in str(result)


async def test_rollout_from_another_cwd_or_before_the_process_is_not_a_candidate(hosted):
    hosted.rollout(cwd=hosted.tmp / "elsewhere")
    assert (await prepare(hosted))["state"] == "unavailable"
    hosted.started = stamp(+3600)  # process "started" after the file was born
    assert (await prepare(hosted))["state"] == "unavailable"


async def test_replaced_host_process_cannot_complete_the_reply(hosted):
    path = hosted.rollout()
    cursor = (await prepare(hosted))["cursor"]
    append(path, events())
    hosted.host_pid = 300  # another process now holds the writer
    hosted.holders[path] = 300
    answer = await hosted.observer.observe(
        cursor, hosted.binding, body=BODY, process_identity=hosted.identity
    )
    assert answer["state"] == "unavailable"
    assert not asyncio.iscoroutine(answer)
