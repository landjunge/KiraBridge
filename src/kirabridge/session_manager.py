"""Exact tmux-pane selection; never infer an interactive session from a PID."""

import asyncio
import json
import re
import shlex
import shutil
import sys
from pathlib import Path

from pydantic import Field

from kirabridge.bridge_core.models import BridgeError, Input, UncertainExecution
from kirabridge.filesystem_manager import PathScope
from kirabridge.terminal_manager import check_executable


class SessionInput(Input):
    pane_id: str = Field(pattern=r"^(%[0-9]+|terminal:[0-9]+:ttys[0-9]+)$")
    expected_pid: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=16384)
    submit: bool = True


class SessionOpen(Input):
    cwd: str = Field(min_length=1, max_length=4096)
    argv: list[str] = Field(default_factory=list, max_length=256)


class SessionManager:
    def __init__(self, bridge, *, socket_name=None):
        self.bridge, self.socket_name = bridge, socket_name
        self.lock = asyncio.Lock()
        self.observed_outputs = {}

    async def native(self, source, *, mutation=False):
        if sys.platform != "darwin":
            raise BridgeError("session_transport_unavailable", "Terminal.app requires macOS")
        child = await asyncio.create_subprocess_exec(
            "/usr/bin/osascript",
            "-l",
            "JavaScript",
            "-e",
            source,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(10):
                stdout, stderr = await child.communicate()
            if child.returncode:
                detail = stderr.decode("utf-8", "replace")[:1024]
                code = (
                    "session_automation_denied"
                    if "1743" in detail
                    else "session_transport_unavailable"
                )
                raise BridgeError(code, detail or "Terminal.app automation failed")
            if len(stdout) > 1048576:
                raise BridgeError("output_limit", "Terminal.app response too large")
            return json.loads(stdout)
        except (TimeoutError, json.JSONDecodeError):
            if mutation:
                raise UncertainExecution(
                    "session_input_unknown", "Outcome unknown; do not resend"
                ) from None
            raise BridgeError(
                "session_transport_unavailable", "Terminal.app did not return valid data"
            ) from None
        finally:
            if child.returncode is None:
                child.kill()
                await child.wait()

    async def terminal_catalog(self):
        if sys.platform != "darwin":
            return []
        rows = await self.native("""const app = Application("Terminal");
JSON.stringify(app.running() ? app.windows().flatMap(w => w.tabs().map(t => ({
window_id:w.id(), tty:t.tty(), busy:t.busy()
}))) : []);""")
        child = await asyncio.create_subprocess_exec(
            "/bin/ps",
            "-axo",
            "pid=,ppid=,tty=",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        async with asyncio.timeout(3):
            output, _ = await child.communicate()
        processes = [line.split() for line in output.decode().splitlines()]
        sessions = []
        for row in rows[:100]:
            tty = Path(row["tty"]).name
            if not re.fullmatch(r"ttys[0-9]+", tty):
                continue
            members = [(int(p), int(parent)) for p, parent, t in processes if t == tty]
            pids = {p for p, _ in members}
            roots = [p for p, parent in members if parent not in pids]
            if not roots:
                continue
            sessions.append(
                {
                    "pane_id": f"terminal:{int(row['window_id'])}:{tty}",
                    "expected_pid": min(roots),
                    "tty": row["tty"],
                    "transport": "terminal_app",
                    "busy": row["busy"],
                    "agent_identity_verified": False,
                }
            )
        return sessions

    @staticmethod
    def native_target(pane_id):
        _, window, tty = pane_id.split(":")
        return f"""const app = Application("Terminal");
const wins = app.windows().filter(w => w.id() === {int(window)});
if (wins.length !== 1) throw Error("Selected window no longer exists");
const tabs = wins[0].tabs().filter(t => t.tty() === {json.dumps("/dev/" + tty)});
if (tabs.length !== 1) throw Error("Selected tab no longer exists");
const tab = tabs[0];"""

    async def open(self, principal, args):
        policy = self.bridge.security.principal(principal, "session.open")
        self.bridge.security.principal(principal, "terminal.execute")
        PathScope(policy.terminal_roots or policy.roots).split(args.cwd)
        cwd = str(Path(args.cwd).resolve(strict=True))
        PathScope(policy.terminal_roots or policy.roots).split(cwd)
        argv = list(args.argv)
        if argv:
            argv[0] = check_executable(
                argv[0],
                policy.executables,
                policy.allow_any_executable,
                self.bridge.terminal.environment["PATH"],
            )
        if any("\x00" in arg for arg in argv):
            raise BridgeError("invalid_arguments", "NUL in command")
        command = "cd -- " + shlex.quote(cwd)
        if argv:
            command += " && " + shlex.join(argv)
        async with self.lock:
            result = await self.native(
                'const app=Application("Terminal"); const tab=app.doScript('
                + json.dumps(command)
                + "); JSON.stringify({tty:tab.tty(),opened:true});",
                mutation=True,
            )
            for _ in range(20):
                sessions = await self.terminal_catalog()
                selected = next((s for s in sessions if s["tty"] == result["tty"]), None)
                if selected:
                    return {**selected, "opened": True, "agent_processed": False}
                await asyncio.sleep(0.05)
        return {**result, "session_handle_pending": True, "agent_processed": False}

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
        native_rows, errors = [], {}
        if sys.platform == "darwin" and self.socket_name is None:
            try:
                native_rows = await self.terminal_catalog()
            except BridgeError as exc:
                errors["terminal_app"] = {"code": exc.code, "message": str(exc)}
        try:
            raw = await self.command(
                "list-panes",
                "-a",
                "-F",
                "#{pane_id}\t#{pane_pid}\t#{pane_tty}\t#{pane_current_command}",
            )
        except BridgeError as exc:
            return {
                "transport": "terminal_app" if native_rows else "tmux",
                "status": "available" if native_rows else exc.code,
                "sessions": native_rows,
                "transport_errors": {**errors, "tmux": {"code": exc.code}},
                "scope": "Exact Terminal.app tabs and tmux panes; existing sessions preserved",
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
            "transport": "terminal_app_and_tmux" if native_rows else "tmux",
            "status": "available",
            "sessions": native_rows + rows,
            "transport_errors": errors,
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
        if pane_id.startswith("terminal:"):
            text = await self.native(
                self.native_target(pane_id) + "\nJSON.stringify(tab.contents().slice(-65536));"
            )
            text = text.encode("utf-8")[-65536:].decode("utf-8", "replace")
        else:
            text = await self.command("capture-pane", "-p", "-t", pane_id, "-S", "-200")
        return {
            "pane_id": pane_id,
            "expected_pid": expected_pid,
            "text": text,
            "scope": "selected terminal output; not proof of project completion",
        }

    async def send(self, principal, args):
        self.bridge.security.principal(principal, "session.input")
        self.bridge.security.principal(principal, "terminal.execute")
        if "\x00" in args.text:
            raise BridgeError("invalid_arguments", "NUL in input")
        async with self.lock:
            await self.selected(principal, args.pane_id, args.expected_pid)
            if args.pane_id.startswith("terminal:"):
                if not args.submit:
                    raise BridgeError(
                        "session_submit_required", "Terminal.app input submits a line"
                    )
                await self.native(
                    self.native_target(args.pane_id)
                    + "\napp.doScript("
                    + json.dumps(args.text)
                    + ", {in:tab}); JSON.stringify({sent:true});",
                    mutation=True,
                )
            else:
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
