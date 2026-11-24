"""Real, disposable PTY coverage for KiraBridge-owned Zsh ZLE readiness."""

from __future__ import annotations

import asyncio
import inspect
import os
import shutil
import signal
import sys
import termios
import time

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.macos.zle_readiness import ZLEReadiness

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin"
    or not shutil.which("/usr/bin/script")
    or not os.path.exists("/bin/zsh"),
    reason="requires macOS, script(1), and the system Zsh",
)


class _TerminalIdentity:
    async def process_identity(self, pid, *, detailed=False):
        args = ["/bin/ps", "-p", str(pid), "-o", "uid=,tty=,lstart=,ppid=,comm="]
        child = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={**os.environ, "LC_ALL": "C"},
        )
        output, _ = await child.communicate()
        if child.returncode:
            raise BridgeError("visible_target_changed", "PTY test shell exited")
        return " ".join(output.decode().split())


async def _wait_for(predicate, *, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if inspect.isawaitable(result):
            result = await result
        if result:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timed out waiting for disposable PTY state")


class _PTYZsh:
    def __init__(self, channel, token, process, row):
        self.channel = channel
        self.token = token
        self.process = process
        self.row = row
        self.session = channel.sessions[token["generation"]]

    @classmethod
    async def start(cls):
        terminal = _TerminalIdentity()
        channel = ZLEReadiness(terminal)
        token = await channel.create()
        env = {
            **os.environ,
            "TERM": "xterm-256color",
            "ZDOTDIR": token["zdotdir"],
        }
        process = await asyncio.create_subprocess_exec(
            "/usr/bin/script",
            "-q",
            "/dev/null",
            "/bin/zsh",
            "-d",
            "-i",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
        try:
            async def shell_row():
                ps = await asyncio.create_subprocess_exec(
                    "/bin/ps",
                    "-axo",
                    "pid=,ppid=,tty=,comm=",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                output, _ = await ps.communicate()
                matches = []
                for line in output.decode().splitlines():
                    fields = line.split(None, 3)
                    if (
                        len(fields) == 4
                        and fields[1] == str(process.pid)
                        and fields[3].endswith("zsh")
                    ):
                        matches.append(fields)
                return matches[0] if len(matches) == 1 else None

            await _wait_for(lambda: channel.sessions[token["generation"]].writer is not None)
            fields = None
            deadline = time.monotonic() + 2
            while fields is None and time.monotonic() < deadline:
                fields = await shell_row()
                if fields is None:
                    await asyncio.sleep(0.02)
            if fields is None:
                raise AssertionError("disposable Zsh process was not found on its PTY")
            pid = int(fields[0])
            await terminal.process_identity(pid, detailed=True)
            row = {
                "controlled_shell": True,
                "pane_id": f"pty-test:{fields[2]}:{pid}",
                "expected_pid": pid,
                "tty": "/dev/" + fields[2],
            }
            await channel.bind(token, row)
            return cls(channel, token, process, row)
        except BaseException:
            process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=1)
            except (ProcessLookupError, TimeoutError):
                process.kill()
                await process.wait()
            await channel.close()
            raise

    async def type(self, text: bytes):
        before = self.session.sequence
        self.process.stdin.write(text)
        await self.process.stdin.drain()
        await _wait_for(lambda: self.session.sequence > before)

    async def close(self):
        if self.process.returncode is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(self.process.wait(), timeout=1)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        await self.channel.close()


@pytest.fixture
async def zsh_pty():
    shell = await _PTYZsh.start()
    try:
        yield shell
    finally:
        await shell.close()


async def test_empty_zle_state_is_fresh_and_buffer_contents_are_not_retained(zsh_pty):
    assert zsh_pty.session.peer_pid == zsh_pty.row["expected_pid"]
    tty_fd = os.open(
        zsh_pty.row["tty"], os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK
    )
    try:
        terminal_flags = termios.tcgetattr(tty_fd)[3]
    finally:
        os.close(tty_fd)
    assert not terminal_flags & termios.ICANON
    assert not terminal_flags & termios.ECHO
    result = await zsh_pty.channel.probe(zsh_pty.row)
    assert result["ready"] is True
    assert set(zsh_pty.session.latest) == {
        "sequence",
        "pid",
        "start",
        "tty",
        "dev",
        "inode",
        "empty",
        "cursor",
        "context",
        "challenge",
        "observed_at",
    }
    assert zsh_pty.session.latest["empty"] is True
    assert zsh_pty.session.latest["cursor"] == 0
    assert "length" not in zsh_pty.session.latest


@pytest.mark.parametrize("cursor_keys", [b"", b"\x01", b"\x01\x06" * 4])
async def test_whitespace_buffer_and_cursor_positions_are_never_ready(zsh_pty, cursor_keys):
    await zsh_pty.type(b" " * 35 + cursor_keys)
    assert zsh_pty.session.latest["empty"] is False
    with pytest.raises(BridgeError) as error:
        await zsh_pty.channel.probe(zsh_pty.row)
    assert error.value.code == "zle_input_not_empty"


async def test_multiline_continuation_is_never_ready(zsh_pty):
    await zsh_pty.type(b"echo 'unfinished\n")
    assert zsh_pty.session.latest["empty"] is False or zsh_pty.session.latest["context"] != "start"
    with pytest.raises(BridgeError):
        await zsh_pty.channel.probe(zsh_pty.row)


@pytest.mark.parametrize("mutation", ["peer", "pid", "tty", "generation", "replay"])
async def test_wrong_identity_and_replayed_reports_fail_closed(zsh_pty, mutation):
    session = zsh_pty.session
    latest = session.latest
    sequence = latest["sequence"] if mutation == "replay" else latest["sequence"] + 1
    nonce = zsh_pty.token["nonce"]
    generation = zsh_pty.token["generation"]
    pid = latest["pid"] + (1 if mutation == "pid" else 0)
    tty = "/dev/ttys000" if mutation == "tty" else latest["tty"]
    report_generation = "0" * 48 if mutation == "generation" else generation
    dev, inode = latest["dev"], latest["inode"]
    report = (
        f"STATE\t{nonce}\t{report_generation}\t{sequence}\t{pid}\t{latest['start']}\t"
        f"{tty}\t{dev}\t{inode}\t1\t0\tstart\t\n"
    ).encode("ascii")
    peer_pid = latest["pid"] + (1 if mutation == "peer" else 0)
    with pytest.raises(BridgeError) as error:
        zsh_pty.channel._record(session, report, peer_pid)
    assert error.value.code == "zle_report_rejected"


async def test_expired_challenge_and_shell_restart_are_not_accepted(zsh_pty):
    session = zsh_pty.session
    session.challenge = "a" * 48
    session.challenge_started = time.monotonic() - 10
    latest = session.latest
    report = (
        f"STATE\t{zsh_pty.token['nonce']}\t{zsh_pty.token['generation']}\t"
        f"{latest['sequence'] + 1}\t{latest['pid']}\t{latest['start']}\t{latest['tty']}\t"
        f"{latest['dev']}\t{latest['inode']}\t1\t0\tstart\t{session.challenge}\n"
    ).encode("ascii")
    with pytest.raises(BridgeError) as error:
        zsh_pty.channel._record(session, report, latest["pid"])
    assert error.value.code == "zle_report_rejected"

    directory = zsh_pty.token["zdotdir"]
    generation = zsh_pty.token["generation"]
    await zsh_pty.close()
    assert generation not in zsh_pty.channel.sessions
    assert not os.path.exists(directory)
    with pytest.raises(BridgeError) as stale:
        await zsh_pty.channel.probe(zsh_pty.row)
    assert stale.value.code == "zle_session_stale"
    reopened = await _PTYZsh.start()
    try:
        assert reopened.token["generation"] != generation
        assert (await reopened.channel.probe(reopened.row))["ready"] is True
    finally:
        await reopened.close()


async def test_failed_create_and_bind_remove_private_socket_and_zdotdir(monkeypatch):
    import kirabridge.platform_adapters.macos.zle_readiness as readiness_module

    channel = ZLEReadiness(_TerminalIdentity())
    created = []
    mkdtemp = readiness_module.tempfile.mkdtemp
    start_server = readiness_module.asyncio.start_unix_server

    def capture_directory(*args, **kwargs):
        path = mkdtemp(*args, **kwargs)
        created.append(path)
        return path

    async def listener_failure(*args, **kwargs):
        raise OSError("test-only listener failure")

    monkeypatch.setattr(readiness_module.tempfile, "mkdtemp", capture_directory)
    monkeypatch.setattr(readiness_module.asyncio, "start_unix_server", listener_failure)
    with pytest.raises(OSError):
        await channel.create()
    assert created and not os.path.exists(created[-1])

    monkeypatch.setattr(readiness_module.asyncio, "start_unix_server", start_server)
    token = await channel.create()
    with pytest.raises(BridgeError):
        await channel.bind(
            token,
            {
                "controlled_shell": True,
                "pane_id": "invalid-test-target",
                "expected_pid": 0,
                "tty": "/dev/ttys000",
            },
        )
    assert not os.path.exists(token["zdotdir"])
    assert token["generation"] not in channel.sessions
