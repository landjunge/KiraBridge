"""Read-only TollGate budget gate, called once per agent run.

Only a user-set daily envelope reached by measured spend can deny a run. Every
other outcome (missing/unpinned TollGate, import error, exception, timeout)
lets the run go ahead and is recorded as evidence. Only the consumer name is
passed; no keys, prompts or paths.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError

GATE_TIMEOUT_SECONDS = 2.0


def load_pinned_agent_gate(settings):
    """Load tollgate.agent_gate only from the pinned, fingerprint-checked package."""
    from kirabridge.configured_workflow import package_fingerprint

    if not settings.source_package_sha256:
        raise ValueError("pinned TollGate source required")
    spec = importlib.util.find_spec("tollgate")
    if (
        spec is None
        or not spec.submodule_search_locations
        or len(spec.submodule_search_locations) != 1
    ):
        raise ValueError("installed source package required")
    root = Path(next(iter(spec.submodule_search_locations))).resolve(strict=True)
    if package_fingerprint(root) != settings.source_package_sha256:
        raise ValueError("installed source differs from approved package")
    from tollgate import agent_gate as module

    return module.agent_gate


def _unavailable(reason):
    return {
        "decision": "unavailable",
        "reason": reason,
        "limit_source": "unavailable",
        "plan_exhausted": False,
    }


def _plan_exhausted(plan):
    return isinstance(plan, dict) and (
        plan.get("exhausted") is True or plan.get("state") == "exhausted"
    )


async def check_budget(loader, consumer):
    """Return the evidence note; raise BridgeError only for a user-set limit reached."""
    try:
        gate = loader()
        decision = await asyncio.wait_for(
            asyncio.to_thread(gate, consumer), timeout=GATE_TIMEOUT_SECONDS
        )
        verdict = decision["decision"]
        note = {
            "decision": verdict,
            "reason": str(decision.get("reason", ""))[:300],
            "limit_source": decision.get("limit_source"),
            "plan_exhausted": _plan_exhausted(decision.get("plan")),
        }
        day = decision.get("day") or {}
    except Exception:  # noqa: BLE001 - nothing blocks without a user-set limit
        return _unavailable("tollgate_unavailable")
    if verdict == "deny" and note["limit_source"] == "user_envelope":
        raise BridgeError(
            "tollgate_budget_reached",
            f"Daily budget for {consumer} reached: spent {day.get('spent_usd')} "
            f"of {day.get('limit_usd')} USD (TollGate)",
        )
    if verdict not in {"allow", "unknown", "deny"}:
        return _unavailable("tollgate_unavailable")
    return note
