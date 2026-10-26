"""Read-only proof for an explicitly requested visible macOS installation.

No window creation, input, focus changes, clipboard access or permission changes.
This is an OS observation, not cryptographic agent identity.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys


class VisibilityError(RuntimeError):
    pass


def process_identity(pid):
    result = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "pid=,ppid=,uid=,tty=,lstart=,comm="],
        capture_output=True,
        text=True,
        timeout=2,
    )
    fields = result.stdout.strip().split(None, 9)
    if (
        result.returncode
        or result.stderr.strip()
        or len(fields) != 10
        or not all(part.isdigit() for part in fields[:3])
        or int(fields[0]) != pid
    ):
        raise VisibilityError("Aktuelle Prozess-/TTY-Identität nicht nachgewiesen")
    return tuple(fields)


def inventory():
    source = """const app=Application("Terminal");
if(!app.running()) throw Error("Terminal is not running");
const windows=app.windows(), front=windows.length ? windows[0].id() : null;
JSON.stringify({frontmost:app.frontmost(),windows:windows.map(w=>({window_id:w.id(),
frontmost_window:w.id()===front,visible:w.visible()&&!w.miniaturized(),
tabs:w.tabs().map((t,i)=>({tab_index:i,tty:t.tty(),selected:t.tty()===w.selectedTab().tty()}))}))});"""
    result = subprocess.run(
        ["/usr/bin/osascript", "-l", "JavaScript", "-"],
        input=source,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode or result.stderr.strip() or len(result.stdout) > 1048576:
        raise VisibilityError("Sichtbares Terminalfenster nicht nachgewiesen; nichts aktivieren")
    try:
        value = json.loads(result.stdout)
        if (
            not isinstance(value, dict)
            or value.get("frontmost") is not True
            or not isinstance(value.get("windows"), list)
        ):
            raise ValueError
        return value["windows"]
    except (ValueError, TypeError):
        raise VisibilityError("Ungültige Terminal-Fensterinventur; nichts aktivieren") from None


def confirm_visible_terminal(expected=None):
    if sys.platform != "darwin" or not sys.stdin.isatty() or not sys.stderr.isatty():
        raise VisibilityError("Installation erfordert ein sichtbares macOS-Terminal mit echter TTY")
    try:
        tty = os.ttyname(sys.stderr.fileno())
        if tty != os.ttyname(sys.stdin.fileno()) or not re.fullmatch(r"/dev/ttys\d+", tty):
            raise VisibilityError("Ein-/Ausgabe gehören nicht zum gleichen macOS-Terminal")
        identities = []
        pid = os.getpid()
        for _ in range(16):
            current = process_identity(pid)
            if current[3] != tty.removeprefix("/dev/"):
                break
            if int(current[2]) != os.getuid() or pid in {int(i[0]) for i in identities}:
                raise VisibilityError("Terminal-Prozesszuordnung ist nicht eindeutig")
            identities.append(current)
            pid = int(current[1])
            if pid <= 1:
                break
        else:
            raise VisibilityError("Terminal-Prozesskette ist nicht vollständig")
        if not identities:
            raise VisibilityError("Installationsprozess ist nicht an diese TTY gebunden")
        matches = []
        for window in inventory():
            if not isinstance(window, dict) or type(window.get("window_id")) is not int:
                raise VisibilityError("Ungültige Fensteridentität")
            tabs = window.get("tabs")
            if not isinstance(tabs, list):
                raise VisibilityError("Ungültige Tab-Inventur")
            for tab in tabs:
                if not isinstance(tab, dict) or type(tab.get("tab_index")) is not int:
                    raise VisibilityError("Ungültige Tab-Identität")
                if tab.get("tty") == tty:
                    if (
                        window.get("visible") is not True
                        or window.get("frontmost_window") is not True
                        or tab.get("selected") is not True
                    ):
                        raise VisibilityError("Installationsfenster ist nicht sichtbar")
                    matches.append((window["window_id"], tab["tab_index"]))
        if len(matches) != 1:
            raise VisibilityError("Keine eindeutige sichtbare Fenster-/Tab-/TTY-Zuordnung")
        if any(process_identity(int(item[0])) != item for item in identities):
            raise VisibilityError("Terminal-Prozessidentität während Prüfung geändert")
        proof = {"window_id": matches[0][0], "tab_index": matches[0][1], "tty": tty}
        if expected is not None and proof != expected:
            raise VisibilityError("Sichtbares Installationsziel geändert; nichts aktivieren")
        return proof
    except (OSError, subprocess.SubprocessError) as exc:
        raise VisibilityError(
            "Sichtbarkeit technisch nicht nachgewiesen; nichts aktivieren"
        ) from exc
