"""Existing Terminal.app transport, independent of principal policy, queue and grants."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.platform_adapters.desktop import MacDesktop


class TerminalAppTransport:
    def __init__(self, clipboard_lock, *, desktop=None):
        self.clipboard_lock = clipboard_lock
        self.desktop = desktop or MacDesktop()

    @property
    def available(self):
        return sys.platform == "darwin"

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
                    else "visible_target_changed"
                    if "Selected target identity changed" in detail
                    else "visible_input_not_empty"
                    if "Selected terminal has existing input" in detail
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

    async def catalog(self):
        if sys.platform != "darwin":
            return []
        rows = await self.native("""const app = Application("Terminal");
    JSON.stringify(app.running() ? app.windows().flatMap(w => w.tabs().map(t => ({
    window_id:w.id(), tty:t.tty(), busy:t.busy()
    }))) : []);""")
        child = await asyncio.create_subprocess_exec(
            "/bin/ps",
            "-axo",
            "uid=,pid=,ppid=,tty=,comm=",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(3):
                output, _ = await child.communicate()
        finally:
            if child.returncode is None:
                try:
                    child.kill()
                except ProcessLookupError:
                    pass
                await child.wait()
        processes = [
            parts
            for line in output.decode().splitlines()
            if len(parts := line.split(None, 4)) == 5 and all(part.isdigit() for part in parts[:3])
        ]
        sessions = []
        for row in rows[:100]:
            tty = Path(row["tty"]).name
            if not re.fullmatch(r"ttys[0-9]+", tty):
                continue
            all_members = [
                (int(owner), int(p), int(parent), comm)
                for owner, p, parent, t, comm in processes
                if t == tty
            ]
            members = [(p, parent) for owner, p, parent, _ in all_members if owner == os.getuid()]
            all_pids = {p for _, p, _, _ in all_members}
            legacy_roots = [
                p
                for owner, p, parent, comm in all_members
                if owner == 0 and parent not in all_pids and Path(comm).name == "login"
            ]
            pids = {p for p, _ in members}
            roots = [p for p, parent in members if parent not in pids]
            if len(roots) != 1:
                continue
            if len(legacy_roots) == 1:
                parents = {p: parent for _, p, parent, _ in all_members}
                ancestor, seen = roots[0], set()
                while ancestor in parents and ancestor not in seen and ancestor != legacy_roots[0]:
                    seen.add(ancestor)
                    ancestor = parents[ancestor]
                if ancestor != legacy_roots[0]:
                    legacy_roots = []
            sessions.append(
                {
                    "pane_id": f"terminal:{int(row['window_id'])}:{tty}",
                    "window_id": int(row["window_id"]),
                    "expected_pid": roots[0],
                    **({"legacy_expected_pid": legacy_roots[0]} if len(legacy_roots) == 1 else {}),
                    "process_owner_verified": True,
                    "tty": row["tty"],
                    "transport": "terminal_app",
                    "busy": row["busy"],
                    "agent_identity_verified": False,
                    "processes": [
                        {"pid": int(p), "ppid": int(parent), "name": Path(comm).name}
                        for owner, p, parent, t, comm in processes
                        if t == tty and int(owner) == os.getuid()
                    ],
                }
            )
        return sessions

    @staticmethod
    def native_target(pane_id):
        _, window, tty = pane_id.split(":")
        return f"""const app = Application("Terminal");
    if (!app.running()) throw Error("Selected Terminal.app is not running");
    const wins = app.windows().filter(w => w.id() === {int(window)});
    if (wins.length !== 1) throw Error("Selected window no longer exists");
    const tabs = wins[0].tabs().filter(t => t.tty() === {json.dumps("/dev/" + tty)});
    if (tabs.length !== 1) throw Error("Selected tab no longer exists");
    const tab = tabs[0];"""

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

    async def insert(self, pane_id, text):
        async with self.clipboard_lock:
            await self.native(
                self.native_focus(pane_id)
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
                + json.dumps(text)
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
                + json.dumps(text.split("\n")[-1])
                + """) || screen.includes("""
                + json.dumps(f"[Pasted Content {len(text)} chars]")
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

    async def read(self, pane_id):
        return await self.native(
            self.native_target(pane_id) + "\nJSON.stringify(tab.contents().slice(-65536));"
        )

    async def open(self, command):
        return await self.native(
            'const app=Application("Terminal"); const tab=app.doScript('
            + json.dumps(command)
            + "); app.activate(); JSON.stringify({tty:tab.tty(),opened:true});",
            mutation=True,
        )

    async def process_identity(self, pid):
        child = await asyncio.create_subprocess_exec(
            "/bin/ps",
            "-p",
            str(int(pid)),
            "-o",
            "uid=,tty=,lstart=",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(3):
                raw, _ = await child.communicate()
        finally:
            if child.returncode is None:
                child.kill()
                await child.wait()
        identity = " ".join(raw.decode().split())
        if child.returncode or not identity.startswith(str(os.getuid()) + " "):
            raise BridgeError("visible_target_changed", "Selected target process identity changed")
        return identity

    async def send_confirmed(self, row, text, identity):
        """Check process start time/UID/TTY and empty input in the same native dispatch."""
        if identity.split()[1] != Path(row["tty"]).name:
            raise BridgeError("visible_target_changed", "Selected process TTY changed")
        from kirabridge.platform_adapters.shell_prompt import empty_shell_prompt

        if not empty_shell_prompt(await self.read(row["pane_id"])):
            raise BridgeError("visible_input_not_empty", "Selected terminal has existing input")
        command = f"/bin/ps -p {int(row['expected_pid'])} -o uid=,tty=,lstart="
        return await self.native(
            self.native_target(row["pane_id"])
            + "\nconst host=Application.currentApplication(); host.includeStandardAdditions=true;"
            + "\nconst observed=host.doShellScript("
            + json.dumps(command)
            + ").trim().replace(/\\s+/g,' ');"
            + "\nif(observed!=="
            + json.dumps(identity)
            + ") throw Error('Selected target identity changed');"
            + "\nif(tab.busy()) throw Error('Selected terminal is busy');"
            + "\n"
            + r"const last=tab.contents().replace(/\n+$/,'').split('\n').pop().replace(/\r$/,'');"
            + "\n"
            + r"if(!last.endsWith('KiraBridge visible % ') && "
            + r"!/^[^\n%$#]{1,240}[%$#] $/.test(last)) "
            + "throw Error('Selected terminal has existing input');"
            + "\nwins[0].selectedTab=tab; wins[0].index=1; app.activate();"
            + "\napp.doScript("
            + json.dumps(text)
            + ", {in:tab}); JSON.stringify({sent:true});",
            mutation=True,
        )

    async def press_return(self, pane_id):
        await self.native(
            self.native_focus(pane_id)
            + "\ncheckFocus(); se.keyCode(36); JSON.stringify({return_sent:true});",
            mutation=True,
        )

    async def send(self, pane_id, text, *, submit, require_idle):
        if not submit:
            raise BridgeError("session_submit_required", "Terminal.app input submits a line")
        await self.native(
            self.native_target(pane_id)
            + ('\nif(tab.busy()) throw Error("Selected terminal is busy");' if require_idle else "")
            + "\napp.doScript("
            + json.dumps(text)
            + ", {in:tab}); JSON.stringify({sent:true});",
            mutation=True,
        )
