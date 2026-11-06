"""Bounded owner-only projection of the existing coordinator ledger.

Reading this projection never starts work, renews a lease, accepts a result or
reads model output. Durable terminal notices use the existing completion inbox.
"""

from collections import Counter

from kirabridge.bridge_core.models import BridgeError


def coordinator_status(bridge, principal):
    bridge.security.principal(principal, "team.read")
    cfg, manager = bridge.config.autonext, bridge.autonext
    if principal != cfg.principal:
        raise BridgeError("coordinator_owner_required", "Configured coordinator owner required")
    native = bool(getattr(manager, "supports_coordinator_checks", False))
    with bridge.store.transaction():
        state = manager.inspect()
        items = []
        if cfg.coordinator_mode and native:
            if cfg.team_id:
                bridge.teams.get(principal, cfg.team_id)
            approved = {card.task_id for card in cfg.cards}
            rows = bridge.store.db.execute(
                "SELECT task_id,work_id,state,claim_published,lease_until,receipt IS NOT NULL "
                "AS receipt_recorded FROM autonext_items WHERE grant_id=? ORDER BY rowid LIMIT 17",
                (cfg.grant_id,),
            ).fetchall()
            if len(rows) > 16 or any(row["task_id"] not in approved for row in rows):
                raise BridgeError("coordinator_state_unknown", "Ledger differs from pinned grant")
            for row in rows:
                review = bridge.store.db.execute(
                    "SELECT grok_work_id,verify_work_id,checks_state FROM autonext_coordinator "
                    "WHERE task_id=?",
                    (row["task_id"],),
                ).fetchone()
                item = dict(row)
                item["claim_published"] = bool(item["claim_published"])
                item["receipt_recorded"] = bool(item["receipt_recorded"])
                roles = {"worker": row["work_id"]}
                if review:
                    item["checks_state"] = review["checks_state"]
                    roles.update(grok=review["grok_work_id"], verifier=review["verify_work_id"])
                item["work"] = {}
                for role, work_id in roles.items():
                    if work_id is None:
                        continue
                    work = bridge.store.db.execute(
                        "SELECT id,assignee,state,core_task_id FROM team_work "
                        "WHERE id=? AND team_id=?",
                        (work_id, cfg.team_id),
                    ).fetchone()
                    if work is None:
                        raise BridgeError(
                            "coordinator_state_unknown", "Coordinator work binding is unavailable"
                        )
                    item["work"][role] = dict(work)
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
        "completion_channel": {
            "target": getattr(cfg, "completion_target", None),
            "receive_tool": "completion_receive",
            "ack_tool": "completion_ack",
            "scope": "durable owner inbox; no unsolicited assistant wake-up",
        },
        "read_only": True,
        "project_completion_verified": False,
    }
