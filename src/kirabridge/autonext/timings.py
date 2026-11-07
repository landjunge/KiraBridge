"""Owner-scoped timings from recorded Core events and task acceptance only."""

import json
import math

from kirabridge.bridge_core.models import BridgeError


def _timestamp(value):
    if type(value) not in (int, float):
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except OverflowError:
        return None


def _seconds(start, end):
    if start is None or end is None or end < start:
        return None
    duration = end - start
    return duration if math.isfinite(duration) else None


def _acceptance_time(row):
    core_id = row["core_task_id"]
    if (
        row["state"] != "completed"
        or not row["receipt"]
        or not isinstance(core_id, str)
        or not core_id.strip()
    ):
        return None
    try:
        receipt = json.loads(row["receipt"])
    except (ValueError, TypeError):
        return None
    if not isinstance(receipt, dict) or any(
        receipt.get(key) != row[column]
        for key, column in (
            ("task_id", "task_id"),
            ("work_id", "work_id"),
            ("core_task_id", "core_task_id"),
            ("source_sha256", "source_ref"),
        )
    ):
        return None
    return _timestamp(receipt.get("accepted_at"))


def task_timings(bridge, principal, task_id):
    """Read one pinned current task; absent timestamps are never estimated.

    Queue time ends at the Core claim, execution spans native start to finish,
    and acceptance spans Core finish to the stored coordinator receipt. Each
    duration requires its own finite, ordered endpoints.
    """
    bridge.security.principal(principal, "team.read")
    cfg = bridge.config.autonext
    if principal != cfg.principal:
        raise BridgeError("coordinator_owner_required", "Configured coordinator owner required")
    if not cfg.grant_id or not any(pin.task_id == task_id for pin in cfg.cards):
        raise BridgeError("not_found", "Current coordinator task was not found")
    with bridge.store.transaction():
        bridge.teams.get(principal, cfg.team_id)
        row = bridge.store.db.execute(
            "SELECT i.task_id,i.work_id,i.state,i.source_ref,i.receipt,"
            "w.id AS bound_work_id,w.core_task_id,"
            "t.created AS core_created_at,t.accepted AS core_accepted_at,"
            "t.started AS core_started_at,t.finished AS core_finished_at "
            "FROM autonext_items i LEFT JOIN team_work w ON w.id=i.work_id AND w.team_id=? "
            "LEFT JOIN tasks t ON t.id=w.core_task_id AND t.principal=w.assignee "
            "AND t.operation='agent.execute' WHERE i.grant_id=? AND i.task_id=?",
            (cfg.team_id, cfg.grant_id, task_id),
        ).fetchone()
        if row is None:
            raise BridgeError("not_found", "Current coordinator task was not found")
        if row["bound_work_id"] is None:
            raise BridgeError(
                "coordinator_state_unknown", "Coordinator work binding is unavailable"
            )
        result = {
            "task_id": task_id,
            **{
                key: _timestamp(row[key])
                for key in (
                    "core_created_at",
                    "core_accepted_at",
                    "core_started_at",
                    "core_finished_at",
                )
            },
            "task_accepted_at": _acceptance_time(row),
        }
    for name, start, end in (
        ("queue_seconds", "core_created_at", "core_accepted_at"),
        ("execution_seconds", "core_started_at", "core_finished_at"),
        ("acceptance_seconds", "core_finished_at", "task_accepted_at"),
        ("total_seconds", "core_created_at", "task_accepted_at"),
    ):
        result[name] = _seconds(result[start], result[end])
    return result
