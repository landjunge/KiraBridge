"""Narrow budget interface for coordinator turns: reserve -> dispatch -> settle.

KiraBridge owns no budget or quota logic. The authority is TollGate (Big Plan BP-TG-01:
Reserve -> Dispatch -> Settlement -> hard stop). Until a TollGate client is bound, the
only implementation is `FailClosedBudgetGate`, which refuses every reservation.
The existing Codex path (`account/rateLimits/read`) does not use this interface.
"""

from __future__ import annotations

from typing import Protocol

from kirabridge.bridge_core.models import BridgeError


class BudgetGate(Protocol):
    # True only when a real budget authority is bound and reachable.
    ready: bool

    def reserve(self, request: dict) -> dict:
        """Return an opaque reservation or raise BridgeError(autonext_budget_stop)."""

    def settle(self, reservation: dict, outcome: str) -> None:
        """outcome: completed | failed | unknown. Raise on a settlement failure."""


class FailClosedBudgetGate:
    """Placeholder until BP-TG-01 is bound: always rejects, never estimates."""

    ready = False

    def reserve(self, request: dict) -> dict:
        raise BridgeError(
            "autonext_budget_stop",
            "No budget authority is bound (TollGate BP-TG-01 pending); failing closed",
        )

    def settle(self, reservation: dict, outcome: str) -> None:
        raise BridgeError("autonext_budget_stop", "No budget authority is bound; failing closed")
