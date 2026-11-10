"""Bridge-owned Linux PTY. Never attaches to an existing user terminal."""

from __future__ import annotations

import asyncio
import os
import pty
import re
import signal
import time
from dataclasses import dataclass, field

from kirabridge.bridge_core.models import BridgeError

_PROMPT = "KIRA_OWNED> "
_TEXT = re.compile(r"^[^\x00-\x1f\x7f]+$")


@dataclass
class _Owned:
    process: asyncio.subprocess.Process
    master: int
    tty: str
    buf: bytearray = field(default_factory=bytearray)


class LinuxOwnedTerminal:
    """One shell per call, started by this process and visible only in its catalog."""

    def __init__(self):
        self._sessions: dict[str, _Owned] = {}

    async def open_shell(self, cwd: str) -> dict:
        if os.name != "posix":
            raise BridgeError("unsupported_platform", "An owned PTY requires POSIX")
        shell = "/bin/bash" if os.path.isfile("/bin/bash") else "/bin/sh"
        master, slave = pty.openpty()
        tty_name = os.ttyname(slave)
        try:
            process = await asyncio.create_subprocess_exec(
                shell,
                "--noprofile",
                "--norc",
                "-i",
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=cwd,
                env={
                    "PATH": "/usr/bin:/bin",
                    "HOME": cwd,
                    "TERM": "dumb",
                    "PS1": _PROMPT,
                    "KIRABRIDGE_OWNED": "1",
                },
                start_new_session=True,
            )
        except OSError as exc:
            os.close(master)
            os.close(slave)
            raise BridgeError("session_transport_unavailable", "Owned shell did not start") from exc
        os.close(slave)
        if process.pid <= 1:
            os.close(master)
            raise BridgeError("session_transport_unavailable", "Owned shell PID is not usable")
        pane_id = f"linux:{process.pid}"
        os.set_blocking(master, False)
        state = _Owned(process, master, tty_name)
        self._sessions[pane_id] = state
        loop = asyncio.get_running_loop()
        loop.add_reader(master, self._on_master, state)
        try:
            await self._wait_prompt(state)
        except BridgeError:
            await self.close(pane_id)
            raise
        return self._row(pane_id, state) | {"opened": True, "agent_processed": False}

    async def catalog(self):
        rows = []
        for pane_id, state in list(self._sessions.items()):
            if state.process.returncode is not None:
                continue
            rows.append(self._row(pane_id, state))
        return rows

    async def read(self, pane_id):
        return self._text(self._get(pane_id))

    async def insert(self, pane_id, text):
        if not text or not _TEXT.fullmatch(text):
            raise BridgeError(
                "invalid_arguments", "Owned terminal text must be one line without control characters"
            )
        self._write(self._get(pane_id), text.encode())

    async def press_return(self, pane_id):
        self._write(self._get(pane_id), b"\n")

    async def send(self, pane_id, text, *, submit, require_idle):
        state = self._get(pane_id)
        if require_idle and not self._idle(state):
            raise BridgeError("session_busy", "Owned shell is not at its prompt")
        if text:
            await self.insert(pane_id, text)
        if submit:
            await self.press_return(pane_id)

    async def close(self, pane_id):
        state = self._sessions.pop(pane_id, None)
        if state is None:
            raise BridgeError("session_selection_changed", "Owned terminal is not open")
        if state.process.returncode is None and state.process.pid > 1:
            try:
                os.killpg(state.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            asyncio.get_running_loop().remove_reader(state.master)
        except (RuntimeError, ValueError, OSError):
            pass
        os.close(state.master)
        try:
            await asyncio.wait_for(state.process.wait(), 2)
        except TimeoutError:
            try:
                os.killpg(state.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await state.process.wait()

    def _get(self, pane_id) -> _Owned:
        state = self._sessions.get(pane_id)
        if state is None or state.process.returncode is not None:
            raise BridgeError("session_selection_changed", "Owned terminal is not open")
        return state

    def _row(self, pane_id, state) -> dict:
        return {
            "pane_id": pane_id,
            "expected_pid": state.process.pid,
            "tty": state.tty,
            "command": "bash",
            "transport": "linux",
            "busy": not self._idle(state),
            "processes": [],
        }

    def _text(self, state) -> str:
        return bytes(state.buf).decode("utf-8", "replace")

    def _idle(self, state) -> bool:
        return self._text(state).rstrip().endswith("KIRA_OWNED>")

    def _write(self, state, data: bytes):
        try:
            os.write(state.master, data)
        except OSError as exc:
            raise BridgeError("session_transport_unavailable", "Owned terminal write failed") from exc

    async def _wait_prompt(self, state):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if self._idle(state):
                return
            await asyncio.sleep(0.02)
        raise BridgeError("session_observation_timeout", "Owned shell prompt did not appear")

    def _on_master(self, state):
        while True:
            try:
                chunk = os.read(state.master, 4096)
            except BlockingIOError:
                return
            except OSError:
                return
            if not chunk:
                return
            state.buf.extend(chunk)
            if len(state.buf) > 65536:
                del state.buf[:-65536]
