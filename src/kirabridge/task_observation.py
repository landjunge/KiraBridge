"""Bounded observations of durable tasks; never dispatch, cancel or replay work."""

import asyncio
import math

from kirabridge.bridge_core.models import BridgeError

MAX_WAIT_SECONDS = 18.0
POLL_SECONDS = 0.05
ACTIVE_STATES = frozenset({"queued", "accepted", "running"})
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "unknown", "blocked"})


def _validate(wait_seconds, after):
    if (
        type(wait_seconds) not in {int, float}
        or not math.isfinite(wait_seconds)
        or not 0 <= wait_seconds <= MAX_WAIT_SECONDS
        or type(after) is not int
        or not 0 <= after <= 2**63 - 1
    ):
        raise BridgeError("invalid_arguments", "Task observation requires wait 0–18s and a cursor")


async def _wait_state(bridge, principal, task_id, state, deadline):
    """Poll only state; resolve potentially large persisted output once, at return."""
    loop = asyncio.get_running_loop()
    while state in ACTIVE_STATES and (remaining := deadline - loop.time()) > 0:
        await asyncio.sleep(min(POLL_SECONDS, remaining))
        bridge.security.principal(principal, "task.read")
        row = bridge.store.db.execute(
            "SELECT state FROM tasks WHERE id=? AND principal=?", (task_id, principal)
        ).fetchone()
        if row is None:
            raise BridgeError("not_found", "Task not found")
        state = row["state"]


def _snapshot(bridge, principal, task_id, after):
    # A short read transaction pins task and event pages to the same durable
    # snapshot, including when another dispatcher process commits concurrently.
    # No await, external mutation or SQLite write lock is held here.
    db = bridge.store.db
    db.execute("SAVEPOINT task_observation_snapshot")
    try:
        task = bridge.task(principal, task_id)
        events = bridge.events(principal, task_id, after)
        next_after = events["events"][-1]["seq"] if events["events"] else after
        more = db.execute(
            "SELECT 1 FROM events WHERE task_id=? AND seq>? LIMIT 1", (task_id, next_after)
        ).fetchone()
    finally:
        db.execute("RELEASE SAVEPOINT task_observation_snapshot")
    return task, events, next_after, more is not None


async def observe_task(bridge, principal, task_id, wait_seconds=0, after=0):
    """Read one owned task and event page, optionally waiting on that same task.

    Approval-required and terminal states, including unknown outcomes, return
    immediately. Cancellation only ends this observer. No runtime, permissions,
    execution state, completion delivery or retry policy is changed.
    """
    _validate(wait_seconds, after)
    task = bridge.task(principal, task_id)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    await _wait_state(bridge, principal, task_id, task["state"], deadline)
    task, events, next_after, more = _snapshot(bridge, principal, task_id, after)
    state = task["state"]
    pending = state in ACTIVE_STATES
    return {
        "task": task,
        "events": events,
        "state": state,
        "complete": state in TERMINAL_STATES,
        "pending": pending,
        "approval_required": state == "created",
        "execution_outcome_unknown": state == "unknown",
        "timed_out": bool(wait_seconds and pending and loop.time() >= deadline),
        "next_after": next_after,
        "has_more_events": more,
    }


async def observe_submitted_task(bridge, principal, task, *, wait_seconds, deadline):
    """Share one response budget between native admission and result observation."""
    if not task.get("id"):
        return task
    task_id = task["id"]
    # Enqueue returns an internal record. Always use the public redaction and
    # task.read check, even for an immediate approval or terminal response.
    task = bridge.task(principal, task_id)
    loop = asyncio.get_running_loop()
    observed = {}
    if task["state"] in ACTIVE_STATES and loop.time() < deadline:
        try:
            async with asyncio.timeout_at(deadline):
                observed = await bridge.tasks.wait_delivery(task_id)
        except TimeoutError:
            pass  # NativeAdmission shields its attempt; only this observation ends.
        task = bridge.task(principal, task_id)
    delivery = observed.get("delivery")
    if (
        task["state"] in ACTIVE_STATES
        and bridge.tasks.workers
        and (delivery or {}).get("status") != "not_admitted"
    ):
        await _wait_state(
            bridge,
            principal,
            task_id,
            task["state"],
            min(deadline, loop.time() + wait_seconds),
        )
        task = bridge.task(principal, task_id)
    if delivery:
        task["delivery"] = delivery
        if observed.get("error") and task["state"] in ACTIVE_STATES and not task.get("error"):
            task["error"] = observed["error"]
    return task
