"""Bound desktop effects to the existing session lock; no queue or OS hooks."""

import asyncio
import math
from contextlib import asynccontextmanager
from dataclasses import dataclass

from kirabridge.bridge_core.models import BridgeError, UncertainExecution

DESKTOP_EFFECT_OPERATIONS = frozenset(
    {
        "apps.launch",
        "apps.quit",
        "app.focus",
        "windows.focus",
        "accessibility.action",
        "accessibility.set",
    }
)


@dataclass
class InputTurn:
    attempted: bool = False

    def mark_attempted(self):
        self.attempted = True


class DesktopInput:
    def __init__(self, session_lock, *, timeout=12.0):
        if type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ValueError("Desktop input deadline must be finite and at most 30 seconds")
        self.lock, self.timeout = session_lock, timeout

    @asynccontextmanager
    async def transaction(self):
        turn = InputTurn()
        deadline = asyncio.timeout(self.timeout)
        try:
            async with deadline:
                async with self.lock:
                    yield turn
        except TimeoutError:
            if not deadline.expired():
                raise  # Preserve the responsible phase of an inner observation timeout.
            if turn.attempted:
                raise UncertainExecution(
                    "desktop_input_unknown",
                    "Desktop input deadline expired after an attempt; no replay",
                ) from None
            raise BridgeError(
                "desktop_input_busy", "Desktop input deadline expired before an effect attempt"
            ) from None
