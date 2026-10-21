"""Finite local reconciliation through descriptor sources; no native watches."""

from threading import Event
from time import monotonic

from kirabridge.bridge_core.models import BridgeError


def poll(
    index,
    principal,
    project,
    *,
    cycles=2,
    batches=10,
    interval_ms=1000,
    max_seconds=60,
    stopped=None,
    clock=monotonic,
    wait=None,
):
    """Coalesce periodic requests into one active bounded observation.

    The local operator owns this index/session. No background task, event path
    queue, external watcher registration or independent policy is introduced.
    Time limits are cooperative; the existing source batch limits still apply.
    """
    if (
        any(type(v) is not int for v in (cycles, batches, interval_ms, max_seconds))
        or not 1 <= cycles <= 1000
        or not 1 <= batches <= 1000
        or cycles * batches > 1000
        or not 250 <= interval_ms <= 5000
        or not 1 <= max_seconds <= 300
    ):
        raise BridgeError("invalid_search_budget", "Use a finite bounded polling budget")
    stopped = stopped or Event()
    wait = wait or stopped.wait
    scope = None
    used = 0
    deadline = clock() + max_seconds
    last = {"status": "not_started", "complete": False, "reasons": []}

    def value(status, cycle, reason=None):
        reasons = set(last["reasons"]) | {"filesystem_snapshot_unverified", "polling_observation"}
        if reason:
            reasons.add(reason)
        return {
            **last,
            "poll_mode": "bounded_poll",
            "poll_status": status,
            "cycles": cycle,
            "batches": used,
            "complete": False,
            "truncated": True,
            "reasons": sorted(reasons),
        }

    try:
        if stopped.is_set():
            yield value("stopped", 0)
            return
        initial = index.context(principal, project)
        if not initial["enabled"]:
            yield {
                **value("disabled", 0),
                "status": "disabled",
                "truncated": False,
                "reasons": ["disabled"],
            }
            return
        scope = initial["scope"]

        def current():
            now = index.context(principal, project)
            if not now["enabled"] or now.get("token") != initial["token"]:
                raise BridgeError("generation_changed", "Search observation changed")

        for cycle in range(1, cycles + 1):
            for _ in range(batches):
                current()
                if stopped.is_set() or clock() >= deadline:
                    yield value(
                        "stopped" if stopped.is_set() else "budget",
                        cycle,
                        "poll_time_budget" if not stopped.is_set() else None,
                    )
                    return
                last = index.scan(principal, project, observational=True)
                used += 1
                current()
                if last["status"] not in {"building", "observing"}:
                    break
            if last["status"] == "index_unavailable":
                yield value("fault", cycle)
                return
            if stopped.is_set():
                yield value("stopped", cycle)
                return
            if cycle == cycles or clock() >= deadline:
                partial = last["status"] in {"building", "observing"} or clock() >= deadline
                yield value(
                    "budget" if partial else "finished",
                    cycle,
                    "poll_cycle_budget" if partial else None,
                )
                return
            yield value("running", cycle)
            # Ticks arriving during the preceding batch are one request. A
            # slow observation continues on its next cycle, never restarts.
            if wait(min(interval_ms / 1000, max(0, deadline - clock()))):
                current()
                yield value("stopped", cycle)
                return
    finally:
        if scope is not None:
            index._cancel_scan(scope)
