"""Bounded observations of durable tasks; never dispatch, cancel or replay work."""

import asyncio
import json
import math

from kirabridge.bridge_core.models import BridgeError

MAX_WAIT_SECONDS = 18.0
POLL_SECONDS = 0.05
FIRST_POLL_SECONDS = 0.005
FIRST_POLL_CHECKS = 10
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


def _task_state(bridge, principal, task_id):
    bridge.security.principal(principal, "task.read")
    row = bridge.store.db.execute(
        "SELECT state FROM tasks WHERE id=? AND principal=?", (task_id, principal)
    ).fetchone()
    if row is None:
        raise BridgeError("not_found", "Task not found")
    return row["state"]


async def _wait_state(bridge, principal, task_id, state, deadline):
    """Observe state without loading output; give freshly queued work one turn."""
    loop = asyncio.get_running_loop()
    started = loop.time()
    first_window = FIRST_POLL_SECONDS * FIRST_POLL_CHECKS
    tick = 1
    while state in ACTIVE_STATES and (remaining := deadline - loop.time()) > 0:
        # Anchor ticks to the monotonic start: repeated short sleeps must not
        # shift the subsequent 50ms phase later. Skip elapsed ticks after an OS
        # scheduling stall instead of issuing catch-up reads or spinning.
        elapsed = loop.time() - started
        if elapsed < first_window:
            tick = max(tick, int(elapsed / FIRST_POLL_SECONDS) + 1)
        else:
            tick = max(tick, FIRST_POLL_CHECKS + int((elapsed - first_window) / POLL_SECONDS) + 1)
        target = started + (
            FIRST_POLL_SECONDS * tick
            if tick <= FIRST_POLL_CHECKS
            else first_window + POLL_SECONDS * (tick - FIRST_POLL_CHECKS)
        )
        delay = max(0, target - loop.time())
        await asyncio.sleep(min(delay, remaining))
        state = _task_state(bridge, principal, task_id)
        tick += 1


def _snapshot(bridge, principal, task_id, after=None):
    # A short read transaction pins task and event pages to the same durable
    # snapshot, including when another dispatcher process commits concurrently.
    # No await, external mutation or SQLite write lock is held here.
    db = bridge.store.db
    db.execute("SAVEPOINT task_observation_snapshot")
    try:
        task = bridge.task(principal, task_id)
        events, next_after, more = None, None, None
        if after is not None:
            # Bridge.task above already checked task.read and ownership inside
            # this same snapshot. Repeating Bridge.events would load the entire
            # task/output again merely to repeat that authorization.
            rows = db.execute(
                "SELECT seq,at,state,evidence FROM events WHERE task_id=? AND seq>? "
                "ORDER BY seq LIMIT 1000",
                (task_id, after),
            )
            events = {
                "events": [{**dict(row), "evidence": json.loads(row["evidence"])} for row in rows]
            }
            next_after = events["events"][-1]["seq"] if events["events"] else after
            more = db.execute(
                "SELECT 1 FROM events WHERE task_id=? AND seq>? LIMIT 1", (task_id, next_after)
            ).fetchone()
    finally:
        db.execute("RELEASE SAVEPOINT task_observation_snapshot")
    return task, events, next_after, more is not None


async def observe_task_result(bridge, principal, task_id, wait_seconds=0):
    """Return one fresh authorized task, without constructing an unused event page."""
    _validate(wait_seconds, 0)
    state = _task_state(bridge, principal, task_id)
    deadline = asyncio.get_running_loop().time() + wait_seconds
    await _wait_state(bridge, principal, task_id, state, deadline)
    return _snapshot(bridge, principal, task_id)[0]


async def observe_task(bridge, principal, task_id, wait_seconds=0, after=0):
    """Read one owned task and event page, optionally waiting on that same task.

    Approval-required and terminal states, including unknown outcomes, return
    immediately. Cancellation only ends this observer. No runtime, permissions,
    execution state, completion delivery or retry policy is changed.
    """
    _validate(wait_seconds, after)
    state = _task_state(bridge, principal, task_id)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    await _wait_state(bridge, principal, task_id, state, deadline)
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
    # Enqueue may return an internal/stale record. Check current rights and owner
    # before observing; use the public redaction once, for the final result.
    state = _task_state(bridge, principal, task_id)
    loop = asyncio.get_running_loop()
    observed = {}
    if state in ACTIVE_STATES and bridge.tasks.native.native(task) and loop.time() < deadline:
        try:
            async with asyncio.timeout_at(deadline):
                observed = await bridge.tasks.wait_delivery(task_id)
        except TimeoutError:
            pass  # NativeAdmission shields its attempt; only this observation ends.
        state = _task_state(bridge, principal, task_id)
    delivery = observed.get("delivery")
    if (
        state in ACTIVE_STATES
        and bridge.tasks.workers
        and (delivery or {}).get("status") != "not_admitted"
    ):
        await _wait_state(
            bridge,
            principal,
            task_id,
            state,
            min(deadline, loop.time() + wait_seconds),
        )
    task = _snapshot(bridge, principal, task_id)[0]
    if delivery:
        task["delivery"] = delivery
        if observed.get("error") and task["state"] in ACTIVE_STATES and not task.get("error"):
            task["error"] = observed["error"]
    return task
