"""Read the macOS console state without opening windows or sending UI events."""

import asyncio
import os
import plistlib
import sys
import time

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters import reap_process
from kirabridge.timing import timed_async

DESKTOP_MESSAGES = {
    "desktop_locked": "Der Mac ist gesperrt. Bitte die bestehende Benutzersitzung entsperren. "
    "Terminalprozesse bleiben erhalten; es wird kein Ersatzfenster gestartet.",
    "desktop_session_inactive": "Die zugehörige Mac-Benutzersitzung ist nicht am Bildschirm aktiv. "
    "Vorhandene Terminalprozesse bleiben erhalten.",
}


DISPLAY_LOCK_MESSAGE = (
    "Bildschirm aus oder Bildschirmschoner: macOS zeigt die Sperre. Ob schon ein Passwort "
    "nötig ist, hängt von der Einstellung ab; eine lokale Eingabe weckt den Mac. "
    "Terminalprozesse bleiben erhalten; es wird kein Ersatzfenster gestartet."
)
LOCK_CAUSES = {
    "asleep": "display_sleep_or_screensaver",
    "dimmed": "display_sleep_or_screensaver",
    "on": "screen_locked",
}


def display_state(raw):
    """IODisplayWrangler power: max state is on, one below dimmed, lower asleep."""
    rows = plistlib.loads(raw)
    rows = rows if isinstance(rows, list) else [rows]
    states = set()
    for row in rows:
        power = row.get("IOPowerManagement") if isinstance(row, dict) else None
        current = power.get("CurrentPowerState") if isinstance(power, dict) else None
        maximum = power.get("MaxPowerState") if isinstance(power, dict) else None
        if type(current) is int and type(maximum) is int and maximum > 0:
            states.add(
                "on" if current >= maximum else "dimmed" if current == maximum - 1 else "asleep"
            )
    return states.pop() if len(states) == 1 else "unknown"


def console_state(raw, uid):
    roots = plistlib.loads(raw)
    roots = roots if isinstance(roots, list) else [roots]
    users = []
    for root in roots:
        rows = root.get("IOConsoleUsers") if isinstance(root, dict) else None
        if isinstance(rows, list):
            users.extend(row for row in rows if isinstance(row, dict))
    own = [u for u in users if u.get("kCGSSessionUserIDKey") == uid]
    if any(u.get("CGSSessionScreenIsLocked") is True for u in own):
        return "desktop_locked"
    if any(u.get("kCGSSessionOnConsoleKey") is True for u in own):
        return "available"
    if own and any(u.get("kCGSSessionOnConsoleKey") is True for u in users):
        return "desktop_session_inactive"
    return "unknown"


class MacDesktop:
    # Lock/active state changes on user action, not within a single polling burst;
    # a short cache avoids re-spawning ioreg on every rapid catalog() call.
    cache_seconds = 1.0

    def __init__(self):
        self.last = {"state": "not_probed", "observed_at": None}

    @timed_async("ioreg_probe")
    async def probe(self):
        cached = self.last
        if (
            cached.get("observed_at") is not None
            and time.time() - cached["observed_at"] < self.cache_seconds
        ):
            return cached
        if sys.platform != "darwin":
            self.last = {"state": "not_applicable", "observed_at": time.time()}
            return self.last
        state = await self._ioreg(
            ("-n", "Root", "-d1", "-a"), lambda raw: console_state(raw, os.getuid())
        )
        self.last = {
            "state": state,
            "observed_at": time.time(),
            "scope": "macOS console availability, not permission or agent readiness",
        }
        if state == "desktop_locked":
            # macOS raises the lock shield when the screensaver starts or the display
            # sleeps, even while its password delay still allows any local key to wake it.
            display = await self._ioreg(
                ("-r", "-d1", "-c", "IODisplayWrangler", "-a"), display_state
            )
            self.last["display"] = display
            self.last["lock_cause"] = LOCK_CAUSES.get(display, "unknown")
        return self.last

    async def _ioreg(self, arguments, parse):
        child = None
        state = "unknown"
        try:
            child = await asyncio.create_subprocess_exec(
                "/usr/sbin/ioreg",
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            async with asyncio.timeout(2):
                raw, _ = await child.communicate()
            if child.returncode == 0 and len(raw) <= 1048576:
                state = parse(raw)
        except (OSError, TimeoutError, ValueError, plistlib.InvalidFileException):
            pass  # An unavailable extra probe never removes an existing grant.
        finally:
            if child is not None:
                try:
                    await reap_process(child, process_group=False)
                except BridgeError:
                    if state not in DESKTOP_MESSAGES:
                        state = "unknown"
        return state

    async def require_interactive(self):
        state = await self.probe()
        if state["state"] in DESKTOP_MESSAGES:
            message = (
                DISPLAY_LOCK_MESSAGE
                if state.get("lock_cause") == "display_sleep_or_screensaver"
                else DESKTOP_MESSAGES[state["state"]]
            )
            raise BridgeError(state["state"], message)
