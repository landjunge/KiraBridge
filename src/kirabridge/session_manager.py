"""Exact tmux-pane selection; never infer an interactive session from a PID."""

import asyncio
import re
import shutil

from pydantic import Field

from kirabridge.bridge_core.models import BridgeError, Input, UncertainExecution


class SessionInput(Input):
    pane_id: str = Field(pattern=r"^%[0-9]+$")
    expected_pid: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=16384)
    submit: bool = True


class SessionManager:
    def __init__(self, bridge, *, socket_name=None):
        self.bridge, self.socket_name = bridge, socket_name
        self.lock = asyncio.Lock()

    async def command(self, *args, mutation=False):
        executable = shutil.which("tmux", path=self.bridge.terminal.environment["PATH"])
        if not executable:
            raise BridgeError(
                "session_transport_unavailable", "tmux is not installed in configured PATH"
            )
        argv = [executable] + (["-L", self.socket_name] if self.socket_name else []) + list(args)
        child = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=self.bridge.terminal.environment.copy(),
        )
        try:
            async with asyncio.timeout(3):
                data = bytearray()
                while len(data) <= 65536:
                    chunk = await child.stdout.read(min(8192, 65537 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                raw = bytes(data)
                if len(raw) > 65536:
                    raise BridgeError("output_limit", "tmux response exceeds 65536 bytes")
                await child.wait()
                if child.returncode:
                    raise BridgeError(
                        "session_transport_unavailable", "No accessible tmux server or pane"
                    )
                return raw.decode("utf-8", "replace")
        except (TimeoutError, BridgeError):
            if mutation:
                raise UncertainExecution(
                    "session_input_unknown", "Input outcome unknown; do not resend automatically"
                ) from None
            raise
        finally:
            if child.returncode is None:
                child.kill()
                await child.wait()

    async def catalog(self, principal):
        self.bridge.security.principal(principal, "session.inspect")
        try:
            raw = await self.command(
                "list-panes",
                "-a",
                "-F",
                "#{pane_id}\t#{pane_pid}\t#{pane_tty}\t#{pane_current_command}",
            )
        except BridgeError as exc:
            return {
                "transport": "tmux",
                "status": exc.code,
                "sessions": [],
                "scope": "No session attached; other terminal transports are not inferred",
            }
        rows = []
        for line in raw.splitlines()[:100]:
            parts = line.split("\t")
            if len(parts) == 4 and re.fullmatch(r"%[0-9]+", parts[0]) and parts[1].isdigit():
                rows.append(
                    dict(
                        pane_id=parts[0],
                        expected_pid=int(parts[1]),
                        tty=parts[2],
                        command=parts[3],
                        agent_identity_verified=False,
                    )
                )
        return {
            "transport": "tmux",
            "status": "available",
            "sessions": rows,
            "truncated": len(raw.splitlines()) > 100,
        }

    async def selected(self, principal, pane_id, expected_pid):
        catalog = await self.catalog(principal)
        if not any(
            r["pane_id"] == pane_id and r["expected_pid"] == expected_pid
            for r in catalog["sessions"]
        ):
            raise BridgeError(
                "session_selection_changed",
                "Select an exact current pane_id and expected_pid from session_catalog",
            )

    async def read(self, principal, pane_id, expected_pid):
        await self.selected(principal, pane_id, expected_pid)
        text = await self.command("capture-pane", "-p", "-t", pane_id, "-S", "-200")
        return {
            "pane_id": pane_id,
            "expected_pid": expected_pid,
            "text": text,
            "scope": "available tmux scrollback; not proof of project completion",
        }

    async def send(self, principal, args):
        self.bridge.security.principal(principal, "session.input")
        self.bridge.security.principal(principal, "terminal.execute")
        if "\x00" in args.text:
            raise BridgeError("invalid_arguments", "NUL in input")
        async with self.lock:
            await self.selected(principal, args.pane_id, args.expected_pid)
            argv = ["send-keys", "-t", args.pane_id, "-l", "--", args.text]
            if args.submit:
                argv += [";", "send-keys", "-t", args.pane_id, "Enter"]
            await self.command(*argv, mutation=True)
        return {
            "pane_id": args.pane_id,
            "expected_pid": args.expected_pid,
            "input_handed_to_transport": True,
            "agent_processed": False,
            "submitted": args.submit,
        }
