"""Existing Terminal.app transport, independent of principal policy, queue and grants."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.platform_adapters.clipboard_lease import clipboard_lease
from kirabridge.platform_adapters.desktop import MacDesktop


class TerminalAppTransport:
    def __init__(self, clipboard_lock, *, desktop=None, clipboard_owner=clipboard_lease):
        self.clipboard_lock = clipboard_lock
        self.desktop = desktop or MacDesktop()
        self.clipboard_owner = clipboard_owner

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
            "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(15 if mutation else 10):
                stdout, stderr = await child.communicate(source.encode("utf-8"))
            if child.returncode:
                detail = stderr.decode("utf-8", "replace")[:1024]
                code = (
                    "session_automation_denied"
                    if "1743" in detail
                    else "visible_target_changed"
                    if "Selected target identity changed" in detail
                    else "visible_focus_changed"
                    if "Selected terminal focus changed" in detail
                    else "clipboard_changed"
                    if "Selected terminal clipboard changed" in detail
                    else "visible_input_changed"
                    if "Selected terminal input changed" in detail
                    else "visible_input_not_empty"
                    if "Selected terminal has existing input" in detail
                    else "visible_paste_unconfirmed"
                    if "Paste not observed" in detail
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
                reaping = asyncio.create_task(child.wait())
                cancelled = False
                while not reaping.done():
                    try:
                        await asyncio.shield(reaping)
                    except asyncio.CancelledError:
                        cancelled = True
                reaping.result()
                if cancelled:
                    raise asyncio.CancelledError

    async def window_inventory(self):
        """Unfiltered native window IDs, including windows without a usable shell PID."""
        return await self.native(
            'const app=Application("Terminal"), running=app.running(); '
            "JSON.stringify({running:running,windows:running ? app.windows().map(w=>({"
            "window_id:w.id(),ttys:w.tabs().map(t=>t.tty())})) : []});"
        )

    async def process_ids(self):
        """Observe all OS PIDs; an error or partial/empty list is never absence proof."""
        if not self.available:
            raise BridgeError("session_transport_unavailable", "Native PID evidence requires macOS")
        child = None
        try:
            child = await asyncio.create_subprocess_exec(
                "/bin/ps",
                "-axo",
                "pid=",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            async with asyncio.timeout(3):
                output, error = await child.communicate()
            lines = output.split()
            if child.returncode != 0 or error.strip() or not lines or len(output) > 1048576:
                raise BridgeError(
                    "visible_absence_unproven", "Complete OS PID inventory unavailable"
                )
            if any(not pid.isdigit() for pid in lines) or len(set(lines)) != len(lines):
                raise BridgeError("visible_absence_unproven", "Invalid OS PID inventory")
            return frozenset(int(pid) for pid in lines)
        except (OSError, TimeoutError):
            raise BridgeError("visible_absence_unproven", "OS PID observation failed") from None
        finally:
            if child is not None and child.returncode is None:
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
                        {"pid": int(p), "ppid": int(parent), "name": Path(comm).name, "image": comm}
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
    const targetWindow = app.windows.byId({int(window)});
    const tabs = targetWindow.tabs().filter(t => t.tty() === {json.dumps("/dev/" + tty)});
    if (tabs.length !== 1) throw Error("Selected tab no longer exists");
    const tab = tabs[0];"""

    def native_focus(self, pane_id):
        window, tty = pane_id.split(":")[1:]
        return (
            self.native_target(pane_id)
            + f"""
    const w=targetWindow; tab.selected=true; app.activate(); w.frontmost=true; delay(0.15);
    const se=Application("System Events");
    // Activation/index alone can restore another key window on macOS. Resolve the
    // exact Window menu entry; duplicate/changing titles never select a substitute.
    const currentWindows=app.windows();
    if(!currentWindows.length || currentWindows[0].id()!=={int(window)} ||
       currentWindows[0].selectedTab().tty()!=={json.dumps("/dev/" + tty)}) {{
     const title=w.name();
     if(app.windows().filter(v=>v.name()===title).length!==1)
      throw Error("Selected terminal focus changed: ambiguous window title");
     const windowMenus=se.processes.byName("Terminal").menuBars()[0].menuBarItems()
      .filter(m=>["Window","Fenster"].includes(m.name()));
     if(windowMenus.length!==1)
      throw Error("Selected terminal focus changed: Window menu unavailable");
     const menu=windowMenus[0].menus()[0], names=menu.menuItems.name();
     if(names.filter(name=>name===title).length!==1 || w.name()!==title)
      throw Error("Selected terminal focus changed: window menu target is not unique/current");
     const item=menu.menuItems.byName(title);
     if(!item.enabled()) throw Error("Selected terminal focus changed: window entry disabled");
     item.click(); delay(0.15);
    }}
    function checkFocus() {{
     const current=app.windows(), frontmost=se.processes.byName("Terminal").frontmost();
     const windowID=current.length ? current[0].id() : null;
     const currentTTY=current.length ? current[0].selectedTab().tty() : null;
     if(!frontmost || windowID!=={int(window)} || currentTTY!=={json.dumps("/dev/" + tty)})
      throw Error("Selected terminal focus changed; do not repeat input " + JSON.stringify({{
       frontmost:frontmost, window_id:windowID, tty:currentTTY,
       expected_window:{int(window)}, expected_tty:{json.dumps("/dev/" + tty)}
      }}));
    }}
    // Window activation is asynchronous. Acquire once with a bounded wait;
    // later pre-input checks remain immediate and never reassert focus.
    const focusDeadline=Date.now()+2000;
    while(true) {{
     try {{ checkFocus(); break; }}
     catch(error) {{ if(Date.now()>=focusDeadline) throw error; delay(0.05); }}
    }}"""
        )

    @staticmethod
    def native_identity_guard(identities):
        if not identities:
            return ""
        source = (
            "\nconst identityHost=Application.currentApplication(); "
            "identityHost.includeStandardAdditions=true;"
        )
        source += "\nfunction checkTargetIdentity(){"
        for pid, expected in identities.items():
            command = (
                f"/usr/bin/env LC_ALL=C /bin/ps -p {int(pid)} -o uid=,tty=,lstart=,ppid=,comm="
            )
            source += (
                "\n{let observedIdentity; try {observedIdentity=identityHost.doShellScript("
                + json.dumps(command)
                + ").trim().replace(/\\s+/g,' ');} catch(error) {"
                + "throw Error('Selected target identity changed');}"
                + "if(observedIdentity!=="
                + json.dumps(expected)
                + ") throw Error('Selected target identity changed');}"
            )
        return source + "\n}\ncheckTargetIdentity();"

    @staticmethod
    def native_screen_guard(expected_screen):
        if expected_screen is None:
            return ""
        # Freeze the current widget and its adjacent activity/footer, not scrollback.
        return (
            "\nif(Array.from(tab.contents()).slice(-8192).join('')!=="
            + json.dumps(expected_screen[-8192:])
            + ") throw Error('Selected terminal input changed');"
        )

    @staticmethod
    def native_paste_observation(text):
        # A historical suffix or empty trailing line is not a new paste observation.
        last = next((line for line in reversed(text.splitlines()) if line.strip()), "").rstrip()
        return (
            "\nfunction observedPaste(before, after) {"
            "const a=Array.from(before), b=Array.from(after); "
            "let first=0, endA=a.length, endB=b.length;"
            "while(first<endA && first<endB && a[first]===b[first]) first++;"
            "while(endA>first && endB>first && a[endA-1]===b[endB-1]) {endA--;endB--;}"
            "const changed=b.slice(first,endB).join('');"
            + "return ("
            + json.dumps(bool(last))
            + " && changed.includes("
            + json.dumps(last)
            + ")) || changed.includes("
            + json.dumps(f"[Pasted Content {len(text)} chars]")
            + ");}\n"
        )

    async def insert(self, pane_id, text, *, identity_guard=None, expected_screen=None):
        async with self.clipboard_lock:
            # The independent memory-only owner survives a killed/cancelled GUI
            # worker. native() reaps that worker before the lease requests restore.
            async with self.clipboard_owner(text) as lease:
                await self.native(
                    self.native_focus(pane_id)
                    + self.native_identity_guard(identity_guard)
                    + self.native_paste_observation(text)
                    + f"""
        ObjC.import("AppKit");
        function checkClipboard() {{
         if(Number($.NSPasteboard.generalPasteboard.changeCount)!=={int(lease.generation)})
          throw Error("Selected terminal clipboard changed; do not repeat input");
        }}
        checkClipboard(); checkFocus();
        const editItem=se.processes.byName("Terminal").menuBars()[0].menuBarItems()[3];
        // Validate the menu, then close tracking BEFORE Terminal Apple events.
        // AXPress targets this exact Paste item without leaving a menu open.
        editItem.click();
        const edit=editItem.menus()[0]; let paste;
        try {{
         paste=edit.menuItems()[6];
         if(!["Einsetzen","Paste"].includes(paste.name()))
          throw Error("Literal Paste menu action unavailable");
         if(!paste.enabled()) throw Error("Literal Paste action is disabled; no paste sent");
         if(!paste.actions.name().includes("AXPress"))
          throw Error("Literal Paste action is unavailable; no paste sent");
        }} finally {{ edit.actions.byName("AXCancel").perform(); }}
        if(typeof checkTargetIdentity === 'function') checkTargetIdentity();
        checkFocus(); checkClipboard();
"""
                    + self.native_screen_guard(expected_screen)
                    + """
        const beforePaste=tab.contents();
        paste.actions.byName("AXPress").perform();
        let echoed=false; const echoDeadline=Date.now()+4000;
        while(Date.now()<echoDeadline) {
         delay(0.1); checkFocus();
         if(observedPaste(beforePaste,tab.contents())) { echoed=true; break; }
        }
        if(!echoed) throw Error("Paste not observed; no Return sent");
        JSON.stringify({paste_event_sent:true,return_sent:false});""",
                    mutation=True,
                )

    async def read(self, pane_id):
        return await self.native(
            self.native_target(pane_id)
            + "\nJSON.stringify(Array.from(tab.contents()).slice(-65536).join(''));"
        )

    async def open(self, command):
        return await self.native(
            'const app=Application("Terminal"); const tab=app.doScript('
            + json.dumps(command)
            + "); app.activate(); JSON.stringify({tty:tab.tty(),opened:true});",
            mutation=True,
        )

    async def process_identity(self, pid, *, detailed=False):
        child = await asyncio.create_subprocess_exec(
            "/bin/ps",
            "-p",
            str(int(pid)),
            "-o",
            "uid=,tty=,lstart=,ppid=,comm=" if detailed else "uid=,tty=,lstart=",
            env={**os.environ, "LC_ALL": "C"} if detailed else None,
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
            + "\ntargetWindow.selectedTab=tab; targetWindow.index=1; app.activate();"
            + "\napp.doScript("
            + json.dumps(text)
            + ", {in:tab}); JSON.stringify({sent:true});",
            mutation=True,
        )

    async def press_return(self, pane_id, *, identity_guard=None, expected_screen=None):
        await self.native(
            self.native_focus(pane_id)
            + self.native_identity_guard(identity_guard)
            + "\ncheckFocus();"
            + self.native_screen_guard(expected_screen)
            + "\nse.keyCode(36); JSON.stringify({return_sent:true});",
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
