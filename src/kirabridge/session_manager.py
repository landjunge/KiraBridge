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
from kirabridge.platform_adapters.desktop import DESKTOP_MESSAGES, MacDesktop
from kirabridge.terminal_manager import check_executable


class SessionReference(Input):
    pane_id: str = Field(pattern=r"^(%[0-9]+|terminal:[0-9]+:ttys[0-9]+)$")
    expected_pid: int = Field(gt=0)


class SessionRead(SessionReference):
    max_bytes: int = Field(default=65536, ge=1, le=65536)


class SessionInput(SessionReference):
    text: str = Field(min_length=1, max_length=16384)
    submit: bool = True
    require_idle: bool = False


class SessionOpen(Input):
    cwd: str = Field(min_length=1, max_length=4096)
    argv: list[str] = Field(default_factory=list, max_length=256)
    window_authorization: str = Field(default="", max_length=128)


class SessionManager:
    def __init__(self, bridge, *, socket_name=None):
        self.bridge, self.socket_name = bridge, socket_name
        self.lock = asyncio.Lock()
        self.observed_outputs = {}
        self.desktop = MacDesktop()

    async def native(self, source, *, mutation=False):
        if sys.platform != "darwin":
            raise BridgeError("session_transport_unavailable", "Terminal.app requires macOS")
        await self.desktop.require_interactive()
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
                    else "session_busy"
                    if "Selected terminal is busy" in detail
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
            "pid=,ppid=,tty=,comm=",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        async with asyncio.timeout(3):
            output, _ = await child.communicate()
        processes = [
            parts
            for line in output.decode().splitlines()
            if len(parts := line.split(None, 3)) == 4 and parts[0].isdigit() and parts[1].isdigit()
        ]
        sessions = []
        for row in rows[:100]:
            tty = Path(row["tty"]).name
            if not re.fullmatch(r"ttys[0-9]+", tty):
                continue
            members = [(int(p), int(parent)) for p, parent, t, _ in processes if t == tty]
            pids = {p for p, _ in members}
            roots = [p for p, parent in members if parent not in pids]
            if len(roots) != 1:
                continue
            sessions.append(
                {
                    "pane_id": f"terminal:{int(row['window_id'])}:{tty}",
                    "window_id": int(row["window_id"]),
                    "expected_pid": roots[0],
                    "tty": row["tty"],
                    "transport": "terminal_app",
                    "busy": row["busy"],
                    "agent_identity_verified": False,
                    "processes": [
                        {"pid": int(p), "ppid": int(parent), "name": Path(comm).name}
                        for p, parent, t, comm in processes
                        if t == tty
                    ],
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

    async def open(self, principal, args, *, task_id=None):
        policy = self.bridge.security.principal(principal, "session.open")
        self.bridge.security.principal(principal, "terminal.execute")
        self.bridge.security.validate_window(principal, task_id, args)
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
            self.bridge.security.check_window(principal, task_id, args)
            try:
                result = await self.native(
                    'const app=Application("Terminal"); const tab=app.doScript('
                    + json.dumps(command)
                    + "); JSON.stringify({tty:tab.tty(),opened:true});",
                    mutation=True,
                )
            except BaseException:
                self.bridge.security.window_outcome(principal, task_id, "unknown")
                raise
            self.bridge.security.window_outcome(principal, task_id, "opened")
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
                "status": "available"
                if native_rows
                else errors.get("terminal_app", {}).get("code", exc.code),
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
        native_error = catalog.get("transport_errors", {}).get("terminal_app", {})
        if pane_id.startswith("terminal:") and native_error.get("code") in DESKTOP_MESSAGES:
            raise BridgeError(native_error["code"], native_error["message"])
        matches = [
            row
            for row in catalog["sessions"]
            if row["pane_id"] == pane_id and row["expected_pid"] == expected_pid
        ]
        if len(matches) == 1:
            return matches[0]
        raise BridgeError(
            "session_selection_changed",
            "Select an exact current pane_id and expected_pid from session_catalog",
        )

    async def read(self, principal, pane_id, expected_pid, *, max_bytes=65536):
        await self.selected(principal, pane_id, expected_pid)
        if pane_id.startswith("terminal:"):
            text = await self.native(
                self.native_target(pane_id) + "\nJSON.stringify(tab.contents().slice(-65536));"
            )
        else:
            text = await self.command("capture-pane", "-p", "-t", pane_id, "-S", "-200")
        text = text.encode("utf-8")[-max_bytes:].decode("utf-8", "ignore")
        return {
            "pane_id": pane_id,
            "expected_pid": expected_pid,
            "text": text,
            "scope": "selected terminal output; not proof of project completion",
        }

    def assigned_agent(self, selected):
        """Recognized CLI input always needs the persistent original binding."""
        selected = selected or {}
        matches = [
            p for p in selected.get("processes", []) if p["name"] in self.bridge.config.agents
        ]
        if not matches:
            return None
        if len(matches) != 1:
            raise BridgeError("visible_target_ambiguous", "Multiple CLI agents in this terminal")
        process = matches[0]
        binding = self.bridge.config.visible_handoffs.bindings.get(process["name"])
        if not binding or (binding.pane_id, binding.expected_pid, binding.agent_pid) != (
            selected.get("pane_id"),
            selected.get("expected_pid"),
            process["pid"],
        ):
            raise BridgeError(
                "visible_target_changed", "CLI input requires its assigned original window"
            )
        return process["name"]

    async def read_observed(self, principal, pane_id, expected_pid, *, max_bytes=65536):
        from kirabridge.bridge_core.models import digest

        result = await self.read(principal, pane_id, expected_pid, max_bytes=max_bytes)
        key, fingerprint = (principal, pane_id, expected_pid), digest(result["text"])
        if self.observed_outputs.get(key) != fingerprint:
            if len(self.observed_outputs) >= 128:
                self.observed_outputs.pop(next(iter(self.observed_outputs)))
            self.observed_outputs[key] = fingerprint
            with self.bridge.store.transaction():
                self.bridge.store.audit(
                    "terminal.output",
                    principal,
                    None,
                    {
                        "pane_id": pane_id,
                        "expected_pid": expected_pid,
                        "text": result["text"],
                        "content_sha256": fingerprint,
                    },
                )
        return result

    def native_focus(self, pane_id):
        window, tty = pane_id.split(":")[1:]
        return (
            self.native_target(pane_id)
            + f"""
const w=wins[0]; w.selectedTab=tab; w.index=1; app.activate(); delay(0.15);
const se=Application("System Events");
function checkFocus() {{
 if(!se.processes.byName("Terminal").frontmost() || app.windows()[0].id()!=={int(window)} ||
    app.windows()[0].selectedTab().tty()!=={json.dumps("/dev/" + tty)})
    throw Error("Selected terminal focus changed; do not repeat input");
}}
checkFocus();"""
        )

    async def insert(self, principal, args):
        """Paste literal input without Return; used by the durable visible handoff."""
        self.bridge.security.principal(principal, "session.input")
        self.bridge.security.principal(principal, "terminal.execute")
        if args.submit or "\x00" in args.text:
            raise BridgeError("invalid_arguments", "Insertion must not submit a line")
        async with self.lock:
            selected = await self.selected(principal, args.pane_id, args.expected_pid)
            self.assigned_agent(selected)
            if args.require_idle and selected.get("busy", True):
                raise BridgeError("session_busy", "Selected terminal is not an idle shell")
            if args.pane_id.startswith("terminal:"):
                # Preserve every clipboard format. Restore only if nobody changed it meanwhile.
                async with self.bridge.clipboard.lock:
                    await self.native(
                        self.native_focus(args.pane_id)
                        + """
ObjC.import("AppKit");
const pb=$.NSPasteboard.generalPasteboard, saved=[]; let totalBytes=0;
const items=pb.pasteboardItems;
if(items.count>32) throw Error("Clipboard too large to preserve");
for(let i=0;i<items.count;i++) {
 const item=items.objectAtIndex(i), formats=[];
 if(item.types.count>64) throw Error("Clipboard too large to preserve");
 for(let j=0;j<item.types.count;j++) {
  const type=item.types.objectAtIndex(j), data=item.dataForType(type);
  if(data && data.length>1048576) throw Error("Clipboard too large to preserve");
  totalBytes+=data ? data.length : 0;
  if(totalBytes>4194304) throw Error("Clipboard too large to preserve");
  formats.push([type,data]);
 }
 saved.push(formats);
}
pb.clearContents;
pb.setStringForType("""
                        + json.dumps(args.text)
                        + """, $.NSPasteboardTypeString);
const generation=pb.changeCount;
try {
 checkFocus();
 // Invoke the literal Paste menu action; keyboard modifiers can select escaped paste.
 const editItem=se.processes.byName("Terminal").menuBars()[0].menuBarItems()[3];
 editItem.click();
 const edit=editItem.menus()[0];
 const paste=edit.menuItems()[6];
 if(!["Einsetzen","Paste"].includes(paste.name()))
  throw Error("Literal Paste menu action unavailable");
 if(!paste.enabled()) throw Error("Literal Paste action is disabled; no paste sent");
 paste.click();
 let echoed=false;
 for(let attempt=0;attempt<40;attempt++) {
  delay(0.1); checkFocus();
  const screen=tab.contents();
  if(screen.includes("""
                        + json.dumps(args.text.split("\n")[-1])
                        + """) || screen.includes("""
                        + json.dumps(f"[Pasted Content {len(args.text)} chars]")
                        + """)) {
   echoed=true; break;
  }
 }
 if(!echoed) throw Error("Paste not observed before clipboard restoration; no Return sent");
}
finally {
 if(pb.changeCount===generation) {
  const restored=$.NSMutableArray.alloc.init;
  for(const formats of saved) {
   const item=$.NSPasteboardItem.alloc.init;
   for(const [type,data] of formats) if(data) item.setDataForType(data,type);
   restored.addObject(item);
  }
  pb.clearContents;
  if(restored.count) pb.writeObjects(restored);
 }
}
JSON.stringify({paste_event_sent:true,return_sent:false});""",
                        mutation=True,
                    )
            else:
                await self.command(
                    "send-keys", "-t", args.pane_id, "-l", "--", args.text, mutation=True
                )
        return {"paste_event_sent": True, "return_sent": False, "agent_confirmed": False}

    async def press_return(self, principal, pane_id, expected_pid):
        """Separate, non-replayed submit action after checked insertion."""
        self.bridge.security.principal(principal, "session.input")
        self.bridge.security.principal(principal, "terminal.execute")
        async with self.lock:
            self.assigned_agent(await self.selected(principal, pane_id, expected_pid))
            if pane_id.startswith("terminal:"):
                await self.native(
                    self.native_focus(pane_id)
                    + "\ncheckFocus(); se.keyCode(36); JSON.stringify({return_sent:true});",
                    mutation=True,
                )
            else:
                await self.command("send-keys", "-t", pane_id, "Enter", mutation=True)
        return {"return_sent": True, "agent_confirmed": False}

    async def send(self, principal, args, *, task_id=None):
        self.bridge.security.principal(principal, "session.input")
        self.bridge.security.principal(principal, "terminal.execute")
        if "\x00" in args.text:
            raise BridgeError("invalid_arguments", "NUL in input")
        async with self.lock:
            selected = await self.selected(principal, args.pane_id, args.expected_pid)
            if self.assigned_agent(selected):
                raise BridgeError(
                    "visible_handoff_required", "CLI handoffs require the central route"
                )
            if args.require_idle and selected.get("busy", True):
                raise BridgeError("session_busy", "Selected terminal is not an idle shell")
            if args.pane_id.startswith("terminal:"):
                if not args.submit:
                    raise BridgeError(
                        "session_submit_required", "Terminal.app input submits a line"
                    )
                args = self.bridge.tasks.input_policy.dispatch(principal, args, task_id)
                await self.native(
                    self.native_target(args.pane_id)
                    + (
                        '\nif(tab.busy()) throw Error("Selected terminal is busy");'
                        if args.require_idle
                        else ""
                    )
                    + "\napp.doScript("
                    + json.dumps(args.text)
                    + ", {in:tab}); JSON.stringify({sent:true});",
                    mutation=True,
                )
            else:
                args = self.bridge.tasks.input_policy.dispatch(principal, args, task_id)
                argv = ["send-keys", "-t", args.pane_id, "-l", "--", args.text]
                if args.submit:
                    argv += [";", "send-keys", "-t", args.pane_id, "Enter"]
                await self.command(*argv, mutation=True)
            self.bridge.tasks.input_policy.sent(principal, task_id)
        return {
            "pane_id": args.pane_id,
            "expected_pid": args.expected_pid,
            "input_handed_to_transport": True,
            "agent_processed": False,
            "submitted": args.submit,
        }
