from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from kirabridge.bridge_core.models import BridgeError, TerminalInput
from kirabridge.filesystem_manager import PathScope
from kirabridge.platform_adapters import reap_process, spawn_process, stop_process

EvidenceCallback = Callable[[dict], Awaitable[None]]


@dataclass
class Session:
    task_id: str
    principal: str
    process: asyncio.subprocess.Process
    stdout: bytearray = field(default_factory=bytearray)
    stderr: bytearray = field(default_factory=bytearray)
    total: int = 0
    timed_out: bool = False
    terminated: bool = False


def minimal_environment() -> dict[str, str]:
    return {"PATH": os.defpath, "LANG": "en_US.UTF-8", "LC_CTYPE": "UTF-8", "TERM": "dumb"}


def check_executable(value: str, executables: list[str]) -> None:
    executable = Path(value)
    allowed = {str(Path(p).resolve()) for p in executables}
    if not executable.is_absolute() or str(executable.resolve()) not in allowed:
        raise BridgeError("executable_denied", "Executable is not explicitly allowed")
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise BridgeError(
            "executable_unavailable", "Allowed executable is missing or not executable"
        )


class TerminalManager:
    def __init__(self):
        self.sessions: dict[str, Session] = {}

    async def execute(
        self,
        task_id: str,
        principal: str,
        args: TerminalInput,
        roots: list[str],
        executables: list[str],
        running: EvidenceCallback,
        *,
        env: dict | None = None,
        stdin: bytes | None = None,
        line_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict:
        check_executable(args.argv[0], executables)
        if any("\x00" in part for part in args.argv):
            raise BridgeError("invalid_command", "NUL in command argument")
        scope = PathScope(roots)
        # Pin cwd, then fchdir in a separate exec trampoline (macOS has no directory /dev/fd).
        with scope.directory(args.cwd) as cwd_fd:
            process = await spawn_process(
                args.argv,
                cwd_fd,
                env=env if env is not None else minimal_environment(),
                stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=1048576,
            )
        session = Session(task_id, principal, process)
        self.sessions[task_id] = session

        async def drain(reader, buffer, events=False):
            pending = bytearray()
            while chunk := await reader.read(8192):
                session.total += len(chunk)
                room = max(0, args.max_output - len(session.stdout) - len(session.stderr))
                buffer.extend(chunk[:room])
                if events and line_callback:
                    pending.extend(chunk)
                    if len(pending) > 1048576:
                        raise BridgeError("agent_protocol", "Agent event exceeds byte limit")
                    while b"\n" in pending:
                        line, _, rest = pending.partition(b"\n")
                        pending = bytearray(rest)
                        await line_callback(line.decode("utf-8", errors="replace"))
            if events and pending and line_callback:
                await line_callback(pending.decode("utf-8", errors="replace"))

        async def send_input():
            if process.stdin is not None:
                try:
                    process.stdin.write(stdin or b"")
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    process.stdin.close()

        readers = [
            asyncio.create_task(drain(process.stdout, session.stdout, True)),
            asyncio.create_task(drain(process.stderr, session.stderr)),
            asyncio.create_task(send_input()),
        ]
        try:
            await running({"pid": process.pid, "evidence_type": "local_process_spawned"})
            try:
                async with asyncio.timeout(args.timeout):
                    await asyncio.gather(process.wait(), *readers)
            except TimeoutError:
                session.timed_out = True
        finally:
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
            await reap_process(process)
            self.sessions.pop(task_id, None)
        return {
            "exit_code": process.returncode,
            "stdout": session.stdout.decode("utf-8", "replace"),
            "stderr": session.stderr.decode("utf-8", "replace"),
            "truncated": session.total > args.max_output,
            "output_bytes": session.total,
            "timed_out": session.timed_out,
            "terminated": session.terminated,
            "pid": process.pid,
        }

    def inspect(self, principal: str, task_id: str) -> dict:
        session = self.sessions.get(task_id)
        if session is None or session.principal != principal:
            raise BridgeError("not_found", "Active owned process not found")
        return {
            "task_id": task_id,
            "pid": session.process.pid,
            "alive": session.process.returncode is None,
            "stdout": session.stdout.decode("utf-8", "replace"),
            "stderr": session.stderr.decode("utf-8", "replace"),
            "output_bytes": session.total,
        }

    async def terminate(self, principal: str, task_id: str) -> dict:
        self.inspect(principal, task_id)
        session = self.sessions[task_id]
        session.terminated = True
        await stop_process(session.process)
        return {
            "termination_requested": True,
            "pid": session.process.pid,
            "exit_code": session.process.returncode,
        }
