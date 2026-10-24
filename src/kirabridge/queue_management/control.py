"""CAS-controlled delivery withdrawal, safe restoration and uncertain-handoff retirement."""

import time

from kirabridge.bridge_core.models import BridgeError, digest
from kirabridge.queue_management.schema import TERMINAL
from kirabridge.queue_management.views import QueueViews


class QueueManager(QueueViews):
    def _capability(self, principal, family, detail):
        if family == "messages":
            if principal not in {detail["sender"], detail["recipient"]}:
                raise BridgeError(
                    "forbidden", "Conversation readers cannot cancel another identity's work"
                )
            return "message.send" if principal == detail["sender"] else "message.ack"
        if family.startswith("team-"):
            self.teams._team(principal, detail["team_id"], "team.write", write=True)
            if principal not in {
                detail.get("assigned_by"),
                detail.get("assignee"),
                detail.get("sender"),
                detail.get("recipient"),
            }:
                raise BridgeError("forbidden", "Cannot cancel another team member's work")
            return "team.write"
        if family == "voice-buffers":
            return "message.send"
        if family == "completions":
            return "task.read" if detail["source"] == "task" else "message.read"
        return "task.cancel"

    async def control(self, principal, args, *, approved=False, control_task_id=None):
        if args.action != "clear" and args.item_id is None:
            raise BridgeError("invalid_arguments", "An entry ID is required")
        # Bulk operations are bounded, exact observed snapshots; no implicit 'all future work'.
        with self.store.transaction():
            if args.action == "clear":
                snapshot = self.snapshot(principal, args.queue_id, exclude_id=control_task_id)
                if snapshot["revision"] != args.revision:
                    raise BridgeError("queue_changed", "Queue changed; inspect before clearing")
                entries = [
                    r
                    for r in self._all(principal, args.queue_id, True)
                    if r["id"] != control_task_id
                ]
            else:
                entry = self.get(principal, args.queue_id, args.item_id)
                if entry["revision"] != args.revision:
                    raise BridgeError("queue_changed", "Entry changed; inspect before controlling")
                entries = [entry]
        # Readiness can await; every mutation rechecks its revision afterwards.
        if args.action == "retire":
            family, _, _, _ = self._spec(principal, args.queue_id)
            if family != "handoffs" or entries[0]["state"] != "unknown":
                raise BridgeError("state_conflict", "Retirement is only for an uncertain handoff")
            target = entries[0]["target"]
            binding = self.handoffs.config.visible_handoffs.bindings.get(target)
            if binding is None:
                raise BridgeError("visible_target_missing", "A current assigned target is required")
            await self.handoffs.check_target(principal, target, binding, ready=True)
        results = []
        with self.store.transaction():
            if (
                args.action == "clear"
                and self.snapshot(principal, args.queue_id, exclude_id=control_task_id)["revision"]
                != args.revision
            ):
                raise BridgeError("queue_changed", "Queue changed during control")
            for entry in entries:
                current = self.get(principal, args.queue_id, entry["id"])
                if current["revision"] != entry["revision"]:
                    raise BridgeError("queue_changed", "Entry changed during control")
                family, _, _, _ = self._spec(principal, args.queue_id)
                cap = self._capability(principal, family, current["detail"])
                decision = self.security.authorize(principal, cap)
                if not approved and decision["approval_required"]:
                    raise BridgeError(
                        "approval_required", "Submit queue.control as an exact approved task"
                    )
                result = self._mutate(principal, family, current, args.action, args.reason)
                results.append(result)
        self.messages.wake.set()
        self.tasks.wake.set()
        return {
            "queue_id": args.queue_id,
            "results": results,
            "fully_removed": all(not r["delivery_active"] for r in results),
            "execution_stop_claimed": False,
            "history_preserved": True,
        }

    def _mutate(self, principal, family, entry, action, reason):
        identifier, state = entry["id"], entry["state"]
        if action in {"cancel", "clear"} and not entry["delivery_active"]:
            return {
                "id": identifier,
                "delivery_active": False,
                "state": state,
                "removed": True,
                "stop_confirmed": False,
                "history_preserved": True,
            }
        if action == "restore":
            if not entry["hold"] or entry["hold"]["actor"] != principal:
                raise BridgeError("forbidden", "Only the withdrawing identity may restore delivery")
            if family not in {"messages", "completions", "team-messages"} or state != "queued":
                raise BridgeError(
                    "state_conflict", "Only never-started held deliveries can be restored"
                )
            detail = entry["detail"]
            if family == "messages" and (
                detail["delivered"]
                or detail["acknowledged"]
                or (detail["processing"] or {}).get("run_id")
            ):
                raise BridgeError(
                    "state_conflict", "Delivered/claimed messages cannot be automatically resent"
                )
            self.store.db.execute(
                "DELETE FROM queue_holds WHERE queue_id=? AND item_id=?", (family, identifier)
            )
        elif action == "retire":
            self._place_hold(principal, family, identifier, reason)
            message_id = entry["detail"]["message_id"]
            self._place_hold(principal, "messages", message_id, reason)
            self.messages._event(
                message_id,
                "message.uncertain_delivery_retired",
                principal,
                {
                    "handoff_id": identifier,
                    "execution_state": "unknown",
                    "fresh_target_idle": True,
                    "automatic_retry": False,
                },
            )
        elif state not in TERMINAL | {"created", "queued", "queued_manual", "waiting"}:
            return {
                "id": identifier,
                "delivery_active": entry["delivery_active"],
                "state": state,
                "removed": False,
                "stop_confirmed": False,
                "error": "execution_unresolved",
                "next_step": (
                    "Inspect receipt/process evidence; use an owned process.terminate/"
                    "workflow.stop, or handoff retirement after verified idle. Never replay."
                ),
            }
        elif family in {"tasks", "session-input"}:
            self.tasks.cancel_queued(principal, identifier)
        elif family == "team-work":
            if entry["detail"].get("core_task_id"):
                raise BridgeError(
                    "execution_unresolved", "Reconcile bound core task before removal"
                )
            self.store.db.execute(
                "UPDATE team_work SET state='cancelled',finished=? WHERE id=?",
                (time.time(), identifier),
            )
            self.teams._event(
                entry["detail"]["team_id"], principal, "team.work_cancelled", identifier
            )
        elif family == "voice-buffers":
            self.store.db.execute(
                "UPDATE voice_message_buffers SET state='cancelled' WHERE id=?", (identifier,)
            )
        else:
            if family == "messages":
                detail = entry["detail"]
                if (
                    detail["delivered"]
                    or detail["acknowledged"]
                    or (detail["processing"] or {}).get("run_id")
                ):
                    raise BridgeError(
                        "execution_unresolved", "Claimed/delivered messages need reconciliation"
                    )
            self._place_hold(principal, family, identifier, reason)
        self.store.audit(
            "queue." + action,
            principal,
            None,
            {
                "queue": family,
                "item_id": identifier,
                "reason_sha256": digest(reason),
                "execution_state_before": state,
                "history_preserved": True,
            },
        )
        if family == "messages":
            self.messages._event(
                identifier,
                "message.delivery_" + action,
                principal,
                {"execution_unchanged": True, "reason_sha256": digest(reason)},
            )
        value = self.get(principal, family, identifier)
        return {
            "id": identifier,
            "delivery_active": value["delivery_active"],
            "state": value["state"],
            "removed": not value["delivery_active"],
            "stop_confirmed": False,
            "history_preserved": True,
        }

    def _place_hold(self, principal, family, identifier, reason):
        self.store.db.execute(
            "INSERT OR REPLACE INTO queue_holds VALUES(?,?,?,?,?)",
            (family, identifier, principal, time.time(), reason),
        )
