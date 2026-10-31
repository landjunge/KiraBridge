"""Existing Terminal.app transport, independent of principal policy, queue and grants."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.platform_adapters import reap_process
from kirabridge.platform_adapters.clipboard_lease import clipboard_lease
from kirabridge.platform_adapters.desktop import MacDesktop


def annotate_views(sessions: list[dict]) -> list[dict]:
    """Mark several on-screen views of one TTY and PID without merging them."""
    counts: dict[str, int] = {}
    for row in sessions:
        key = f"{row.get('tty')}:{row.get('expected_pid')}"
        row["session_key"] = key
        row["view_id"] = row.get("window_id")
        counts[key] = counts.get(key, 0) + 1
    for row in sessions:
        row["view_count"] = counts[row["session_key"]]
        row["duplicate_view"] = row["view_count"] > 1
    return sessions


def attach_visual_windows(rows: list[dict]) -> list[dict]:
    """Group Terminal.app scripting objects that share one on-screen window.

    With system tabbing set to always, each tab is one scripting window and
    windows() is not the number of windows on screen. Tabs of one window share
    bounds. A scripting window that already contains several tabs stays one group.
    """
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        bounds = row.get("bounds") or {}
        if row.get("script_tab_count", 1) > 1:
            key = ("script", row.get("window_id"))
        else:
            key = (
                "bounds",
                bounds.get("x"),
                bounds.get("y"),
                bounds.get("width"),
                bounds.get("height"),
            )
            if None in key:
                key = ("script", row.get("window_id"))
        groups.setdefault(key, []).append(row)
    ui_count = len(groups)
    tty_count: dict[str, int] = {}
    for row in rows:
        if row.get("ended"):
            continue
        tty_count[row.get("tty") or ""] = tty_count.get(row.get("tty") or "", 0) + 1
    for members in groups.values():
        members.sort(
            key=lambda item: (
                item.get("index") or 0,
                item.get("tab_index_in_script_window") or 0,
                item.get("window_id") or 0,
            )
        )
        visual_id = min(item.get("window_id") or 0 for item in members)
        # Each scripting window reports its own tab as selected. The visible tab
        # is the frontmost scripting window, or the single selected tab when one
        # scripting window holds several tabs.
        fronts = [item for item in members if item.get("frontmost") is True]
        if not fronts and any(item.get("script_tab_count", 1) > 1 for item in members):
            fronts = [item for item in members if item.get("selected") is True]
        if len(members) == 1 and not fronts:
            fronts = members
        for index, item in enumerate(members, start=1):
            item["visual_window_id"] = visual_id
            item["tab_index"] = index
            item["tab_count"] = len(members)
            item["ui_window_count"] = ui_count
            item["tab_selected"] = len(fronts) == 1 and item is fronts[0]
            item["identity_ambiguous"] = tty_count.get(item.get("tty") or "", 0) > 1
            if len(members) > 1 and len(fronts) != 1:
                item["tab_selected"] = False
                item["selection_ambiguous"] = True
    return rows


class TerminalAppTransport:
    def __init__(self, clipboard_lock, *, desktop=None, clipboard_owner=clipboard_lease):
        self.clipboard_lock = clipboard_lock
        self.desktop = desktop or MacDesktop()
        self.clipboard_owner = clipboard_owner
        self.last_catalog_incomplete = False

    @property
    def available(self):
        return sys.platform == "darwin"

    async def native(self, source, *, mutation=False):
        if sys.platform != "darwin":
            raise BridgeError("session_transport_unavailable", "Terminal.app requires macOS")
        guard = getattr(self, "platform_guard", None)
        if guard is not None:
            guard()
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
            was_cancelled = isinstance(sys.exc_info()[1], asyncio.CancelledError)
            try:
                await reap_process(child, process_group=False)
            except BridgeError:
                if was_cancelled:
                    raise asyncio.CancelledError from None
                if mutation:
                    raise UncertainExecution(
                        "session_input_unknown", "Worker cleanup unknown; do not resend"
                    ) from None
                raise BridgeError(
                    "session_transport_unavailable", "Terminal worker cleanup unconfirmed"
                ) from None

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
            if child is not None:
                try:
                    await reap_process(child, process_group=False)
                except BridgeError:
                    raise BridgeError(
                        "visible_absence_unproven", "PID observation cleanup unconfirmed"
                    ) from None

    async def catalog(self):
        if sys.platform != "darwin":
            return []
        rows = await self.native("""const app = Application("Terminal");
    JSON.stringify(app.running() ? app.windows().flatMap(w => {
     const b = w.bounds();
     return w.tabs().map((t, i) => ({
      window_id:w.id(), index:w.index(), frontmost:w.frontmost(),
      bounds:{x:b.x, y:b.y, width:b.width, height:b.height},
      script_tab_count:w.tabs().length, tab_index_in_script_window:i+1,
      tty:t.tty(), busy:t.busy(), selected:t.selected()
     }));
    }) : []);""")
        rows = attach_visual_windows(rows if isinstance(rows, list) else [])
        shared = {
            row.get("tty")
            for row in rows
            if sum(item.get("tty") == row.get("tty") for item in rows) > 1
        }
        if shared:
            ended = await self.ended_windows(
                [int(row["window_id"]) for row in rows if row.get("tty") in shared]
            )
            for row in rows:
                if int(row.get("window_id") or 0) in ended:
                    row["ended"] = True
            rows = attach_visual_windows(rows)
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
            await reap_process(child, process_group=False)
        processes = [
            parts
            for line in output.decode().splitlines()
            if len(parts := line.split(None, 4)) == 5 and all(part.isdigit() for part in parts[:3])
        ]
        sessions = []
        omitted = len(rows) > 100
        for row in rows[:100]:
            tty = Path(row["tty"]).name
            if not re.fullmatch(r"ttys[0-9]+", tty) or row.get("ended"):
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
                omitted = True
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
                    "visual_window_id": row.get("visual_window_id"),
                    "tab_index": row.get("tab_index"),
                    "tab_count": row.get("tab_count"),
                    "tab_selected": row.get("tab_selected"),
                    "ui_window_count": row.get("ui_window_count"),
                    "identity_ambiguous": bool(row.get("identity_ambiguous")),
                    "selection_ambiguous": bool(row.get("selection_ambiguous")),
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
        self.last_catalog_incomplete = omitted
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
    def native_input_tail(limit):
        """Read the current buffer tail, independently of the scroll viewport.

        Terminal's scripting dictionary defines ``contents`` as the currently
        visible viewport and ``history`` as the entire scrolling buffer. A
        scrolled viewport can contain old output while the current input lies
        at the buffer's end. Use one source for observation and native guards;
        never fall back to a different representation after a failed check.
        Bound both the intermediate UTF-16 slice and final Unicode-point tail.
        """
        return f"Array.from(tab.history().slice(-{2 * limit})).slice(-{limit}).join('')"

    @staticmethod
    def native_screen_guard(expected_screen):
        if expected_screen is None:
            return ""
        # Freeze the current input and adjacent footer using the same source as
        # read(), rather than comparing that observation against a stale viewport.
        return (
            "\nif("
            + TerminalAppTransport.native_input_tail(8192)
            + "!=="
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

    @staticmethod
    def validate_shell_paste_text(text):
        import unicodedata

        if not text or any(
            unicodedata.category(char) == "Cc" or char in "\u2028\u2029" for char in text
        ):
            raise BridgeError(
                "invalid_arguments", "Plain shell paste requires single-line text without controls"
            )

    async def shell_process_snapshot(self, tty):
        if not re.fullmatch(r"/dev/ttys[0-9]+", tty):
            raise BridgeError("visible_target_changed", "Invalid selected shell TTY")
        command = [
            "/bin/ps",
            "-t",
            tty.removeprefix("/dev/"),
            "-o",
            "uid=,pid=,ppid=,tty=,lstart=,comm=",
        ]
        child = await asyncio.create_subprocess_exec(
            *command,
            env={**os.environ, "LC_ALL": "C"},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(3):
                raw, error = await child.communicate()
            if child.returncode or error.strip() or not raw.strip() or len(raw) > 262144:
                raise BridgeError(
                    "visible_target_changed", "Complete selected TTY processes unavailable"
                )
            return {
                "command": command,
                "rows": sorted(
                    " ".join(line.split())
                    for line in raw.decode("utf-8").splitlines()
                    if line.strip()
                ),
            }
        finally:
            await reap_process(child, process_group=False)

    async def prepare_shell_paste(self, row):
        from kirabridge.platform_adapters.shell_prompt import empty_shell_prompt

        if row.get("busy", True) or not row.get("processes"):
            raise BridgeError("session_busy", "Selected shell must be positively idle")
        snapshot = await self.shell_process_snapshot(row["tty"])
        records = {}
        for line in snapshot["rows"]:
            parts = line.split(None, 9)
            if len(parts) != 10 or not all(value.isdigit() for value in parts[:3]):
                raise BridgeError("visible_target_changed", "Incomplete selected TTY identity")
            uid, pid, parent = map(int, parts[:3])
            if pid in records or parts[3] != Path(row["tty"]).name:
                raise BridgeError("visible_target_changed", "Ambiguous selected TTY identity")
            records[pid] = (
                uid,
                parent,
                parts[9],
                " ".join([parts[0], parts[3], *parts[4:9], parts[2], parts[9]]),
            )
        own = {pid: data for pid, data in records.items() if data[0] == os.getuid()}
        observed = {process["pid"]: process for process in row["processes"]}
        if set(own) != set(observed) or row["expected_pid"] not in own:
            raise BridgeError("visible_target_changed", "Selected process set changed")
        for pid, (_, parent, image, _) in own.items():
            process = observed[pid]
            if (
                Path(image).name.lstrip("-") not in {"zsh", "bash", "sh"}
                or process["ppid"] != parent
                or process["image"] != image
            ):
                raise BridgeError("visible_target_changed", "Selected shell image/parent changed")
        foreign = set(records) - set(own)
        boundary = own[row["expected_pid"]][1]
        if foreign and (
            foreign != {boundary}
            or records[boundary][0] != 0
            or Path(records[boundary][2]).name.lstrip("-") != "login"
        ):
            raise BridgeError("session_busy", "Other processes exist on selected TTY")
        screen = await self.read(row["pane_id"])
        if not empty_shell_prompt(screen):
            raise BridgeError(
                "visible_input_not_empty",
                "Cannot verify an empty shell prompt; existing or ambiguous input is preserved",
            )
        return {
            "identities": {pid: data[3] for pid, data in records.items()},
            "screen": screen,
            "snapshot": snapshot,
        }

    @staticmethod
    def native_shell_guard(snapshot):
        import shlex

        command = "/usr/bin/env LC_ALL=C " + shlex.join(snapshot["command"])
        return (
            "\nconst shellRows=identityHost.doShellScript("
            + json.dumps(command)
            + ").replace(/\\r\\n?/g,'\\n').trim().split(/\\n/).filter(s=>s.trim())"
            + ".map(s=>s.trim().replace(/\\s+/g,' ')).sort();"
            + "if(JSON.stringify(shellRows)!=="
            + json.dumps(json.dumps(snapshot["rows"], separators=(",", ":")))
            + ")throw Error('Selected target identity changed');"
            + "if(tab.busy())throw Error('Selected terminal is busy');"
        )

    async def insert(
        self, pane_id, text, *, identity_guard=None, expected_screen=None, shell_snapshot=None
    ):
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
"""
                    + (
                        self.native_shell_guard(shell_snapshot)
                        if shell_snapshot is not None
                        else ""
                    )
                    + "\ncheckFocus(); checkClipboard();"
                    + self.native_screen_guard(expected_screen)
                    + """
        const beforePaste="""
                    + self.native_input_tail(65536)
                    + """;
        paste.actions.byName("AXPress").perform();
        let echoed=false; const echoDeadline=Date.now()+4000;
        while(Date.now()<echoDeadline) {
         delay(0.1); checkFocus();
         if(observedPaste(beforePaste,"""
                    + self.native_input_tail(65536)
                    + """)) { echoed=true; break; }
        }
        if(!echoed) throw Error("Paste not observed; no Return sent");
        JSON.stringify({paste_event_sent:true,return_sent:false});""",
                    mutation=True,
                )

    async def ended_windows(self, window_ids):
        """Read only the last line of tabs that share a tty.

        A finished tab must not inherit a reused tty.
        """
        if not window_ids:
            return set()
        found = await self.native(
            "const app=Application('Terminal'); const ids="
            + json.dumps([int(value) for value in window_ids])
            + """;
            JSON.stringify(ids.filter(id => {
             const wins=app.windows().filter(w => w.id()===id);
             if (wins.length!==1) return false;
             const tail=((wins[0].selectedTab().contents()||'').replace(/\\s+$/,'')
              .split('\\n').pop()||'');
             return /^\\[(Prozess beendet|Process completed)\\]$/.test(tail);
            }));"""
        )
        return {int(value) for value in found} if isinstance(found, list) else set()

    async def front_tab(self):
        return await self.native(
            """const app=Application("Terminal");
            if(!app.running() || !app.windows().length) JSON.stringify({window_id:null,tty:null});
            else {
             const w=app.windows()[0];
             JSON.stringify({window_id:w.id(), tty:w.selectedTab().tty(), frontmost:w.frontmost()});
            }"""
        )

    async def focus(self, pane_id):
        return await self.native(
            self.native_focus(pane_id) + "\ncheckFocus(); JSON.stringify({focused:true});",
            mutation=True,
        )

    async def close_tab(self, pane_id):
        """Close one scripting tab. Other tab ids must still exist afterwards."""
        return await self.native(
            self.native_target(pane_id)
            + """
            const id = targetWindow.id();
            const others = app.windows().filter(w => w.id() !== id).map(w => w.id());
            if (!others.length) throw Error("Refusing to close the only Terminal tab");
            targetWindow.close();
            delay(0.3);
            const left = app.windows().map(w => w.id());
            const missing = others.filter(value => !left.includes(value));
            if (missing.length) throw Error("Close removed other tabs");
            JSON.stringify({closed:true, closed_window_id:id, remaining:left.length});
            """,
            mutation=True,
        )

    async def read(self, pane_id):
        return await self.native(
            self.native_target(pane_id) + "\nJSON.stringify(" + self.native_input_tail(65536) + ");"
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
            await reap_process(child, process_group=False)
        identity = " ".join(raw.decode().split())
        if child.returncode or not identity.startswith(str(os.getuid()) + " "):
            raise BridgeError("visible_target_changed", "Selected target process identity changed")
        return identity

    async def process_working_directory(self, pid, *, expected_identity):
        """Read one task-bound process CWD; never discover or follow another PID."""
        if (
            type(pid) is not int
            or pid <= 0
            or not isinstance(expected_identity, str)
            or not expected_identity.startswith(str(os.getuid()) + " ")
        ):
            raise BridgeError("visible_target_changed", "Task-owned process identity required")
        child = None
        readers = []

        async def bounded_pipe(stream, limit):
            data = bytearray()
            while len(data) <= limit:
                chunk = await stream.read(min(4096, limit + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            return bytes(data)

        try:
            if await self.process_identity(pid, detailed=True) != expected_identity:
                raise BridgeError("visible_target_changed", "Selected target identity changed")
            child = await asyncio.create_subprocess_exec(
                "/usr/sbin/lsof",
                "-a",
                "-p",
                str(pid),
                "-d",
                "cwd",
                "-F0pfn",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            async with asyncio.timeout(3):
                readers = [
                    asyncio.create_task(bounded_pipe(child.stdout, 65536)),
                    asyncio.create_task(bounded_pipe(child.stderr, 4096)),
                ]
                raw, error = await asyncio.gather(*readers)
                if len(raw) > 65536 or len(error) > 4096:
                    raise BridgeError("process_cwd_unavailable", "CWD observation exceeds limit")
                await child.wait()
            if await self.process_identity(pid, detailed=True) != expected_identity:
                raise BridgeError("visible_target_changed", "Selected target identity changed")
            fields = []
            for field in raw.split(b"\x00"):
                if field in {b"", b"\n"}:
                    continue
                fields.append(field.removeprefix(b"\n"))
            if (
                child.returncode
                or error
                or len(fields) != 3
                or fields[:2] != [f"p{pid}".encode(), b"fcwd"]
                or not fields[2].startswith(b"n/")
            ):
                raise BridgeError("process_cwd_unavailable", "Exact process CWD unavailable")
            cwd = fields[2][1:].decode("utf-8")
            if len(cwd.encode()) > 4096 or any(ord(char) < 32 or ord(char) == 127 for char in cwd):
                raise BridgeError("process_cwd_unavailable", "Unsupported CWD representation")
            return cwd
        except (OSError, TimeoutError, UnicodeError) as exc:
            raise BridgeError("process_cwd_unavailable", "Exact process CWD unavailable") from exc
        finally:
            for reader in readers:
                if not reader.done():
                    reader.cancel()
            if readers:
                await asyncio.gather(*readers, return_exceptions=True)
            if child is not None:
                await reap_process(child, process_group=False)

    async def send_confirmed(self, row, text, identity, *, before_transport=None):
        """Check process start time/UID/TTY and empty input in the same native dispatch."""
        if identity.split()[1] != Path(row["tty"]).name:
            raise BridgeError("visible_target_changed", "Selected process TTY changed")
        from kirabridge.platform_adapters.shell_prompt import empty_shell_prompt

        screen = await self.read(row["pane_id"])
        if not empty_shell_prompt(screen):
            raise BridgeError(
                "visible_input_not_empty",
                "Cannot verify an empty shell prompt; existing or ambiguous input is preserved",
            )
        command = f"/bin/ps -p {int(row['expected_pid'])} -o uid=,tty=,lstart="
        if before_transport is not None:
            await before_transport()
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
            # Use the accepted screen, not a second prompt parser that can drift.
            + self.native_screen_guard(screen)
            + "\ntargetWindow.selectedTab=tab; targetWindow.index=1; app.activate();"
            + "\nif(tab.busy()) throw Error('Selected terminal is busy');"
            + self.native_screen_guard(screen)
            + "\napp.doScript("
            + json.dumps(text)
            + ", {in:tab}); JSON.stringify({sent:true});",
            mutation=True,
        )

    async def press_return(
        self, pane_id, *, identity_guard=None, expected_screen=None, shell_snapshot=None
    ):
        await self.native(
            self.native_focus(pane_id)
            + self.native_identity_guard(identity_guard)
            + (self.native_shell_guard(shell_snapshot) if shell_snapshot is not None else "")
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
