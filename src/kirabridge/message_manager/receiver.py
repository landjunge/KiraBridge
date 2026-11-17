"""One bounded worker per recipient; replies use authenticated recipient MCP."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from pathlib import Path

from kirabridge.bridge_core.models import (
    AgentInput,
    BridgeError,
    UncertainExecution,
    canonical,
    digest,
)
from kirabridge.local_runtime import peer
from kirabridge.mcp_gateway.client import MCPClientPool
from kirabridge.message_manager import MessageSend


def separate_managed_eligible(config, created: float) -> bool:
    """True only for messages created at or after an explicit operator cutoff.

    The default cutoff is unset, so existing visible delivery stays unchanged.
    Holds, unknown jobs and older rows are not made eligible by this check.
    """
    cutoff = config.messaging.separate_managed_after
    if cutoff is None:
        return False
    return float(created) >= float(cutoff)


class MessageReceiver:
    WAIT_REASONS = {
        "visible_target_busy",
        "visible_target_not_ready",
        "desktop_locked",
        "desktop_session_inactive",
        "visible_target_working",
        "visible_input_not_empty",
        "visible_target_scrolled",
        "visible_target_unknown",
    }

    def __init__(self, bridge):
        self.bridge = bridge
        self.messages = bridge.messages
        self.worker = None
        self.stopping = False
        self.recovered_handoffs = set()
        self._stops_in_progress = 0
        from kirabridge.message_manager.direct import DirectDelivery

        self.direct = DirectDelivery(self)

    async def start(self):
        if self._stops_in_progress:
            return
        if self.direct._stop_task is not None and not self.direct._stop_task.done():
            return  # A cancelled stop observer must not reopen admission during owned cleanup.
        if self.worker and self.worker.done():
            if not self.worker.cancelled():
                self.worker.exception()  # Consume the finished task before replacing its handle.
            self.worker = None
        if self.worker or not self.bridge.config.messaging.receivers:
            return
        self.recovered_handoffs.clear()
        # The task dispatcher owns the exclusive runtime lock before this is called.
        with self.bridge.store.transaction():
            rows = self.bridge.store.db.execute(
                "SELECT message_id,evidence FROM message_jobs WHERE state='running'"
            ).fetchall()
            for row in rows:
                if self._reply_can_finish(row):
                    self.recovered_handoffs.add(row["message_id"])
                    continue  # Return already happened; do not interrupt or paste again.
                observed = json.loads(row["evidence"])
                self._finish(
                    row[0],
                    "unknown",
                    {
                        "reason": "receiver_restart",
                        "last_observation": observed,
                        # Keep the claim proofs verbatim; never refresh them on restart.
                        **{
                            key: observed[key]
                            for key in ("managed_guidance_context", "claim_seal")
                            if key in observed
                        },
                    },
                    "interrupted",
                )
            queued = self.bridge.store.db.execute(
                "SELECT m.id,m.recipient,m.created FROM messages m "
                "JOIN message_jobs j ON j.message_id=m.id WHERE j.state='queued'"
            ).fetchall()
            cutoff = self.bridge.config.messaging.separate_managed_after
            for row in queued:
                if row["recipient"] not in self.bridge.config.messaging.receivers:
                    # A configured cutoff preserves older jobs instead of
                    # marking them blocked when their receiver is absent.
                    if cutoff is not None and row["created"] < cutoff:
                        continue
                    self._finish(row["id"], "blocked", {"reason": "receiver_removed"})
        self._reconcile_recovered_handoffs()
        self.stopping = False
        self.direct.accepting = True
        self.messages.delivery_hook = self._submit_new
        self.worker = asyncio.create_task(self._loop())

    async def stop(self):
        self._stops_in_progress += 1
        self.messages.delivery_hook = None
        self.stopping = True
        self.messages.wake.set()
        worker = self.worker
        try:
            try:
                await self.direct.stop()
            finally:
                if worker:
                    # Never observe a replacement worker from a concurrent start.
                    try:
                        await asyncio.shield(worker)
                    finally:
                        if self.worker is worker and worker.done():
                            self.worker = None
        finally:
            self._stops_in_progress -= 1

    def _submit_new(self, principal, message_id):
        row = self.bridge.store.db.execute(
            "SELECT created FROM messages WHERE id=?", (message_id,)
        ).fetchone()
        if self.bridge.config.visible_handoffs.enabled and not separate_managed_eligible(
            self.bridge.config, row["created"]
        ):
            self.direct.submit(principal, message_id)

    async def send(self, principal, message, *, completion_target=None):
        """Observe one new visible admission, never resubmit a recorded ID."""
        recorded = self.bridge.store.db.execute(
            "SELECT id FROM messages WHERE sender=? AND idem=?",
            (principal, message.idempotency_key),
        ).fetchone()
        result = self.messages.send(principal, message, completion_target=completion_target)
        if "id" not in result or result.get("message_buffer"):
            return result
        identifier = result["id"]
        job = result.get("processing")
        visible = self.bridge.config.visible_handoffs.enabled and not separate_managed_eligible(
            self.bridge.config, result["created"]
        )
        if not job or not visible:
            return result
        if not recorded and job["state"] == "queued" and not self.direct.accepting:
            self.direct.fail(
                identifier, BridgeError("receiver_unavailable", "Direct receiver is not running")
            )
        if identifier in self.direct.active:
            await self.direct.wait_delivery(identifier)
        result = self.messages.get(principal, identifier)
        job = result["processing"]
        if job["state"] == "queued":
            # No active runtime attempt means a historical/unadmitted record.
            # Its ID remains readable, but reading it never starts delivery.
            result["delivery"] = {
                "status": "not_admitted",
                "automatic_retry": False,
                "next_step": "Inspect the original record; do not resend or release history",
            }
            result["error"] = {
                "code": "delivery_not_admitted",
                "message": "No active delivery attempt for this record; inspect without replay",
            }
        elif job["state"] in {"failed", "blocked", "cancelled", "unknown"}:
            result["error"] = {
                "code": job["error"] or job["evidence"].get("reason", "delivery_not_admitted"),
                "message": "Visible delivery unconfirmed; inspect this message ID, never replay",
            }
        return result

    def _reply_can_finish(self, row):
        """A delivered visible handoff is waiting for its reply, not for another paste."""
        try:
            evidence = json.loads(row["evidence"] or "{}")
        except (TypeError, ValueError):
            return False
        handoff_id = evidence.get("handoff_id") if isinstance(evidence, dict) else None
        if not handoff_id:
            return False
        handoff = self.bridge.store.db.execute(
            "SELECT h.state FROM visible_handoffs h JOIN messages m ON m.id=h.message_id "
            "WHERE h.id=? AND m.id=? AND h.principal=m.sender AND h.target=m.recipient",
            (handoff_id, row["message_id"]),
        ).fetchone()
        return bool(handoff) and handoff["state"] in {
            "return_sent",
            "sent",
            "confirmed",
            "completed",
        }

    def _local_reply_evidence(self, message_id, run_id, result, *, recovered=False):
        """Observed local protocol results never impersonate an authenticated peer."""
        from kirabridge.bridge_core.config import VisibleTerminalBinding
        from kirabridge.platform_adapters.codex_reply import MAX_ANSWER_BYTES, MAX_LOG_BYTES

        try:
            proof = result.get("evidence") if isinstance(result, dict) else None
            if (
                not isinstance(result, dict)
                or result.get("success") is not True
                or result.get("scope") != "local_agent_turn"
                or result.get("reply_source") != "bound_local_codex_rollout"
                or result.get("agent_confirmed") is not False
                or result.get("request_reply_satisfied") is not True
                or result.get("work_completion_verified") is not False
                or result.get("project_completion_verified") is not False
                or result.get("reply_id") is not None
                or not isinstance(result.get("text"), str)
                or not result["text"].strip()
                or len(result["text"].encode("utf-8")) > MAX_ANSWER_BYTES
                or not isinstance(proof, dict)
                or proof.get("message_id") != message_id
                or proof.get("handoff_id") != run_id
                or proof.get("reply_id") is not None
                or proof.get("reply_source") != "bound_local_codex_rollout"
                or proof.get("completion_scope") != "local_agent_turn"
                or proof.get("identity_scope")
                != "OS_process_and_local_protocol_not_authenticated_mailbox"
                or proof.get("agent_confirmed") is not False
                or proof.get("request_reply_satisfied") is not True
                or proof.get("process_writer_verified") is not True
                or proof.get("task_complete_observed") is not True
                or type(proof.get("baseline_offset")) is not int
                or not 0 < proof["baseline_offset"] <= MAX_LOG_BYTES
                or any(
                    not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,256}", value)
                    for value in (
                        proof.get(key) for key in ("turn_id", "user_item_id", "final_item_id")
                    )
                )
                or proof["user_item_id"] == proof["final_item_id"]
                or any(
                    not isinstance(proof.get(key), str)
                    or not re.fullmatch(r"[a-f0-9]{64}", proof[key])
                    for key in ("baseline_sha256", "appended_sha256", "expected_payload_sha256")
                )
                or any(
                    key.startswith("authenticated_")
                    for value in (result, proof, proof.get("protocol_binding"))
                    if isinstance(value, dict)
                    for key in value
                )
                or not isinstance(proof.get("binding"), dict)
                or not isinstance(proof.get("protocol_binding"), dict)
            ):
                raise ValueError("invalid_local_reply_result")
            binding = VisibleTerminalBinding.model_validate(proof["binding"])
            protocol = proof["protocol_binding"]
            thread, path, cwd = (protocol.get(key) for key in ("thread_id", "rollout_path", "cwd"))
            if (
                not isinstance(thread, str)
                or not re.fullmatch(r"[a-f0-9-]{36}", thread)
                or not isinstance(path, str)
                or len(path) > 4096
                or not Path(path).is_absolute()
                or ".." in Path(path).parts
                or Path(path).suffix != ".jsonl"
                or any(ord(char) < 32 for char in path)
                or binding.expected_pid == binding.agent_pid
                or (
                    cwd is not None
                    and (
                        not isinstance(cwd, str)
                        or len(cwd) > 4096
                        or not Path(cwd).is_absolute()
                        or ".." in Path(cwd).parts
                        or any(ord(char) < 32 for char in cwd)
                    )
                )
                or (
                    binding.codex_thread_id is not None
                    and (
                        protocol.get("origin") != "explicit_verified_writer"
                        or binding.codex_thread_id != thread
                        or binding.codex_rollout_path != path
                    )
                )
                or (
                    binding.codex_thread_id is None
                    and (protocol.get("origin") != "process_writer_discovery" or cwd is None)
                )
            ):
                raise ValueError("invalid_local_protocol_binding")
            original = self.bridge.store.db.execute(
                "SELECT body,sender,recipient FROM messages WHERE id=?", (message_id,)
            ).fetchone()
            if (
                original is None
                or original["recipient"] != "codex"
                or proof["expected_payload_sha256"]
                != hashlib.sha256(original["body"].encode("utf-8")).hexdigest()
            ):
                raise ValueError("original_body_mismatch")
            handoff = self.bridge.store.db.execute(
                "SELECT binding,state,message_id,principal,target FROM visible_handoffs WHERE id=?",
                (run_id,),
            ).fetchone()
            if handoff and (
                handoff["state"] != "completed"
                or handoff["message_id"] != message_id
                or handoff["principal"] != original["sender"]
                or handoff["target"] != original["recipient"]
                or json.loads(handoff["binding"]) != proof["binding"]
            ):
                raise ValueError("original_handoff_binding_mismatch")
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            raise BridgeError(
                "local_reply_conflict", "Bound local reply evidence does not match this message"
            ) from None
        return {
            **proof,
            "run_id": run_id,
            "session_scope": "existing_visible_terminal",
            "completion_scope": "local_agent_turn",
            "reply_source": "bound_local_codex_rollout",
            "agent_confirmed": False,
            "agent_turn_completed": True,
            "agent_work_completion_verified": False,
            "project_completion_verified": False,
            "request_reply_satisfied": True,
            "response_sha256": digest(result["text"]),
            "response_preview": result["text"][:320],
            "response_truncated": False,
            "local_reply_result": result,
            "reconciled_without_input": recovered,
            "automatic_retry": False,
        }

    def _existing_reply(self, message_id):
        original = self.bridge.store.db.execute(
            "SELECT sender, recipient, acknowledged FROM messages WHERE id=?", (message_id,)
        ).fetchone()
        if original is None or original["acknowledged"] is None:
            return None
        reply = self.bridge.store.db.execute(
            "SELECT id FROM messages WHERE reply_to=? AND sender=? AND recipient=? "
            "AND kind IN ('result','answer') ORDER BY seq LIMIT 1",
            (message_id, original["recipient"], original["sender"]),
        ).fetchone()
        return reply["id"] if reply else None

    def _reconcile_recovered_handoffs(self, recipient=None):
        """Observe only waiters lost at startup; never touch a new running turn or send input."""
        for message_id in tuple(self.recovered_handoffs):
            with self.bridge.store.transaction():
                row = self.bridge.store.db.execute(
                    "SELECT j.message_id,j.state,j.evidence,j.run_id,m.sender,m.recipient "
                    "FROM message_jobs j JOIN messages m ON m.id=j.message_id "
                    "WHERE j.message_id=?",
                    (message_id,),
                ).fetchone()
                if row is not None and recipient is not None and row["recipient"] != recipient:
                    continue
                if row is None or row["state"] != "running" or not self._reply_can_finish(row):
                    self.recovered_handoffs.discard(message_id)
                    continue  # In particular, never reconcile an unknown or blocked history.
                try:
                    stored_evidence = json.loads(row["evidence"])
                except (TypeError, ValueError):
                    stored_evidence = None
                seal_reason = self._stored_seal_reason(
                    message_id, row["recipient"], row["run_id"], stored_evidence
                )
                if seal_reason == "hold_placed":
                    continue  # A hold keeps the recovered waiter; never complete it.
                if seal_reason is not None:
                    # Missing/replaced/drifted binding: no visible recovery completion
                    # and no repair; the stored evidence is preserved verbatim.
                    self.bridge.store.audit(
                        "message.claim_revalidation_failed",
                        "local",
                        None,
                        {"message_id": message_id, "run_id": row["run_id"],
                         "reason": seal_reason, "recovery": True},
                    )
                    self._finish(
                        message_id,
                        "unknown",
                        {
                            "reason": "claim_seal_broken",
                            "seal_reason": seal_reason,
                            "last_observation": stored_evidence
                            if isinstance(stored_evidence, dict)
                            else {"invalid_evidence_sha256": digest(row["evidence"])},
                            "automatic_retry": False,
                        },
                        "claim_seal_broken",
                        run_id=row["run_id"],
                    )
                    self.recovered_handoffs.discard(message_id)
                    continue
                local_handoff = self.bridge.store.db.execute(
                    "SELECT state,evidence FROM visible_handoffs WHERE id=? AND message_id=? "
                    "AND principal=? AND target=?",
                    (row["run_id"], message_id, row["sender"], row["recipient"]),
                ).fetchone()
                reply_id = self._existing_reply(message_id)
                if local_handoff and local_handoff["state"] == "completed":
                    if reply_id:
                        # A genuine authenticated return does not depend on the
                        # shape of an optional local cache. This handoff is already
                        # terminal; retain the existing principal read check.
                        try:
                            self.bridge.security.principal(row["sender"], "task.read")
                        except BridgeError as exc:
                            if exc.code != "forbidden":
                                raise
                            continue
                        evidence = json.loads(row["evidence"])
                        evidence.pop("local_reply_result", None)
                        if evidence.get("completion_scope") == "local_agent_turn":
                            evidence.pop("response_preview", None)
                            evidence.pop("response_sha256", None)
                        self._finish(
                            message_id,
                            "completed",
                            {
                                **evidence,
                                "completion_scope": "agent_turn",
                                "reply_source": "authenticated_bridge_mailbox",
                                "agent_confirmed": True,
                                "request_reply_satisfied": True,
                                "reason": "reply_already_recorded",
                                "reconciled_without_input": True,
                                "automatic_retry": False,
                            },
                            reply_id=reply_id,
                            run_id=row["run_id"],
                        )
                        self.recovered_handoffs.discard(message_id)
                        continue
                    try:
                        saved = json.loads(local_handoff["evidence"])
                        if not isinstance(saved, dict):
                            raise ValueError("invalid_local_handoff_evidence")
                        has_local = (
                            "local_reply_result" in saved
                            or saved.get("completion_scope") == "local_agent_turn"
                        )
                        if has_local:
                            local = self._local_reply_evidence(
                                message_id,
                                row["run_id"],
                                saved.get("local_reply_result"),
                                recovered=True,
                            )
                    except (ValueError, TypeError, AttributeError, RecursionError, BridgeError):
                        self._finish(
                            message_id,
                            "unknown",
                            {"reason": "local_reply_conflict", "automatic_retry": False},
                            "local_reply_conflict",
                        )
                        self.recovered_handoffs.discard(message_id)
                        continue
                    if has_local:
                        local = {
                            **local,
                            "claim_seal": stored_evidence["claim_seal"],
                            **(
                                {"managed_guidance_context":
                                 stored_evidence["managed_guidance_context"]}
                                if "managed_guidance_context" in stored_evidence
                                else {}
                            ),
                        }
                        self._finish(message_id, "completed", local, run_id=row["run_id"])
                        self.recovered_handoffs.discard(message_id)
                        continue
                if not reply_id:
                    continue
                evidence = json.loads(row["evidence"])
                try:
                    handoff = self.bridge.visible_handoffs.reconcile(
                        row["sender"], evidence["handoff_id"]
                    )
                except BridgeError as exc:
                    if exc.code != "forbidden":
                        raise
                    continue  # Revoked historical access must not stop other receiver work.
                if handoff["state"] != "completed":
                    continue
                self._finish(
                    message_id,
                    "completed",
                    {
                        **evidence,
                        "reason": "reply_already_recorded",
                        "reconciled_without_input": True,
                        "automatic_retry": False,
                    },
                    reply_id=reply_id,
                    run_id=row["run_id"],
                )
            self.recovered_handoffs.discard(message_id)

    def reconcile_completed_handoff(self, principal, handoff_id):
        """Explicit late-receipt correction; never restart an UNKNOWN receiver.

        The existing visible_handoff_status call owns this reconciliation. An
        authenticated reply alone is insufficient: the exact persisted run must
        already have an independently completed handoff for this original message.
        """
        self.bridge.security.principal(principal, "task.read")
        self.bridge.security.principal(principal, "message.read")
        with self.bridge.store.transaction():
            handoff = self.bridge.store.db.execute(
                "SELECT * FROM visible_handoffs WHERE id=? AND (principal=? OR target=?)",
                (handoff_id, principal, principal),
            ).fetchone()
            if handoff is None:
                raise BridgeError("not_found", "Visible handoff not found")
            message = self.messages._row(principal, handoff["message_id"])
            job = self.bridge.store.db.execute(
                "SELECT * FROM message_jobs WHERE message_id=?", (message["id"],)
            ).fetchone()
            unchanged = {"reconciled": False, "message_id": message["id"]}
            if job is None or job["state"] != "unknown":
                return {**unchanged, "state": job["state"] if job else None}
            if (
                handoff["state"] != "completed"
                or job["run_id"] != handoff_id
                or handoff["principal"] != message["sender"]
                or handoff["target"] != message["recipient"]
            ):
                return {**unchanged, "state": "unknown", "reason": "completion_unproven"}
            reply = self.bridge.store.db.execute(
                "SELECT id,body FROM messages WHERE reply_to=? AND sender=? AND recipient=? "
                "AND conversation_id=? AND kind IN ('answer','result') ORDER BY seq LIMIT 1",
                (
                    message["id"],
                    message["recipient"],
                    message["sender"],
                    message["conversation_id"],
                ),
            ).fetchone()
            try:
                previous = json.loads(job["evidence"])
            except (ValueError, TypeError, RecursionError):
                return {**unchanged, "state": "unknown", "reason": "invalid_prior_evidence"}
            if not isinstance(previous, dict):
                return {**unchanged, "state": "unknown", "reason": "invalid_prior_evidence"}
            fence = self._unknown_promotion_fence(job, previous)
            if fence is not None:
                return {**unchanged, "state": "unknown", "reason": fence}

            # Preserve the authenticated mailbox route whenever its ACK and
            # exact reply are present. Otherwise accept only a persisted local
            # Codex result that passes the same strict validator used at finish.
            if message["acknowledged"] is None or reply is None:
                try:
                    handoff_evidence = json.loads(handoff["evidence"])
                    local_result = (
                        handoff_evidence.get("local_reply_result")
                        if isinstance(handoff_evidence, dict)
                        else None
                    )
                    if local_result is None or not message["request_reply"]:
                        return {**unchanged, "state": "unknown", "reason": "completion_unproven"}
                    local = self._local_reply_evidence(
                        message["id"], handoff_id, local_result, recovered=True
                    )
                except (ValueError, TypeError, AttributeError, RecursionError):
                    return {**unchanged, "state": "unknown", "reason": "local_reply_conflict"}
                except BridgeError as exc:
                    if exc.code != "local_reply_conflict":
                        raise
                    return {**unchanged, "state": "unknown", "reason": "local_reply_conflict"}

                notice = self.bridge.store.db.execute(
                    "SELECT id FROM completion_notices WHERE source='message' AND source_id=? "
                    "ORDER BY seq DESC LIMIT 1",
                    (message["id"],),
                ).fetchone()
                evidence = {
                    **local,
                    "reason": "completed_local_handoff_reconciled",
                    "handoff_id": handoff_id,
                    "run_id": job["run_id"],
                    "completion_scope": "local_agent_turn",
                    "reply_source": "bound_local_codex_rollout",
                    "agent_confirmed": False,
                    "request_reply_satisfied": True,
                    "project_completion_verified": False,
                    "reconciled_without_input": True,
                    "automatic_retry": False,
                    "previous_state": "unknown",
                    "previous_error": job["error"],
                    "previous_finished": job["finished"],
                    "previous_evidence": previous,
                    "supersedes_notice_id": notice["id"] if notice else None,
                }
                self._record_finish(job, "completed", evidence)
                return {
                    "reconciled": True,
                    "message_id": message["id"],
                    "state": "completed",
                    "reply_source": "bound_local_codex_rollout",
                    "reconciled_without_input": True,
                }

            notice = self.bridge.store.db.execute(
                "SELECT id FROM completion_notices WHERE source='message' AND source_id=? "
                "ORDER BY seq DESC LIMIT 1",
                (message["id"],),
            ).fetchone()
            evidence = {
                "reason": "completed_handoff_reply_reconciled",
                "handoff_id": handoff_id,
                "run_id": job["run_id"],
                "completion_scope": "agent_turn",
                "reply_source": "authenticated_bridge_mailbox",
                "agent_confirmed": True,
                "request_reply_satisfied": True,
                "project_completion_verified": False,
                "reconciled_without_input": True,
                "automatic_retry": False,
                "response_sha256": digest(reply["body"]),
                "response_preview": reply["body"][:320],
                "previous_state": "unknown",
                "previous_error": job["error"],
                "previous_finished": job["finished"],
                "previous_evidence": previous,
                "supersedes_notice_id": notice["id"] if notice else None,
            }
            self._record_finish(job, "completed", evidence, reply_id=reply["id"])
            return {
                "reconciled": True,
                "message_id": message["id"],
                "state": "completed",
                "reply_id": reply["id"],
                "reconciled_without_input": True,
            }

    def _finish(self, message_id, state, evidence, error=None, reply_id=None, *, run_id=None):
        """run_id given: only the claiming run may write (atomic owner check)."""
        job = self.bridge.store.db.execute(
            "SELECT * FROM message_jobs WHERE message_id=?", (message_id,)
        ).fetchone()
        if job["state"] not in {"queued", "running"}:
            return False  # same job must not create a second completion
        if run_id is not None and (job["state"] != "running" or job["run_id"] != run_id):
            return False  # owner handoff: foreign run keeps its own history
        self._record_finish(job, state, evidence, error=error, reply_id=reply_id)
        return True

    SEAL_FAILURE_ERRORS = frozenset({"claim_seal_broken", "guidance_context_changed"})

    def _unknown_promotion_fence(self, job, previous):
        """Recovery fence for UNKNOWN -> completed (caller owns the transaction).

        A seal failure marker, damaged seal/context binding or an active hold
        keeps the job UNKNOWN; a late ACK/reply never overrides it. Strictly
        fail-closed: evidence without a claim_seal is never promotable.
        """
        if job["error"] in self.SEAL_FAILURE_ERRORS:
            return "seal_failure_recorded"
        if not isinstance(previous, dict):
            return "invalid_prior_evidence"
        if previous.get("claim_seal_mismatch") or previous.get("reason") == "claim_seal_broken":
            return "seal_failure_recorded"
        held = self.bridge.store.db.execute(
            "SELECT 1 FROM queue_holds WHERE queue_id='messages' AND item_id=?",
            (job["message_id"],),
        ).fetchone()
        if held is not None:
            return "hold_placed"
        if "claim_seal" not in previous:
            return "seal_missing"
        seal = previous["claim_seal"]
        row = self.bridge.store.db.execute(
            "SELECT * FROM messages WHERE id=?", (job["message_id"],)
        ).fetchone()
        context = previous.get("managed_guidance_context")
        try:
            if (
                row is None
                or not isinstance(seal, dict)
                or seal.get("run_id") != job["run_id"]
                or self.claim_seal(row, job["run_id"], seal.get("execution_cwd"), context) != seal
            ):
                return "seal_broken"
        except (KeyError, TypeError, ValueError, RecursionError):
            return "seal_broken"
        return None

    def _record_finish(self, job, state, evidence, error=None, reply_id=None):
        """Caller has validated the exact prior state and owns the transaction."""
        from kirabridge.completion_manager import completion_payload, record_notice

        message_id = job["message_id"]
        if job["state"] == "unknown":
            # Single UNKNOWN promotion path: re-check the fence in the same
            # transaction as the CAS write below.
            try:
                previous = json.loads(job["evidence"])
            except (TypeError, ValueError, RecursionError):
                previous = None
            fence = self._unknown_promotion_fence(job, previous)
            if fence is not None:
                raise BridgeError("receiver_claim_changed", "UNKNOWN job is fenced: " + fence)
        now = time.time()
        # Compare-and-set on the exact observed state/run_id (ABA fence): a
        # requeue/new claim between observation and write must not be finished.
        updated = self.bridge.store.db.execute(
            "UPDATE message_jobs SET state=?,finished=?,evidence=?,error=?,reply_id=? "
            "WHERE message_id=? AND state=? AND run_id IS ?",
            (state, now, canonical(evidence), error, reply_id, message_id, job["state"],
             job["run_id"]),
        ).rowcount
        if updated != 1:
            raise BridgeError("receiver_claim_changed", "Job changed before finish write")
        row = self.bridge.store.db.execute(
            "SELECT * FROM messages WHERE id=?", (message_id,)
        ).fetchone()
        self.messages._event(
            message_id,
            "message.processing_" + state,
            row["recipient"],
            {"evidence_sha256": digest(evidence), "error": error},
        )
        seq = self.bridge.store.db.execute(
            "SELECT max(seq) FROM message_events WHERE message_id=?", (message_id,)
        ).fetchone()[0]
        task = {
            "id": row["task_id"] or job["run_id"] or "message-" + message_id,
            "message_id": message_id,
            "operation": "message.agent_turn",
            "agent": row["recipient"],
            "state": state,
            "evidence": evidence,
            "error": {"code": error} if error else None,
            "updated": now,
            "finished": now,
            "result": {"text": evidence.get("response_preview", "")},
        }
        delivery_only = evidence.get("completion_scope") == "visible_input_delivery"
        if delivery_only:
            task["operation"] = "message.visible_input_delivery"
            task["result"] = {
                "submitted": True,
                "agent_confirmed": False,
                "agent_work_completion_verified": False,
                "request_reply_satisfied": False,
                "scope": "visible_input_delivery",
            }
        local_reply = evidence.get("completion_scope") == "local_agent_turn"
        if local_reply:
            task["operation"] = "message.local_agent_turn"
            task["result"] = evidence["local_reply_result"]
        payload = completion_payload(task, seq, source="message")
        payload.update(
            message_id=message_id,
            run_id=job["run_id"],
            conversation_id=row["conversation_id"],
            reply_id=reply_id,
        )
        if job["state"] == "unknown" and evidence.get("supersedes_notice_id"):
            # Only explicit proven reconciliation can reach this writer from
            # UNKNOWN. Existing notices stay immutable, including their receipts.
            payload["supersedes"] = evidence["supersedes_notice_id"]
        if delivery_only:
            payload.update(
                completion_scope="visible_input_delivery",
                agent_confirmed=False,
                agent_work_completion_verified=False,
                request_reply_satisfied=False,
                summary="Message text submitted; agent acknowledgement and reply unconfirmed",
            )
        if evidence.get("externally_acknowledged"):
            payload["outcome"] = "not_executed"
            payload["summary"] = "Message acknowledged externally; no receiver turn executed"
        route = self.bridge.store.db.execute(
            "SELECT target FROM message_completion_routes WHERE message_id=?", (message_id,)
        ).fetchone()
        record_notice(
            self.bridge.store,
            row["sender"],
            route[0] if route else "default",
            "message",
            message_id,
            seq,
            payload,
        )

    def _claim(self, message_id, *, direct=False, interim=False):
        config = self.bridge.config.messaging
        with self.bridge.store.transaction():
            row = self.bridge.store.db.execute(
                "SELECT m.* FROM messages m JOIN message_jobs j ON j.message_id=m.id "
                "WHERE m.id=? AND j.state='queued' "
                "AND NOT EXISTS (SELECT 1 FROM queue_holds h WHERE "
                "h.queue_id='messages' AND h.item_id=m.id)",
                (message_id,),
            ).fetchone()
            if not row:
                return None
            if not self.bridge.store.can_claim(row["created"]):
                return None
            if row["acknowledged"]:
                self._finish(message_id, "completed", {"externally_acknowledged": True})
                return None

            def blocked(reason):
                evidence = {"reason": reason}
                if direct:
                    evidence.update(
                        phase="direct_admission",
                        terminal_input_attempted=False,
                        automatic_retry=False,
                    )
                self._finish(message_id, "blocked", evidence)
                if direct:
                    # Only this fresh direct attempt was refused before claim.
                    # Its body must not be delivered later by an inbox poll.
                    self.bridge.queues._place_hold(
                        row["sender"], "messages", message_id, "direct_admission_rejected"
                    )
                    self.bridge.store.audit(
                        "queue.admission_rejected",
                        row["sender"],
                        None,
                        {
                            "queue": "messages",
                            "item_id": message_id,
                            "reason": reason,
                            "terminal_input_attempted": False,
                            "history_preserved": True,
                        },
                    )

            if row["created"] <= time.time() - self.bridge.config.queue_stale_seconds:
                # Late delivery could duplicate work already done in the visible terminal.
                blocked("stale_queue_expired")
                return None
            # Both run ceilings are rolling one-hour windows that bound provider
            # cost and queue growth. They are not identity, authentication or
            # dedupe guards: those are enforced before this point and must never
            # depend on these counters.
            since = time.time() - 3600
            count = self.bridge.store.db.execute(
                "SELECT count(*) FROM message_jobs j JOIN messages m ON m.id=j.message_id "
                "WHERE m.conversation_id=? AND j.claimed>?",
                (row["conversation_id"], since),
            ).fetchone()[0]
            if not interim and count >= config.max_runs_per_conversation:
                blocked("conversation_run_limit")
                return None
            count = self.bridge.store.db.execute(
                "SELECT count(*) FROM message_jobs j JOIN messages m ON m.id=j.message_id "
                "WHERE m.recipient=? AND j.claimed>?",
                (row["recipient"], since),
            ).fetchone()[0]
            if not interim and count >= config.max_runs_per_hour:
                blocked("hourly_run_limit")
                return None
            run_id = "channel-" + uuid.uuid4().hex
            scope = (
                "separate_managed_session"
                if separate_managed_eligible(self.bridge.config, row["created"])
                else "existing_visible_terminal"
                if self.bridge.config.visible_handoffs.enabled
                else "separate_managed_session"
            )
            evidence = {"session_scope": scope}
            cwd = config.receivers[row["recipient"]].cwd
            if not direct and not interim:
                from kirabridge.message_manager.guidance_context import prepare

                if context := prepare(self.bridge, row):
                    context["claim_run_id"] = run_id
                    evidence["managed_guidance_context"] = context
            evidence["claim_seal"] = self.claim_seal(
                row, run_id, cwd, evidence.get("managed_guidance_context")
            )
            self.bridge.store.db.execute(
                "UPDATE message_jobs SET state='running',run_id=?,claimed=?,evidence=?,"
                "execution_cwd=? "
                "WHERE message_id=?",
                (
                    run_id,
                    time.time(),
                    canonical(evidence),
                    cwd,
                    message_id,
                ),
            )
            self.messages._event(
                message_id,
                "message.processing_claimed",
                row["recipient"],
                {"run_id": run_id, "session_scope": scope},
            )
            message = dict(row)
            if "managed_guidance_context" in evidence:
                # Keep the original binding even if later job evidence changes;
                # losing stored proof must never turn this claim into raw work.
                message["_managed_guidance_context"] = evidence["managed_guidance_context"]
            message["_claim_seal"] = evidence["claim_seal"]
            return message, run_id

    def _waiting(self, message_id, reason, observation=None):
        """A pre-dispatch observation is not a failed turn or an input attempt."""
        evidence = {
            "session_scope": "existing_visible_terminal",
            "waiting_for_visible_target": True,
            "reason": reason,
            "terminal_input_attempted": False,
            "waiting_message": {
                "visible_target_busy": "Eine frühere Übergabe muss noch abgeglichen werden.",
                "visible_target_not_ready": "Das Agentenfenster ist noch nicht eingabebereit.",
                "desktop_locked": "Mac gesperrt; die Nachricht wartet ohne Eingabe.",
                "desktop_session_inactive": "Die Mac-Sitzung ist nicht am Bildschirm aktiv.",
                "visible_target_working": "Der angebundene Agent arbeitet; Nachricht wartet.",
                "visible_input_not_empty": "Vorhandener Eingabetext wird nicht überschrieben.",
                "visible_target_scrolled": "Zur aktuellen Eingabeansicht zurückkehren.",
                "visible_target_unknown": "Bereitschaft nicht eindeutig; Diagnose ansehen.",
            }[reason],
        }
        if observation is not None:
            evidence["observation"] = observation
        with self.bridge.store.transaction():
            row = self.bridge.store.db.execute(
                "SELECT state,evidence FROM message_jobs WHERE message_id=?", (message_id,)
            ).fetchone()
            previous = json.loads(row["evidence"]) if row else {}
            if "receiver_retry" in previous:
                evidence["receiver_retry"] = previous["receiver_retry"]

            def comparable(value):
                value = {**value}
                if "observation" in value:
                    value["observation"] = {**value["observation"]}
                    value["observation"].pop("observed_at", None)
                return value

            if row and row["state"] == "queued" and previous != evidence:
                self.bridge.store.db.execute(
                    "UPDATE message_jobs SET evidence=? WHERE message_id=?",
                    (canonical(evidence), message_id),
                )
                if comparable(previous) != comparable(evidence):
                    self.messages._event(
                        message_id, "message.waiting_for_visible_target", "local", evidence
                    )

    def _queue_unsent(self, message_id, reason, run_id, state):
        """Only without input or with a recorded preinput abort; never replay uncertainty."""
        if reason not in self.WAIT_REASONS or state not in {"running", "failed"}:
            return False
        with self.bridge.store.transaction():
            row = self.bridge.store.db.execute(
                "SELECT j.*,m.acknowledged FROM message_jobs j JOIN messages m "
                "ON m.id=j.message_id WHERE j.message_id=?",
                (message_id,),
            ).fetchone()
            handoffs = self.bridge.store.db.execute(
                "SELECT state,evidence FROM visible_handoffs WHERE id=? OR message_id=?",
                (run_id, message_id),
            ).fetchall()
            if (
                not row
                or row["state"] != state
                or row["run_id"] != run_id
                or row["started"] is not None
                or row["acknowledged"] is not None
                or state == "failed"
                and row["error"] != reason
                or any(
                    h["state"] != "interrupted"
                    or json.loads(h["evidence"]).get("preinput_abort") is not True
                    or json.loads(h["evidence"]).get("terminal_input_attempted") is not False
                    for h in handoffs
                )
            ):
                return False
            if (
                self.bridge.store.db.execute(
                    "UPDATE message_jobs SET state='queued',run_id=NULL,claimed=NULL,"
                    "started=NULL,finished=NULL,error=NULL,reply_id=NULL,execution_cwd=NULL "
                    "WHERE message_id=? AND state=? AND run_id=? AND started IS NULL",
                    (message_id, state, run_id),
                ).rowcount
                != 1
            ):
                return False  # ABA: never requeue a different/started claim
            evidence = {
                "previous_run_id": run_id,
                "previous_state": state,
                "reason": reason,
                "terminal_input_attempted": False,
            }
            self.messages._event(message_id, "message.unsent_requeued", "local", evidence)
            self.bridge.store.audit(
                "message.unsent_requeued", "local", None, {"message_id": message_id, **evidence}
            )
            self._waiting(message_id, reason)
        return True

    def resume_unsent(self, message_id):
        """Explicit internal repair of a proven pre-input failure, not automatic replay."""
        row = self.bridge.store.db.execute(
            "SELECT error,run_id FROM message_jobs WHERE message_id=?", (message_id,)
        ).fetchone()
        if not row or not self._queue_unsent(message_id, row["error"], row["run_id"], "failed"):
            raise BridgeError(
                "delivery_reconciliation_required", "An input may have occurred; do not resend"
            )
        self.messages.wake.set()

    def _preflight_failed(self, message_id, recipient, code):
        """Persist failures before claim; only connection setup can be retried safely."""
        with self.bridge.store.transaction():
            row = self.bridge.store.db.execute(
                "SELECT state,evidence FROM message_jobs WHERE message_id=?", (message_id,)
            ).fetchone()
            if not row or row["state"] != "queued":
                return
            previous = json.loads(row["evidence"])
            now = time.time()
            retry = previous.get("receiver_retry", {})
            first = retry.get("first_failure_at", now)
            attempts = retry.get("attempts", 0) + 1
            deadline = retry.get(
                "deadline", first + self.bridge.config.messaging.receivers[recipient].timeout
            )
            evidence = {
                "phase": "receiver_connect",
                "reason": code,
                "terminal_input_attempted": False,
                "receiver_retry": {
                    "first_failure_at": first,
                    "attempts": attempts,
                    "deadline": deadline,
                },
            }
            if code != "peer_connection" or now >= deadline:
                self._finish(message_id, "failed", evidence, code)
                return
            evidence["waiting_for_receiver"] = True
            evidence["receiver_retry"]["next_attempt_at"] = min(
                deadline, now + min(30, 2 ** min(attempts, 5))
            )
            self.bridge.store.db.execute(
                "UPDATE message_jobs SET evidence=? WHERE message_id=?",
                (canonical(evidence), message_id),
            )
            self.messages._event(message_id, "message.waiting_for_receiver", "local", evidence)

    def _unexpected_dispatch_failure(self, message_id):
        """Never replay an unexpected fault after claim or expose exception contents."""
        with self.bridge.store.transaction():
            row = self.bridge.store.db.execute(
                "SELECT state,evidence FROM message_jobs WHERE message_id=?", (message_id,)
            ).fetchone()
            if not row or row["state"] not in {"queued", "running"}:
                return
            unclaimed = row["state"] == "queued"
            code = "receiver_preflight_failed" if unclaimed else "receiver_interrupted"
            evidence = {
                "reason": code,
                "phase": "receiver_preflight" if unclaimed else "receiver_claimed",
                "last_observation_sha256": digest(row["evidence"]),
            }
            if unclaimed:
                evidence["terminal_input_attempted"] = False
            self._finish(message_id, "failed" if unclaimed else "unknown", evidence, code)

    async def _dispatch_next(self, recipient=None, *, include_visible=True):
        # One oldest message per recipient: a busy Codex must not hide ready Grok.
        # A cutoff removes older rows from that contest so they are neither
        # dispatched nor able to hide a newer eligible message.
        cutoff = self.bridge.config.messaging.separate_managed_after
        rows = self.bridge.store.db.execute(
            "SELECT m.id,m.sender,m.recipient,m.created,m.acknowledged,j.evidence FROM messages m "
            "JOIN message_jobs j ON j.message_id=m.id WHERE j.state='queued' "
            "AND NOT EXISTS (SELECT 1 FROM queue_holds h WHERE "
            "h.queue_id='messages' AND h.item_id=m.id) "
            "AND (? IS NULL OR m.created>=?) "
            "AND (? IS NULL OR m.recipient=?) "
            "AND NOT EXISTS (SELECT 1 FROM messages older JOIN message_jobs q "
            "ON q.message_id=older.id WHERE q.state='queued' "
            "AND NOT EXISTS (SELECT 1 FROM queue_holds h WHERE "
            "h.queue_id='messages' AND h.item_id=older.id) "
            "AND (? IS NULL OR older.created>=?) "
            "AND older.recipient=m.recipient AND older.seq<m.seq) ORDER BY m.seq LIMIT 17",
            (cutoff, cutoff, recipient, recipient, cutoff, cutoff),
        ).fetchall()
        for row in rows:
            if row["acknowledged"] is not None:
                # External ACK can close only this never-claimed delivery;
                # it never restarts a historical visible turn.
                self._claim(row["id"])
                continue
            if (
                not include_visible
                and self.bridge.config.visible_handoffs.enabled
                and not separate_managed_eligible(self.bridge.config, row["created"])
            ):
                # Old visible backlog is inventory, never fresh authorization.
                # New visible work has one runtime-owned direct admission.
                continue
            if row["recipient"] not in self.bridge.config.messaging.receivers:
                continue
            try:
                if not self.bridge.store.can_claim(row["created"]):
                    continue
                if row["acknowledged"] is not None:
                    # Completes externally received work without a CLI turn.
                    self._claim(row["id"])
                    continue
                retry = json.loads(row["evidence"]).get("receiver_retry", {})
                now = time.time()
                if retry and now >= retry["deadline"]:
                    self._preflight_failed(row["id"], row["recipient"], "peer_connection")
                    continue
                if now < retry.get("next_attempt_at", 0):
                    continue
                if self.bridge.config.visible_handoffs.enabled and not separate_managed_eligible(
                    self.bridge.config, row["created"]
                ):
                    try:
                        await self.bridge.visible_handoffs.dispatch_ready(
                            row["sender"], row["recipient"]
                        )
                    except BridgeError as exc:
                        if exc.code in self.WAIT_REASONS:
                            self._waiting(row["id"], exc.code, getattr(exc, "observation", None))
                            continue
                        # Missing/stale targets retain the existing explicit failure path.
                async with MCPClientPool(call_timeout=15) as pool:
                    await pool.connect(peer(self.bridge.config, row["recipient"]))
                    claimed = self._claim(row["id"])
                    if claimed:
                        await self._process(pool, *claimed)
                        return True
            except BridgeError as exc:
                self._preflight_failed(row["id"], row["recipient"], exc.code)
            except Exception:
                self._unexpected_dispatch_failure(row["id"])
        return False

    async def _loop(self):
        # Waiting for Codex's final reply must not prevent a ready Grok from
        # receiving delegated work. Aliases of one physical pane share an owner.
        locks = {}
        async with asyncio.TaskGroup() as group:
            for recipient in self.bridge.config.messaging.receivers:
                binding = self.bridge.config.visible_handoffs.bindings.get(recipient)
                target = (
                    ("pane", binding.pane_id)
                    if self.bridge.config.visible_handoffs.enabled and binding
                    else ("recipient", recipient)
                )
                group.create_task(
                    self._recipient_loop(recipient, locks.setdefault(target, asyncio.Lock()))
                )

    async def _recipient_loop(self, recipient, lock):
        fault_recorded = False
        while not self.stopping:
            self.messages.wake.clear()
            try:
                async with lock:
                    if self.stopping:
                        return
                    self._reconcile_recovered_handoffs(recipient)
                    from kirabridge.message_manager.guidance import consume, ready

                    if ready(self, recipient):
                        async with MCPClientPool(call_timeout=15) as pool:
                            await pool.connect(peer(self.bridge.config, recipient))
                            if await consume(self, recipient, pool):
                                continue
                    dispatched = await self._dispatch_next(recipient, include_visible=False)
                fault_recorded = False
                if dispatched:
                    continue
            except Exception:
                # A storage/observation fault outside one row must not cancel siblings.
                # Cancellation itself remains a BaseException and still propagates.
                if not fault_recorded:
                    try:
                        with self.bridge.store.transaction():
                            self.bridge.store.audit(
                                "message.receiver_loop_failed",
                                recipient,
                                None,
                                {"reason": "receiver_loop_failed"},
                            )
                    except Exception:
                        pass  # The store itself may be unavailable; retry only the observation.
                    fault_recorded = True
            try:
                await asyncio.wait_for(self.messages.wake.wait(), 2)
            except TimeoutError:
                pass

    CLAIM_FIELDS = ("body", "request_reply", "kind", "sender", "recipient", "conversation_id")

    def _claim_contract(self, message, run_id, context=None):
        claim = {
            "run_id": run_id,
            "snapshot_sha256": digest({k: message[k] for k in self.CLAIM_FIELDS}),
        }
        if context is not None:
            # Server re-checks the stored pinned binding and all its sources at ACK write.
            claim["context_sha256"] = digest(context)
        return claim

    SEAL_SCHEMA = "kirabridge.message-claim-seal.v1"
    SEAL_FIELDS = (
        "id", "seq", "position", "body", "request_reply", "kind", "sender", "recipient",
        "conversation_id", "reply_to", "task_id", "depth", "idem", "request_hash", "created",
    )

    def claim_seal(self, row, run_id, cwd, context=None):
        """Hash-bound claim seal: current message fields + run_id + cwd + pinned context."""
        fields = {k: row[k] for k in self.SEAL_FIELDS}
        return {
            "schema": self.SEAL_SCHEMA,
            "run_id": run_id,
            "execution_cwd": cwd,
            "request_reply": bool(row["request_reply"]),
            "fields_sha256": digest(fields),
            "context_sha256": digest(context) if context is not None else None,
            "seal_sha256": digest(
                {"fields": fields, "run_id": run_id, "cwd": cwd,
                 "context": digest(context) if context is not None else None}
            ),
        }

    def _seal_reason(self, message_id, recipient, run_id, seal, context=None):
        """Pure fresh read (caller owns the transaction); None means the seal holds."""
        row = self.bridge.store.db.execute(
            "SELECT m.*,j.state AS job_state,j.run_id AS job_run_id,"
            "j.execution_cwd AS job_cwd,j.evidence AS job_evidence FROM messages m "
            "JOIN message_jobs j ON j.message_id=m.id WHERE m.id=?",
            (message_id,),
        ).fetchone()
        held = self.bridge.store.db.execute(
            "SELECT 1 FROM queue_holds WHERE queue_id='messages' AND item_id=?",
            (message_id,),
        ).fetchone()
        receiver = self.bridge.config.messaging.receivers.get(recipient)
        try:
            stored_evidence = json.loads(row["job_evidence"]) if row else None
        except (TypeError, ValueError, RecursionError):
            stored_evidence = None
        if not isinstance(stored_evidence, dict):
            stored_evidence = {}
        stored = stored_evidence.get("claim_seal")
        reason = None
        if row is None:
            reason = "message_missing"
        elif not isinstance(seal, dict) or seal.get("run_id") != run_id:
            reason = "seal_missing"
        elif row["job_state"] != "running":
            reason = "job_state_changed"
        elif row["job_run_id"] != run_id:
            reason = "run_owner_changed"
        elif held is not None:
            reason = "hold_placed"
        elif receiver is None or row["job_cwd"] != receiver.cwd:
            reason = "receiver_scope_changed"
        elif stored != seal or self.claim_seal(row, run_id, row["job_cwd"], context) != seal:
            reason = "seal_broken"
        elif not self._stored_context_intact(stored_evidence, context):
            # The stored managed_guidance_context binding must still equal the
            # claim's process copy; a removed/altered binding is never repaired.
            reason = "context_binding_changed"
        return reason

    @staticmethod
    def _stored_context_intact(stored_evidence, context):
        if not isinstance(stored_evidence, dict):
            return False
        if context is None:
            return stored_evidence.get("managed_guidance_context") is None
        if "managed_guidance_context" not in stored_evidence:
            return False
        try:
            return digest(stored_evidence["managed_guidance_context"]) == digest(context)
        except (TypeError, ValueError, RecursionError):
            return False

    # Stored claim/context integrity damage, as opposed to a normal owner/run
    # handoff or state change. These always settle fail-closed.
    SEAL_INTEGRITY_REASONS = frozenset(
        {"message_missing", "seal_missing", "seal_broken", "context_binding_changed"}
    )

    def _stored_binding_intact(self, message_id, seal, context):
        """Pure read (caller owns the transaction): stored seal/context still ours."""
        row = self.bridge.store.db.execute(
            "SELECT evidence FROM message_jobs WHERE message_id=?", (message_id,)
        ).fetchone()
        try:
            stored = json.loads(row["evidence"]) if row else None
        except (TypeError, ValueError, RecursionError):
            return False
        return (
            isinstance(stored, dict)
            and isinstance(seal, dict)
            and stored.get("claim_seal") == seal
            and self._stored_context_intact(stored, context)
        )

    def _seal_failed(self, message_id, run_id, reason, seal=None, context=None):
        with self.bridge.store.transaction():
            self.bridge.store.audit(
                "message.claim_revalidation_failed",
                "local",
                None,
                {"message_id": message_id, "run_id": run_id, "reason": reason},
            )
            integrity = reason in self.SEAL_INTEGRITY_REASONS
            if reason == "seal_broken" and self._stored_binding_intact(message_id, seal, context):
                # Stored seal/context untouched: plain message field drift, a
                # normal claim change (the fence still recomputes the seal).
                integrity = False
        error = BridgeError("guidance_context_changed", "Claim seal broken: " + reason)
        error.seal_integrity_reason = reason if integrity else None
        raise error

    def verify_seal(self, message, run_id, seal, context=None):
        """Central fresh read: job running with same run_id, no hold, no field drift."""
        with self.bridge.store.transaction():
            reason = self._seal_reason(message["id"], message["recipient"], run_id, seal, context)
        if reason is not None:
            self._seal_failed(message["id"], run_id, reason, seal, context)

    def _stored_seal_reason(self, message_id, recipient, run_id, evidence):
        """Recovery: the stored seal must still bind the fresh message/run/cwd/context."""
        if not isinstance(evidence, dict):
            return "seal_missing"
        return self._seal_reason(
            message_id,
            recipient,
            run_id,
            evidence.get("claim_seal"),
            evidence.get("managed_guidance_context"),
        )

    def _revalidate_claim(self, message, run_id, *, receipt=None, acknowledged=False):
        """Claim contract for work without managed context (same blocking set).

        A change of body/request_reply/routing, job state (incl. UNKNOWN),
        run_id owner, worktree, receipt/ACK state or a new hold blocks the next
        core step. Never refreshes the claimed snapshot.
        """
        message_id = message["id"]
        with self.bridge.store.transaction():
            row = self.bridge.store.db.execute(
                "SELECT m.*,j.state AS job_state,j.run_id AS job_run_id,"
                "j.execution_cwd AS job_cwd FROM messages m "
                "JOIN message_jobs j ON j.message_id=m.id WHERE m.id=?",
                (message_id,),
            ).fetchone()
            held = self.bridge.store.db.execute(
                "SELECT 1 FROM queue_holds WHERE queue_id='messages' AND item_id=?",
                (message_id,),
            ).fetchone()
            receiver = self.bridge.config.messaging.receivers.get(message["recipient"])
            reason = None
            if row is None:
                reason = "message_missing"
            elif any(row[key] != message[key] for key in self.CLAIM_FIELDS):
                reason = "message_changed"
            elif row["job_state"] != "running":
                reason = "job_state_changed"
            elif row["job_run_id"] != run_id:
                reason = "run_owner_changed"
            elif receiver is None or row["job_cwd"] != receiver.cwd:
                reason = "receiver_scope_changed"
            elif held is not None:
                reason = "hold_placed"
            elif acknowledged is not None and (row["acknowledged"] is not None) != acknowledged:
                reason = "acknowledged_elsewhere"
            elif receipt is not None and row["receipt"] != receipt:
                reason = "receipt_changed"
            if reason is not None:
                self.bridge.store.audit(
                    "message.claim_revalidation_failed",
                    "local",
                    None,
                    {"message_id": message_id, "run_id": run_id, "reason": reason},
                )
        if reason is not None:
            raise BridgeError("claim_changed", "Claimed message changed: " + reason)

    async def _process(
        self, pool, message, run_id, *, delivery_event=None, delivery_binding=None, interim=None
    ):
        message_id, recipient = message["id"], message["recipient"]
        limits = self.bridge.config.messaging
        receiver = limits.receivers[recipient]
        claimed = self.bridge.store.db.execute(
            "SELECT evidence FROM message_jobs WHERE message_id=?", (message_id,)
        ).fetchone()
        # Stored evidence is untrusted at process start: malformed JSON or a
        # non-object never escapes to DirectDelivery settlement (which would
        # replace it); it is settled fail-closed below, kept verbatim.
        try:
            claimed_evidence = json.loads(claimed["evidence"])
        except (TypeError, ValueError, RecursionError):
            claimed_evidence = None
        start_damage = None if isinstance(claimed_evidence, dict) else "seal_broken"
        if start_damage is not None:
            claimed_evidence = {}
        context = message.get("_managed_guidance_context")
        if context is None:
            context = claimed_evidence.get("managed_guidance_context")
        seal = message.get("_claim_seal") or claimed_evidence.get("claim_seal")
        # request_reply comes only from the seal, never from a later read.
        request_reply = bool(seal.get("request_reply")) if isinstance(seal, dict) else None
        adapter_attempted = False
        visible = False
        reply_id = None

        def owns_claim():
            # Every claim, managed context or not, is bound to its exact run_id.
            return (
                self.bridge.store.db.execute(
                    "SELECT 1 FROM message_jobs WHERE message_id=? "
                    "AND state='running' AND run_id=?",
                    (message_id, run_id),
                ).fetchone()
                is not None
            )

        def verify_seal_now():
            try:
                self.verify_seal(message, run_id, seal, context)
            except BridgeError as exc:
                if context is not None:
                    raise
                integrity = getattr(exc, "seal_integrity_reason", None)
                if integrity is not None:
                    # Integrity damage keeps a stable fail-closed code without
                    # managed context too; never downgraded to claim_changed.
                    error = BridgeError("claim_seal_broken", "Claim seal broken: " + integrity)
                    error.seal_integrity_reason = integrity
                    raise error from None
                raise BridgeError("claim_changed", "Claim seal broken") from None

        def validate_context(*, receipt=None, acknowledged=False):
            verify_seal_now()
            if context is not None:
                # Pinned managed scope: guidance_context.validate_current owns
                # body/request_reply/state/run_id/hold/receipt checks.
                from kirabridge.message_manager.guidance_context import render_pinned

                try:
                    return render_pinned(
                        self.bridge,
                        message,
                        context,
                        run_id=run_id,
                        receipt=receipt,
                        acknowledged=acknowledged,
                    )
                except BridgeError as exc:
                    with self.bridge.store.transaction():
                        self.bridge.store.audit(
                            "message.claim_revalidation_failed",
                            "local",
                            None,
                            {"message_id": message_id, "run_id": run_id, "reason": exc.code},
                        )
                    raise
            # Work without managed context: same blocking set, previously unchecked.
            expect = None if adapter_attempted and visible else acknowledged
            self._revalidate_claim(message, run_id, receipt=receipt, acknowledged=expect)
            return message["body"]

        def retain_context(evidence):
            if isinstance(seal, dict):
                evidence = {**evidence, "claim_seal": seal}
            if context is None:
                return evidence
            return {**evidence, "managed_guidance_context": context}

        def failure_evidence(integrity=None):
            # Terminal failure write (caller owns the finish transaction): read
            # the stored evidence fresh in that same transaction, keep our seal
            # only if the stored one is still identical; otherwise record the
            # drift and leave the stored value verbatim inside last_observation.
            observed = self.bridge.store.db.execute(
                "SELECT evidence FROM message_jobs WHERE message_id=?", (message_id,)
            ).fetchone()[0]
            observation = last_observation(observed)
            stored = observation.get("claim_seal") if isinstance(observation, dict) else None
            evidence = {"run_id": run_id, "last_observation": observation}
            if integrity is not None:
                evidence["seal_failure_reason"] = integrity
            if stored != seal or not self._stored_context_intact(observation, context):
                # No top-level process context/seal: the damaged stored binding
                # stays only inside last_observation, never repaired.
                evidence["claim_seal_mismatch"] = True
                return evidence
            return retain_context(evidence)

        def stored_damage():
            # Caller owns the transaction: integrity reason if the stored seal or
            # context binding no longer matches this claim, else None.
            observed = self.bridge.store.db.execute(
                "SELECT evidence FROM message_jobs WHERE message_id=?", (message_id,)
            ).fetchone()[0]
            observation = last_observation(observed)
            if not isinstance(observation, dict) or observation.get("claim_seal") != seal:
                return "seal_broken"
            if not self._stored_context_intact(observation, context):
                return "context_binding_changed"
            return None

        def last_observation(raw):
            try:
                return json.loads(raw)
            except (TypeError, ValueError, RecursionError):
                # Unparsable stored evidence stays byte-identical (never repaired).
                return {"invalid_evidence": raw, "invalid_evidence_sha256": digest(raw)}

        async def call(tool, arguments):
            result = await pool.call("daemon", tool, arguments)
            content = result.structuredContent
            if result.isError or not isinstance(content, dict) or content.get("error"):
                error = content.get("error") if isinstance(content, dict) else None
                if isinstance(error, dict) and error.get("code") == "claim_changed":
                    # Atomic ACK contract rejected: same UNKNOWN/no-replay handling.
                    raise BridgeError("claim_changed", "Claimed message changed at ACK")
                raise BridgeError("receiver_protocol", "Recipient MCP call was rejected")
            return content

        def sealed_write(evidence, *, start=False):
            # Fresh seal check and evidence write in ONE transaction: a removed,
            # replaced or drifted stored seal (or hold/run_id/state/body drift) is
            # never overwritten from this process's snapshot; abort instead.
            # Adapters call running/progress directly before visible input, so
            # this is also the last fence immediately before every input effect.
            evidence = retain_context(evidence)
            with self.bridge.store.transaction():
                reason = self._seal_reason(message_id, recipient, run_id, seal, context)
                if reason is None:
                    if start:
                        self.bridge.store.db.execute(
                            "UPDATE message_jobs SET started=COALESCE(started,?) "
                            "WHERE message_id=? AND state='running' AND run_id=?",
                            (time.time(), message_id, run_id),
                        )
                    self.bridge.store.db.execute(
                        "UPDATE message_jobs SET evidence=? WHERE message_id=? "
                        "AND state='running' AND run_id=?",
                        (canonical(evidence), message_id, run_id),
                    )
                    self.messages._event(
                        message_id,
                        "message.agent_progress",
                        recipient,
                        {
                            "run_id": run_id,
                            "evidence_sha256": digest(evidence),
                        },
                    )
            if reason == "run_owner_changed":
                # Lost claim: existing contract, no evidence write and no audit.
                raise BridgeError("receiver_claim_changed", "Receiver no longer owns this claim")
            if reason is not None:
                self._seal_failed(message_id, run_id, reason, seal, context)

        async def progress(evidence):
            sealed_write(evidence)

        async def running(evidence):
            sealed_write(evidence, start=True)
            if delivery_event is not None:
                delivery_event.set()

        def sealed_finish(evidence, **kwargs):
            # Visible completion keeps the original seal and checks it atomically.
            evidence = retain_context(evidence)
            with self.bridge.store.transaction():
                reason = self._seal_reason(message_id, recipient, run_id, seal, context)
                if reason is None:
                    self._finish(message_id, "completed", evidence, run_id=run_id, **kwargs)
            if reason is not None:
                self._seal_failed(message_id, run_id, reason, seal, context)

        if start_damage is not None:
            # Damaged stored evidence at process start: no input happened yet, so
            # terminal FAILED with claim_seal_broken; the raw stored value stays
            # verbatim inside last_observation with the mismatch marker. The
            # claim's verified seal is only the expected value, never a repair.
            with self.bridge.store.transaction():
                if owns_claim():
                    self._finish(
                        message_id,
                        "failed",
                        failure_evidence(start_damage),
                        "claim_seal_broken",
                        run_id=run_id,
                    )
            return

        try:
            validate_context()
            delivered = await call(
                "message_receive",
                {
                    "after": message["seq"] - 1,
                    "limit": 1,
                    "conversation_id": message["conversation_id"],
                },
            )
            if not delivered["messages"] or delivered["messages"][0]["id"] != message_id:
                raise BridgeError("receiver_delivery", "Message was consumed by another client")
            receipt = delivered["messages"][0]["receipt"]
            separate_managed = separate_managed_eligible(self.bridge.config, message["created"])
            visible = self.bridge.config.visible_handoffs.enabled and not separate_managed
            # Visible delivery and work without processed managed guidance keep
            # the exact current body. Only the pinned same-scope managed context
            # may frame prior original notes around it; never mutate the message.
            prompt = validate_context(receipt=receipt)
            if len(prompt) > 262144:
                raise BridgeError("payload_limit", "Receiver prompt exceeds the adapter limit")
            args = AgentInput(
                agent=recipient,
                prompt=prompt,
                cwd=receiver.cwd,
                timeout=receiver.timeout,
                wait_for_reply=request_reply,
            )
            pinned = self.bridge.store.db.execute(
                "SELECT execution_cwd FROM message_jobs WHERE message_id=?", (message_id,)
            ).fetchone()
            if pinned is None or pinned[0] != receiver.cwd:
                raise BridgeError("receiver_scope_changed", "Claimed receiver worktree changed")
            policy = self.bridge.security.principal(recipient, "message.read")
            # Last synchronous check before handing control to an adapter.
            validate_context(receipt=receipt)
            adapter_attempted = True
            if interim is not None:
                from kirabridge.interim_message import execute as steer
                from kirabridge.session_manager import SessionInput

                result = await steer(
                    self.bridge,
                    {"id": run_id, "principal": message["sender"]},
                    SessionInput(**interim.model_dump(), text=prompt, intent="interim"),
                    recipient,
                    delivery_binding,
                    running,
                    progress,
                )
            else:
                result = await self.bridge.agents.execute(
                    {
                        "id": run_id,
                        "principal": message["sender"] if visible else recipient,
                        "visible_message_id": message_id if visible else None,
                    },
                    args,
                    policy,
                    running,
                    progress,
                    separate_managed=separate_managed,
                    **(
                        {"visible_binding": delivery_binding}
                        if delivery_binding is not None
                        else {}
                    ),
                )
            if not result.get("success"):
                await progress(result.get("evidence", {}))
                raise BridgeError("agent_failed", "Receiving agent did not complete successfully")
            validate_context(receipt=receipt)
            if visible and result.get("scope") == "local_agent_turn":
                evidence = self._local_reply_evidence(message_id, run_id, result)
                sealed_finish(evidence)
                return
            if visible and result.get("scope") == "visible_input_delivery":
                # Native Paste+Return confirms delivery only. No protocol text
                # was injected, so do not invent a recipient ACK or final reply.
                evidence = {
                    **result.get("evidence", {}),
                    "run_id": run_id,
                    "session_scope": "existing_visible_terminal",
                    "completion_scope": "visible_input_delivery",
                    "agent_confirmed": False,
                    "agent_work_completion_verified": False,
                    "request_reply_satisfied": False,
                    "automatic_retry": False,
                }
                sealed_finish(evidence)
                return
            evidence = retain_context(
                {
                    **result.get("evidence", {}),
                    "run_id": run_id,
                    "session_scope": "existing_visible_terminal"
                    if visible
                    else "separate_managed_session",
                    "response_sha256": digest(result.get("text", "")),
                    "response_preview": result.get("text", "")[:320],
                }
            )
            if request_reply:
                text = result.get("text", "")
                if not isinstance(text, str) or not text.strip():
                    raise BridgeError("agent_no_text", "Receiving agent returned no answer")
                bounded = text.encode()[: limits.max_body_bytes].decode("utf-8", "ignore")
                response = MessageSend(
                    recipient=message["sender"],
                    conversation_id=message["conversation_id"],
                    idempotency_key="auto-" + digest(message_id),
                    body=bounded,
                    reply_to=message_id,
                    request_reply=False,
                    kind="result" if message["kind"] == "work" else "answer",
                    # The original sender's live client owns this return path.
                    # Starting another receiver here can consume its awaited answer.
                    dispatch=False,
                )
                if visible:
                    reply = await call(
                        "message_get", {"message_id": result["evidence"]["reply_id"]}
                    )
                    if reply["reply_to"] != message_id or reply["recipient"] != message["sender"]:
                        raise BridgeError("reply_conflict", "Visible agent reply does not match")
                else:
                    reply = await call("message_send", {"message": response.model_dump()})
                assert reply["sender"] == recipient
                reply_id = reply["id"]
                evidence["response_truncated"] = len(text.encode()) > limits.max_body_bytes
            # Reply delivery awaits a peer and may have lost the claim or gained
            # a hold. Revalidate after it, immediately before the final ACK.
            validate_context(receipt=receipt)
            ack = await call(
                "message_ack",
                {
                    "message_id": message_id,
                    "receipt": receipt,
                    # Atomic at ACK write: unchanged snapshot, running, same run_id, no hold.
                    "claim": self._claim_contract(message, run_id, context),
                },
            )
            assert ack["acknowledged"] is not None
            with self.bridge.store.transaction():
                validate_context(receipt=receipt, acknowledged=True)
                self._finish(message_id, "completed", evidence, reply_id=reply_id, run_id=run_id)
        except asyncio.CancelledError:
            with self.bridge.store.transaction():
                if not owns_claim():
                    raise  # Preserve an UNKNOWN or another owner's exact state/evidence.
                job = self.bridge.store.db.execute(
                    "SELECT message_id,evidence FROM message_jobs WHERE message_id=?",
                    (message_id,),
                ).fetchone()
                if (
                    delivery_event is not None
                    and delivery_event.is_set()
                    and self._reply_can_finish(job)
                ):
                    # Shutdown loses only the waiter, not the authenticated
                    # return path. Startup observes ACK/late reply without input.
                    raise
                self._finish(
                    message_id,
                    "unknown",
                    failure_evidence(),
                    "receiver_interrupted",
                    reply_id=reply_id,
                    run_id=run_id,
                )
            raise
        except Exception as exc:
            if not owns_claim():
                return  # Never finish/requeue or rewrite progress for a lost claim.
            integrity = getattr(exc, "seal_integrity_reason", None)
            if integrity is not None or delivery_event is not None:
                # Seal/context integrity damage: fail-closed UNKNOWN with a seal
                # failure code, the damaged stored evidence kept verbatim. Never
                # routed through DirectDelivery settlement (which replaces
                # evidence) nor requeued. Direct failures re-check the stored
                # seal fresh in the same transaction as their settlement.
                with self.bridge.store.transaction():
                    if not owns_claim():
                        return
                    if integrity is None:
                        integrity = stored_damage()
                    if integrity is None:
                        # Stored seal freshly verified intact in this transaction:
                        # settlement keeps it (and the pinned context) so a later
                        # reconciliation re-validates the same seal. Never a replay/ACK.
                        self.direct.fail(message_id, exc, retain=retain_context({}))
                        return  # One admission attempt; no pre-input requeue or replay.
                    code = (
                        exc.code
                        if isinstance(exc, BridgeError) and exc.code in self.SEAL_FAILURE_ERRORS
                        else "claim_seal_broken"
                    )
                    # Before any adapter attempt no input happened: terminal
                    # FAILED (never promotable); afterwards UNKNOWN, fenced.
                    self._finish(
                        message_id,
                        "unknown" if adapter_attempted else "failed",
                        failure_evidence(integrity),
                        code,
                        reply_id=reply_id,
                        run_id=run_id,
                    )
                return
            if (
                delivery_event is None
                and isinstance(exc, BridgeError)
                and self._queue_unsent(message_id, exc.code, run_id, "running")
            ):
                return  # Readiness changed before any input attempt.
            state = (
                "unknown"
                if isinstance(exc, UncertainExecution)
                or (isinstance(exc, BridgeError) and exc.code == "peer_unknown")
                or adapter_attempted
                else "failed"
            )
            # Preserve the last observed adapter/session evidence, never raw exception texts.
            with self.bridge.store.transaction():
                if owns_claim():
                    self._finish(
                        message_id,
                        state,
                        failure_evidence(),
                        exc.code if isinstance(exc, BridgeError) else "receiver_failed",
                        reply_id=reply_id,
                        run_id=run_id,
                    )
