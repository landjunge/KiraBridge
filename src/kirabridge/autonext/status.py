"""Bounded owner-only projection of the existing coordinator ledger.

Reading this projection never starts work, renews a lease, accepts a result or
reads model output. Durable terminal notices use the existing completion inbox.
"""

import re
from collections import Counter

from kirabridge.autonext.timings import authorize_coordinator_reader, task_timings
from kirabridge.bridge_core.models import BridgeError, canonical, digest


def _recorded_note(db, cfg, task_id, phase, details):
    """Match existing public workflow metadata, never read a model result or audit."""
    content = canonical(
        {"autonext": 1, "task_id": task_id, "grant_id": cfg.grant_id, "phase": phase, **details}
    )
    key = "autonext-" + digest([cfg.grant_id, task_id, phase])[:48]
    return (
        db.execute(
            "SELECT 1 FROM autonext_outbox WHERE key=? AND grant_id=? AND task_id=? "
            "AND phase=? AND content=?",
            (key, cfg.grant_id, task_id, phase, content),
        ).fetchone()
        is not None
    )


def _workflow_state(db, cfg, item, source_ref, review, work, state):
    stored = item["ledger_state"]
    if stored != "waiting" or state["state"] != "stopped":
        return stored
    if review is not None and review["checks_state"] not in {"not_started", "completed"}:
        return stored
    pin = next(card for card in cfg.cards if card.task_id == item["task_id"])
    if source_ref != pin.content_sha256 or not _recorded_note(
        db, cfg, item["task_id"], "stopped", {"reason": state["reason"], "automatic_retry": False}
    ):
        return stored
    # A stopped controller is not evidence that its native effects have stopped.
    finished = {"completed", "failed", "blocked", "cancelled"}
    if any(w["state"] not in finished or w["core_state"] not in finished for w in work.values()):
        return stored
    if work["worker"]["assignee"] != "codex" or work["worker"]["assigned_by"] != cfg.principal:
        return stored
    for role in work.keys() - {"worker"}:
        w = work[role]
        if (
            review is None
            or not isinstance(review["source_sha"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", review["source_sha"])
            or w["parent_id"] != item["work_id"]
            or w["assigned_by"] != cfg.principal
            or w["assignee"] != {"verifier": "codex_verify", "grok": "grok"}[role]
            or db.execute(
                "SELECT 1 FROM team_work WHERE id=? AND body=?",
                (w["id"], "Controller-bound review of result " + review["source_sha"]),
            ).fetchone()
            is None
            or not _recorded_note(
                db,
                cfg,
                item["task_id"],
                "verify_review" if role == "verifier" else "grok_review",
                {"work_id": w["id"], "source_sha256": review["source_sha"]},
            )
        ):
            return stored
    reason = state["reason"]
    if reason == "autonext_review_rejected":
        return (
            "rejected"
            if len(work) > 1
            and all(w["state"] == w["core_state"] == "completed" for w in work.values())
            else stored
        )
    worker_state = work["worker"]["state"]
    if (
        worker_state in {"failed", "blocked", "cancelled"}
        and reason == "autonext_work_" + worker_state
    ):
        return worker_state
    if reason == "autonext_check_failed" and review and review["checks_state"] == "completed":
        return "failed"
    if reason == "autonext_review_unknown" and any(
        w["state"] == "failed" for role, w in work.items() if role != "worker"
    ):
        return "failed"
    return "stopped"


def coordinator_status(bridge, principal):
    cfg, manager = bridge.config.autonext, bridge.autonext
    native = bool(getattr(manager, "supports_coordinator_checks", False))
    with bridge.store.transaction():
        authorize_coordinator_reader(bridge, principal)
        state = manager.inspect()
        items = []
        if cfg.coordinator_mode and native:
            if cfg.team_id:
                bridge.teams.get(principal, cfg.team_id)
            approved = {card.task_id for card in cfg.cards}
            rows = bridge.store.db.execute(
                "SELECT task_id,work_id,state,claim_published,lease_until,receipt IS NOT NULL "
                "AS receipt_recorded,source_ref FROM autonext_items "
                "WHERE grant_id=? ORDER BY rowid LIMIT 17",
                (cfg.grant_id,),
            ).fetchall()
            if len(rows) > 16 or any(row["task_id"] not in approved for row in rows):
                raise BridgeError("coordinator_state_unknown", "Ledger differs from pinned grant")
            for row in rows:
                review = bridge.store.db.execute(
                    "SELECT source_sha,grok_work_id,verify_work_id,checks_state "
                    "FROM autonext_coordinator "
                    "WHERE task_id=?",
                    (row["task_id"],),
                ).fetchone()
                item = dict(row)
                source_ref = item.pop("source_ref")
                item["ledger_state"] = item["state"]
                item["claim_published"] = bool(item["claim_published"])
                item["receipt_recorded"] = bool(item["receipt_recorded"])
                roles = {"worker": row["work_id"]}
                if review:
                    item["checks_state"] = review["checks_state"]
                    roles.update(grok=review["grok_work_id"], verifier=review["verify_work_id"])
                item["work"] = {}
                metadata = {}
                for role, work_id in roles.items():
                    if work_id is None:
                        continue
                    work = bridge.store.db.execute(
                        "SELECT w.id,w.assignee,w.state,w.core_task_id,w.parent_id,w.assigned_by,"
                        "t.state AS core_state FROM team_work w LEFT JOIN tasks t "
                        "ON t.id=w.core_task_id AND t.principal=w.assignee "
                        "AND t.operation='agent.execute' WHERE w.id=? AND w.team_id=?",
                        (work_id, cfg.team_id),
                    ).fetchone()
                    if work is None:
                        raise BridgeError(
                            "coordinator_state_unknown", "Coordinator work binding is unavailable"
                        )
                    metadata[role] = dict(work)
                    item["work"][role] = {
                        key: work[key] for key in ("id", "assignee", "state", "core_task_id")
                    }
                item["state"] = _workflow_state(
                    bridge.store.db, cfg, item, source_ref, review, metadata, state
                )
                item["timings"] = task_timings(bridge, principal, row["task_id"])
                items.append(item)
    return {
        "schema": "kirabridge.coordinator-status.v1",
        "coordinator_mode": cfg.coordinator_mode,
        "native_manager": native,
        "controller_running": bool(manager.worker is not None and not manager.worker.done()),
        "restart_required": cfg.coordinator_mode and not native,
        "autonext": state,
        "team_id": cfg.team_id or None,
        "tasks": items,
        "counts": dict(Counter(item["state"] for item in items)),
        "task_state_scope": "coordinator workflow projection, not native effect completion",
        "completion_channel": {
            "target": getattr(cfg, "completion_target", None),
            "receive_tool": "completion_receive",
            "ack_tool": "completion_ack",
            "scope": "durable owner inbox; no unsolicited assistant wake-up",
        },
        "read_only": True,
        "project_completion_verified": False,
    }
