"""Durable handoffs to exact existing visible terminals; never spawn a fallback."""

import asyncio
import hashlib
import re
import time

from kirabridge.bridge_core.models import BridgeError, UncertainExecution, canonical, digest
from kirabridge.cli_adapters import adapter_for
from kirabridge.message_manager import MessageSend
from kirabridge.session_manager import SessionInput
from kirabridge.visible_binding import (
    binding_still_present,
    catalog_can_replace,
    distinct_window_processes,
    load_refresh,
    replacement_binding,
    save_refresh,
)
from kirabridge.visible_readiness import assess, input_view

RETURN_OBSERVATION_TIMEOUT = 8.0


def _text_sha256(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class VisibleReadinessError(BridgeError):
    def __init__(self, observation):
        self.observation = observation
        code = {
            "working": "visible_target_working",
            "input_not_empty": "visible_input_not_empty",
            "scrolled": "visible_target_scrolled",
            "unknown": "visible_target_unknown",
            "target_changed": "visible_target_changed",
            "navigation_required": "visible_navigation_required",
        }[observation["state"]]
        message = {
            "working": (
                "Der Agent arbeitet noch; keine Eingabe und keine automatische Wiederholung."
            ),
            "input_not_empty": "Im Eingabefeld steht bereits Text; er wird nicht überschrieben.",
            "scrolled": "Die aktuelle Eingabeansicht ist nicht erreichbar; keine Eingabe.",
            "unknown": "Die aktuelle Eingabebereitschaft ist nicht eindeutig; keine Eingabe.",
            "target_changed": "Die zugeordnete CLI-Sitzung hat sich geändert; keine Eingabe.",
            "navigation_required": (
                "Bekannte CLI-Ansicht erfordert gebundene Navigation; keine Eingabe."
            ),
        }[observation["state"]]
        super().__init__(code, message)
        # Persist only internal classifier labels, never screen/protocol contents.
        readiness = {"state": observation["state"]}
        for key in ("target", "reason"):
            value = observation.get(key)
            if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,95}", value):
                readiness[key] = value
        self.provider_error = {"readiness": readiness}


class VisibleHandoffs:
    def activation_work_count(
        self, *, active_only=False, context=None, preserve_external_waits=False
    ):
        # Count evidence, without rewriting reservations during a read query.
        # ACK alone is not completion; transient native input always stays active.
        db = context.db if context is not None else self.store.db
        return db.execute(
            "SELECT count(*) FROM visible_handoffs h WHERE state IN "
            "('planned','inserting','inserted','submitting','return_sent','sent','confirmed') "
            "AND NOT (h.state IN ('sent','confirmed') AND EXISTS ("
            "SELECT 1 FROM messages original JOIN messages reply ON reply.reply_to=original.id "
            "WHERE original.id=h.message_id AND original.sender=h.principal "
            "AND original.recipient=h.target AND original.acknowledged IS NOT NULL "
            "AND reply.sender=h.target AND reply.recipient=h.principal "
            "AND reply.kind IN ('answer','result'))) "
            + ("AND h.state NOT IN ('sent','confirmed')" if preserve_external_waits else "")
        ).fetchone()[0]

    @staticmethod
    def input_view(target, text):
        """The last current input widget, never an older prompt in scrollback."""
        return input_view(target, text)

    @staticmethod
    def prompt(principal, target, identifier, body, message_id=None, conversation_id=None):
        """Only the authorized body is terminal input; routing stays internal."""
        return body

    @staticmethod
    def insertion_observed(target, text, prompt, identifier, *, before=None, **options):
        """Reuse the strict literal verifier with the real empty pre-paste frame."""
        from kirabridge.literal_session_input import insertion_observed

        if before is None:
            return None
        return (
            "literal_widget_exact_payload"
            if insertion_observed(target, text, prompt, before, **options)
            else None
        )

    @staticmethod
    def body_only_delivery(status):
        return any(
            event["state"] == "sent"
            and event["evidence"].get("prompt_format") == "body_only_v1"
            and event["evidence"].get("return_sent") is True
            and event["evidence"].get("input_field_cleared") is True
            for event in status["events"]
        )

    @classmethod
    def body_only_transport_delivery(cls, status):
        return cls.body_only_delivery(status) and any(
            event["state"] == "sent"
            and event["evidence"].get("prompt_format") == "body_only_v1"
            and event["evidence"].get("return_sent") is True
            and event["evidence"].get("input_field_cleared") is True
            and event["evidence"].get("wait_for_reply") is False
            for event in status["events"]
        )

    @classmethod
    def body_only_input_released(cls, status):
        evidence = status["evidence"]
        return (
            status["state"] == "unknown"
            and evidence.get("prompt_format") == "body_only_v1"
            and evidence.get("reason") == "body_only_target_ready"
            and evidence.get("input_reservation_released") is True
            and evidence.get("return_sent") is True
            and evidence.get("target_readiness") == "verified_ready_before_new_input"
            and cls.body_only_delivery(status)
        )

    async def verify_inserted_body(self, principal, target, binding, prompt, before, after, cwd):
        from kirabridge.literal_session_input import _task_cwd

        options = {}
        observed = self.insertion_observed(
            target, after["text"], prompt, None, before=before["text"]
        )
        if not observed and adapter_for(target).capabilities.softwrap:
            selection = self.sessions.current_selection()
            if selection and len(prompt) <= 1000:
                try:
                    columns = await self.sessions.terminal_app.input_columns(
                        binding.pane_id,
                        identity_guard=selection[2],
                        expected_screen=after["text"],
                    )
                except BridgeError:
                    columns = None
                if columns is not None:
                    options["columns"] = columns
                    observed = self.insertion_observed(
                        target, after["text"], prompt, None, before=before["text"], **options
                    )
            if not observed and cwd is not None:
                if await _task_cwd(self.sessions, binding) == cwd:
                    observed = self.insertion_observed(
                        target,
                        after["text"],
                        prompt,
                        None,
                        before=before["text"],
                        cwd=cwd,
                        **options,
                    )
        return observed

    def __init__(self, config, store, security, sessions, messages):
        self.config, self.store, self.security = config, store, security
        self.sessions, self.messages = sessions, messages
        from kirabridge.platform_adapters.codex_reply import CodexReplyObserver
        from kirabridge.platform_adapters.codex_state import CodexTurnState

        self.codex_state = CodexTurnState()
        self.codex_reply = CodexReplyObserver()
        load_refresh(config)
        with store.transaction():
            store.db.execute(
                "CREATE TABLE IF NOT EXISTS visible_handoffs ("
                "id TEXT PRIMARY KEY,principal TEXT NOT NULL,target TEXT NOT NULL,"
                "request_hash TEXT NOT NULL,binding TEXT NOT NULL,message_id TEXT NOT NULL,"
                "state TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,"
                "evidence TEXT NOT NULL)"
            )
            store.db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS visible_target_active "
                "ON visible_handoffs(target) "
                "WHERE state IN ('planned','inserting','inserted','submitting',"
                "'return_sent','sent','confirmed')"
            )
            store.db.execute(
                "CREATE TABLE IF NOT EXISTS visible_handoff_events ("
                "seq INTEGER PRIMARY KEY AUTOINCREMENT,"
                "id TEXT NOT NULL REFERENCES visible_handoffs(id),"
                "at REAL NOT NULL,state TEXT NOT NULL,evidence TEXT NOT NULL)"
            )

    def status(self, principal, identifier):
        self.security.principal(principal, "task.read")
        row = self.store.db.execute(
            "SELECT * FROM visible_handoffs WHERE id=? AND (principal=? OR target=?)",
            (identifier, principal, principal),
        ).fetchone()
        if not row:
            raise BridgeError("not_found", "Visible handoff not found")
        import json

        result = dict(row)
        result["binding"] = json.loads(result["binding"])
        result["evidence"] = json.loads(result["evidence"])
        result["events"] = [
            {**dict(e), "evidence": json.loads(e["evidence"])}
            for e in self.store.db.execute(
                "SELECT seq,at,state,evidence FROM visible_handoff_events WHERE id=? ORDER BY seq",
                (identifier,),
            )
        ]
        from kirabridge.visible_message_evidence import handoff_delivery_status

        result.update(handoff_delivery_status(self.store.db, identifier, result["state"]))
        return result

    def reconcile(self, principal, identifier):
        """Read authenticated evidence after an uncertain outcome; never send input."""
        status = self.status(principal, identifier)
        message = self.messages.get(principal, status["message_id"])
        idle_reply_pending = (
            status["state"] == "unknown"
            and status["evidence"].get("reason") == "target_idle_reply_unconfirmed"
        ) or self.body_only_input_released(status)
        if message["acknowledged"] and status["state"] not in {"completed", "interrupted"}:
            evidence = {
                "authenticated_principal": status["target"],
                "message_id": status["message_id"],
                "agent_confirmed": True,
                "reconciled_without_input": True,
            }
            retired = self.store.db.execute(
                "SELECT 1 FROM queue_holds WHERE queue_id='handoffs' AND item_id=?", (identifier,)
            ).fetchone()
            if status["state"] != "confirmed" and not idle_reply_pending and not retired:
                self.transition(identifier, "confirmed", evidence)
            reply = self.store.db.execute(
                "SELECT id FROM messages WHERE reply_to=? AND sender=? AND recipient=? "
                "AND kind IN ('answer','result') ORDER BY seq LIMIT 1",
                (status["message_id"], status["target"], status["principal"]),
            ).fetchone()
            if reply:
                self.transition(identifier, "completed", {**evidence, "reply_id": reply["id"]})
        return self.status(principal, identifier)

    def transition(self, identifier, state, evidence):
        with self.store.transaction():
            current = self.store.db.execute(
                "SELECT state FROM visible_handoffs WHERE id=?", (identifier,)
            ).fetchone()
            if current and current[0] in {"completed", "interrupted"}:
                return  # Completed evidence is terminal, including after a late callback failure.
            if (
                state
                in {
                    "planned",
                    "inserting",
                    "inserted",
                    "submitting",
                    "return_sent",
                    "sent",
                    "confirmed",
                }
                and self.store.db.execute(
                    "SELECT 1 FROM queue_holds WHERE queue_id='handoffs' AND item_id=?",
                    (identifier,),
                ).fetchone()
            ):
                evidence = {
                    **evidence,
                    "late_observation_state": state,
                    "delivery_retired": True,
                    "automatic_retry": False,
                }
                state = "unknown"  # Late receipts never reacquire the delivery reservation.
            now = time.time()
            self.store.db.execute(
                "UPDATE visible_handoffs SET state=?,updated=?,evidence=? WHERE id=?",
                (state, now, canonical(evidence), identifier),
            )
            self.store.db.execute(
                "INSERT INTO visible_handoff_events(id,at,state,evidence) VALUES(?,?,?,?)",
                (identifier, now, state, canonical(evidence)),
            )
            row = self.store.db.execute(
                "SELECT principal FROM visible_handoffs WHERE id=?", (identifier,)
            ).fetchone()
            self.store.audit(
                "control.handoff." + state, row[0], None, {"handoff_id": identifier, **evidence}
            )

    async def observe_readiness(self, principal, output):
        selected = await self.sessions.observed_selected(
            principal, output["pane_id"], output["expected_pid"]
        )
        try:
            target, binding = self.sessions.explicit_agent_binding(selected)
        except BridgeError as exc:
            return {
                "state": "unknown",
                "ready": False,
                "reason": exc.code,
                "observed_at": time.time(),
                "identity_scope": "OS process observation only",
            }
        if target is None:
            return None
        with self.sessions.observation_scope(principal, selected):
            return await self.binding_readiness(principal, target, binding, output)

    async def binding_readiness(self, principal, target, binding, output):
        selected = await self.sessions.observed_selected(
            principal, binding.pane_id, binding.expected_pid
        )
        if not self.sessions.binding_matches(selected, binding, target) or not any(
            p["pid"] == binding.agent_pid and p["name"] == target
            for p in selected.get("processes", [])
        ):
            return {
                "state": "target_changed",
                "ready": False,
                "reason": "bound_agent_pid_not_present",
                "target": target,
                "observed_at": time.time(),
            }
        protocol = None
        protocol = await adapter_for(target).protocol_state(binding, self.codex_state)
        return {
            **assess(target, output["text"], binding, protocol),
            "binding": {
                "pane_id": binding.pane_id,
                "expected_pid": binding.expected_pid,
                "agent_pid": binding.agent_pid,
            },
            "protocol": protocol,
            "observed_at": time.time(),
            "identity_scope": "OS process/window observation, not cryptographic identity",
            "scope": "current input and separately bound turn observation; no input proof",
        }

    @staticmethod
    def independent_unknown_paste(row, binding, task_id):
        """A different resource is not reconciliation or replay of the old handoff."""
        from kirabridge.bridge_core.config import VisibleTerminalBinding

        if row["state"] != "unknown" or row["id"] == task_id:
            return False
        try:
            original = VisibleTerminalBinding.model_validate_json(row["binding"])
            old, current = original.pane_id.split(":"), binding.pane_id.split(":")
            return (
                len(old) == len(current) == 3
                and old[0] == current[0] == "terminal"
                and old[1] != current[1]
                and old[2] != current[2]
                and original.expected_pid > 0
                and original.agent_pid > 0
                and {original.expected_pid, original.agent_pid}.isdisjoint(
                    {binding.expected_pid, binding.agent_pid}
                )
            )
        except (ValueError, TypeError, AttributeError):
            return False

    async def reconcile_target_reservations(
        self,
        principal,
        target,
        binding,
        *,
        busy_message="Existing handoff must finish or reconcile",
        explicit_paste_task_id=None,
        explicit_handoff_task_id=None,
        explicit_return_task_id=None,
        observed_sessions=None,
    ):
        """Keep the input lock until authenticated receipt and verified target readiness."""
        if explicit_paste_task_id is not None:
            selection = self.sessions.current_selection()
            if (
                not explicit_paste_task_id
                or not selection
                or selection[0] != target
                or selection[1] != binding
                or binding.expected_pid == binding.agent_pid
                or not isinstance(selection[2], dict)
                or not {binding.expected_pid, binding.agent_pid}.issubset(selection[2])
            ):
                raise BridgeError(
                    "visible_selection_required",
                    "Literal paste requires task-owned native identities",
                )
            await self.check_target(principal, target, binding, ready=True)
        if explicit_return_task_id is not None:
            # The key owner has already validated its scoped observation and
            # current Return frame. This is a resource check, never Paste-ready
            # permission for a menu or a nonempty composer.
            selection = self.sessions.current_selection()
            if (
                not explicit_return_task_id
                or not selection
                or selection[0] != target
                or selection[1] != binding
                or binding.expected_pid == binding.agent_pid
                or not isinstance(selection[2], dict)
                or not {binding.expected_pid, binding.agent_pid}.issubset(selection[2])
            ):
                raise BridgeError(
                    "visible_selection_required", "Return requires task-owned native identities"
                )
        active = self.store.db.execute(
            "SELECT id,principal,state,binding FROM visible_handoffs WHERE target=? "
            "AND NOT EXISTS (SELECT 1 FROM queue_holds h WHERE "
            "h.queue_id='handoffs' AND h.item_id=visible_handoffs.id) AND state IN "
            "('planned','inserting','inserted','submitting',"
            "'return_sent','sent','confirmed','unknown') "
            "ORDER BY updated,id",
            (target,),
        ).fetchall()
        for row in active:
            if explicit_return_task_id is not None and self.independent_unknown_paste(
                row, binding, explicit_return_task_id
            ):
                continue  # Another proven-independent resource retains its complete uncertainty.
            if explicit_paste_task_id is not None and self.independent_unknown_paste(
                row, binding, explicit_paste_task_id
            ):
                continue  # Original state, binding, events and receipt remain untouched.
            if explicit_handoff_task_id is not None and self.independent_unknown_paste(
                row, binding, explicit_handoff_task_id
            ):
                # An explicitly addressed, independently identified native pane
                # is a different resource, not a retry/rebind of the old input.
                # Default agent delivery must never borrow this exception.
                selection = self.sessions.current_selection()
                if (
                    not selection
                    or selection[0] != target
                    or selection[1] != binding
                    or binding.expected_pid == binding.agent_pid
                    or not isinstance(selection[2], dict)
                    or not {binding.expected_pid, binding.agent_pid}.issubset(selection[2])
                ):
                    raise BridgeError(
                        "visible_selection_required",
                        "Explicit handoff requires task-owned native identities",
                    )
                await self.check_target(principal, target, binding, ready=True)
                continue  # Old uncertainty and its own terminal reservation stay intact.
            if await self._foreign_dead_reservation(
                principal, target, row, binding, observed_sessions
            ):
                continue  # Dead pane stays recorded. It does not lock the replacement.
            status = self.reconcile(row["principal"], row["id"])
            if status["state"] in {"completed", "interrupted"}:
                continue
            if (
                self.body_only_delivery(status)
                and status["binding"] == binding.model_dump()
                and (
                    self.body_only_transport_delivery(status)
                    or self.body_only_input_released(status)
                )
                and (
                    status["state"] in {"sent", "confirmed"}
                    or (
                        status["state"] == "unknown"
                        and status["evidence"].get("reason") == "body_only_target_ready"
                    )
                )
            ):
                if self.body_only_input_released(status):
                    # The old input slot was already released. The current
                    # operation owns its fresh input/menu/key checks; an old
                    # empty-composer requirement must not override those guards.
                    continue
                # Delivery does not claim an answer. A later *fresh* empty/idle
                # observation of this same exact target releases its input slot.
                await self.check_target(principal, target, binding, ready=True)
                if status["evidence"].get("reason") != "body_only_target_ready":
                    self.transition(
                        row["id"],
                        "unknown",
                        {
                            **status["evidence"],
                            "reason": "body_only_target_ready",
                            "input_reservation_released": True,
                            "prompt_format": "body_only_v1",
                            "wait_for_reply": False,
                            "return_sent": True,
                            "previous_state": status["state"],
                            "agent_confirmed": False,
                            "automatic_retry": False,
                            "target_readiness": "verified_ready_before_new_input",
                        },
                    )
                continue
            message = self.messages.get(row["principal"], status["message_id"])
            reply = self.store.db.execute(
                "SELECT 1 FROM messages WHERE reply_to=? AND sender=? AND recipient=? "
                "AND kind IN ('answer','result') LIMIT 1",
                (status["message_id"], target, row["principal"]),
            ).fetchone()
            if (
                adapter_for(target).has_bound_protocol(binding)
                and status["state"] in {"sent", "confirmed", "unknown"}
                and message["acknowledged"]
                and not reply
            ):
                # The accepted turn has finished, but its answer may still be missing.
                # Keep that uncertainty on the original handoff and never replay it;
                # release only its terminal lock after a fresh positive idle check.
                await self.check_target(principal, target, binding, ready=True)
                evidence = {
                    **status["evidence"],
                    "reason": "target_idle_reply_unconfirmed",
                    "previous_state": status["state"],
                    "agent_acknowledged": True,
                    "terminal_input_attempted": True,
                    "target_readiness": "verified_ready_before_new_input",
                    "automatic_retry": False,
                }
                if (
                    status["state"] != "unknown"
                    or status["evidence"].get("reason") != "target_idle_reply_unconfirmed"
                ):
                    self.transition(row["id"], "unknown", evidence)
                continue

            if self._pre_paste_refusal(status):
                await self.check_target(principal, target, binding, ready=True)
                if status["evidence"].get("reason") != "pre_paste_refusal_lock_released":
                    self.transition(
                        row["id"],
                        "unknown",
                        {
                            **status["evidence"],
                            "reason": "pre_paste_refusal_lock_released",
                            "previous_reason": status["evidence"].get("reason"),
                            "terminal_input_attempted": False,
                            "return_sent": False,
                            "automatic_retry": False,
                            "target_readiness": "verified_ready_before_new_input",
                        },
                    )
                continue  # The old message stays unknown and is not sent again.
            error = BridgeError("visible_target_busy", busy_message)
            last = status["events"][-1] if status["events"] else None
            error.observation = {
                "state": "reserved",
                "handoff_id": row["id"],
                "handoff_state": status["state"],
                "message_id": message["id"],
                "acknowledged": message["acknowledged"],
                "last_event": {key: last[key] for key in ("state", "at")} if last else None,
                "next_step": "Empfang und Antwort dieses Auftrags abgleichen; nicht neu senden",
            }
            raise error

    @staticmethod
    def _pre_paste_refusal(status):
        """A screen mismatch before AXPress sent no paste and no Return."""
        if status["state"] != "unknown":
            return False
        if status["evidence"].get("reason") not in {
            "visible_input_changed",
            "pre_paste_refusal_lock_released",
        }:
            return False
        return not any(
            event["state"] in {"submitting", "return_sent", "sent", "confirmed"}
            for event in status["events"]
        )

    async def dispatch_ready(self, principal, target):
        """Observe before claiming a message; never paste or settle unknown input."""
        binding = self.config.visible_handoffs.bindings.get(target)
        if binding is None:
            raise BridgeError("visible_target_missing", "No assigned existing visible terminal")
        binding, observed = await self.refreshed_binding(principal, target, binding)
        await self.reconcile_target_reservations(
            principal, target, binding, observed_sessions=observed
        )
        await self.check_target(principal, target, binding, ready=True)

    async def refreshed_binding(self, principal, target, binding):
        """Use the saved binding while its process lives. Replace only a dead unique agent.

        The returned session list is the catalog snapshot that proved the replacement.
        Callers may use it to ignore reservations on that dead pane. A matched binding
        returns no snapshot, so an unrelated reservation keeps its existing lock.
        """
        try:
            selected = await self.sessions.selected(
                principal, binding.pane_id, binding.expected_pid
            )
        except BridgeError:
            selected = None
        if selected is not None and self.sessions.binding_matches(selected, binding, target):
            return binding, None
        try:
            catalog = await self.sessions.catalog(principal)
        except BridgeError:
            return binding, None
        if not catalog_can_replace(catalog):
            return binding, None
        sessions = catalog.get("sessions") or []
        try:
            await self.sessions.prove_original_target_gone(principal, binding.model_dump())
        except BridgeError:
            return binding, None
        updated = replacement_binding(target, binding, sessions)
        if updated is None:
            # The catalog is complete and the configured pane is proven gone;
            # retain that snapshot even without a replacement so an orphaned
            # reservation on this exact binding can be released.
            return binding, sessions
        self.config.visible_handoffs.bindings[target] = updated
        save_refresh(self.config, target, binding, updated)
        self.store.audit(
            "visible_binding_refreshed",
            principal,
            None,
            {
                "target": target,
                "previous_pane_id": binding.pane_id,
                "pane_id": updated.pane_id,
                "expected_pid": updated.expected_pid,
                "agent_pid": updated.agent_pid,
                "automatic_retry": False,
            },
        )
        return updated, sessions

    async def _foreign_dead_reservation(self, principal, target, row, binding, observed_sessions):
        from kirabridge.bridge_core.config import VisibleTerminalBinding

        try:
            original = VisibleTerminalBinding.model_validate_json(row["binding"])
        except (ValueError, TypeError):
            return False
        same_binding = (
            original.pane_id == binding.pane_id
            and original.expected_pid == binding.expected_pid
            and original.agent_pid == binding.agent_pid
        )
        if not same_binding and not distinct_window_processes(original, binding):
            return False
        if same_binding and observed_sessions is None:
            # An own-binding absence proof needs a complete fresh catalog first;
            # an incomplete or unavailable snapshot must not release it.
            return False
        if observed_sessions is not None and binding_still_present(original, observed_sessions):
            return False
        # A tty can be reused as soon as its old window closes. That name is not
        # the session identity. Only a full native window inventory plus absence
        # of both original PIDs may release the lock, never a missing catalog row.
        # The exact configured binding may be that vanished window too; an
        # existing window or either original PID keeps its lock.
        try:
            await self.sessions.prove_original_target_gone(principal, original.model_dump())
        except BridgeError:
            return False
        return True

    async def _park_proven_dead(self, principal, target, binding, observed_sessions):
        """Move a proven-dead active reservation out of the unique target index.

        The row stays unknown, is not completed, and is not sent again.
        """
        import json

        rows = self.store.db.execute(
            "SELECT id,binding,state,evidence FROM visible_handoffs WHERE target=? AND state IN "
            "('planned','inserting','inserted','submitting','return_sent','sent','confirmed')",
            (target,),
        ).fetchall()
        for row in rows:
            if not await self._foreign_dead_reservation(
                principal, target, row, binding, observed_sessions
            ):
                continue
            try:
                previous = json.loads(row["evidence"])
            except (TypeError, ValueError):
                previous = {}
            if not isinstance(previous, dict):
                previous = {}
            self.transition(
                row["id"],
                "unknown",
                {
                    **previous,
                    "reason": "binding_proven_dead",
                    "previous_state": row["state"],
                    "automatic_retry": False,
                    "index_released": True,
                },
            )

    async def check_target(self, principal, target, binding, *, ready=False):
        row = await self.sessions.selected(principal, binding.pane_id, binding.expected_pid)
        with self.sessions.observation_scope(principal, row):
            matches = [
                p
                for p in row.get("processes", [])
                if p["pid"] == binding.agent_pid and p["name"] == target
            ]
            if len(matches) != 1:
                raise BridgeError(
                    "visible_target_changed", "Bound CLI process is not in this exact terminal"
                )
            output = await self.sessions.read(principal, binding.pane_id, binding.expected_pid)
            if ready:
                observation = await self.binding_readiness(
                    principal,
                    target,
                    binding,
                    {**output, "pane_id": binding.pane_id, "expected_pid": binding.expected_pid},
                )
                if not observation["ready"]:
                    # Store raw contents only in the bounded capture repository.
                    observed = self.sessions.audit.observe_terminal(
                        principal,
                        {
                            **output,
                            "pane_id": binding.pane_id,
                            "expected_pid": binding.expected_pid,
                        },
                    )
                    raise VisibleReadinessError(
                        {
                            **observation,
                            "observed_at": time.time(),
                            "output_ref": observed.get("output_ref"),
                        }
                    )
            return output

    async def submit_inserted(
        self,
        identifier,
        principal,
        target,
        binding,
        running,
        *,
        expected_input_view=None,
        wait_for_reply=True,
    ):
        """Exactly one separately recorded Return; never call after an uncertain submit."""
        self.transition(identifier, "submitting", {"agent_confirmed": False})
        view = await self.check_target(principal, target, binding)
        if (
            expected_input_view is not None
            and self.input_view(target, view["text"]) != expected_input_view
        ):
            raise UncertainExecution(
                "visible_insert_unknown", "Inserted input changed; no Return sent"
            )
        if expected_input_view is None:
            raise UncertainExecution(
                "visible_insert_unknown", "No previously verified input frame; no Return sent"
            )
        await self.sessions.press_return(
            principal, binding.pane_id, binding.expected_pid, expected_screen=view["text"]
        )
        self.transition(identifier, "return_sent", {"return_sent": True, "agent_confirmed": False})
        # Return transport is separate from observable CLI acceptance.
        deadline = time.monotonic() + RETURN_OBSERVATION_TIMEOUT
        while time.monotonic() < deadline:
            view = await self.check_target(principal, target, binding)
            if re.search(binding.ready_pattern, self.input_view(target, view["text"])):
                break
            await asyncio.sleep(0.1)
        else:
            raise UncertainExecution(
                "visible_submit_unknown",
                "Input field did not clear after Return; do not repeat",
            )
        self.transition(
            identifier,
            "sent",
            {
                "return_sent": True,
                "input_field_cleared": True,
                "agent_confirmed": False,
                "request_reply_satisfied": False,
                "prompt_format": "body_only_v1",
                "wait_for_reply": wait_for_reply,
            },
        )
        await running({"handoff_id": identifier, "state": "sent", "agent_confirmed": False})

    async def continue_unsubmitted(self, principal, identifier, running):
        from kirabridge.bridge_core.config import VisibleTerminalBinding

        status = self.status(principal, identifier)
        binding = VisibleTerminalBinding.model_validate(status["binding"])
        async with self.sessions.agent_selection(principal, status["target"], binding):
            return await self._continue_unsubmitted(principal, identifier, running)

    async def _continue_unsubmitted(self, principal, identifier, running):
        """Explicit local reconciliation, no new paste and no repeat of a prior Return."""
        from kirabridge.bridge_core.config import VisibleTerminalBinding

        status = self.status(principal, identifier)
        message = self.messages.get(principal, status["message_id"])
        if message["acknowledged"]:
            return self.reconcile(principal, identifier)
        attempted_return = any(
            e["state"] in {"submitting", "return_sent", "sent", "confirmed"}
            for e in status["events"]
        )
        if (
            status["state"] != "unknown"
            or status["evidence"].get("reason") != "visible_insert_unknown"
            or attempted_return
        ):
            raise BridgeError(
                "return_reconciliation_required", "A Return may already have been sent"
            )
        binding = VisibleTerminalBinding.model_validate(status["binding"])
        if self.config.visible_handoffs.bindings.get(status["target"]) != binding:
            raise BridgeError("handoff_conflict", "Original binding changed")
        view = await self.check_target(principal, status["target"], binding)
        verified = next(
            (
                event["evidence"]
                for event in reversed(status["events"])
                if event["state"] == "inserted"
                and event["evidence"].get("prompt_format") == "body_only_v1"
                and event["evidence"].get("prompt_observed") is True
            ),
            None,
        )
        current_view = self.input_view(status["target"], view["text"])
        if (
            verified is None
            or verified.get("expected_payload_sha256") != _text_sha256(message["body"])
            or verified.get("verified_input_view_sha256") != _text_sha256(current_view)
        ):
            raise BridgeError(
                "return_reconciliation_required",
                "Original literal input was not verified; inspect it and use an explicit Return",
            )
        wait_for_reply = verified.get("wait_for_reply", True)
        if type(wait_for_reply) is not bool or wait_for_reply != bool(message["request_reply"]):
            raise BridgeError(
                "return_reconciliation_required", "Original reply preference is not consistent"
            )
        observed = "same_previously_verified_literal_widget"
        local_reply = verified.get("local_reply_observer")
        if isinstance(local_reply, dict) and local_reply.get("state") == "ready":
            local_reply = await self.codex_reply.before_submit(
                local_reply["cursor"], binding, body=message["body"]
            )
        self.transition(
            identifier,
            "inserted",
            {
                "insertion_representation": observed,
                "reconciled_without_paste": True,
                "return_sent": False,
                "agent_confirmed": False,
                **({"local_reply_observer": local_reply} if isinstance(local_reply, dict) else {}),
            },
        )
        try:
            await self.submit_inserted(
                identifier,
                principal,
                status["target"],
                binding,
                running,
                expected_input_view=current_view,
                wait_for_reply=wait_for_reply,
            )
        except BaseException as exc:
            self.transition(
                identifier,
                "unknown",
                {"reason": getattr(exc, "code", "interrupted"), "automatic_retry": False},
            )
            raise
        return self.status(principal, identifier)

    async def execute(self, task, args, running, progress, *, binding_override=None):
        started = time.monotonic()
        error = None
        cause_error = None
        try:
            return await self._execute_selected(
                task, args, running, progress, binding_override=binding_override
            )
        except BaseException as exc:
            code = getattr(exc, "code", None)
            error = (
                code
                if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code)
                else "cancelled"
                if isinstance(exc, asyncio.CancelledError)
                else "timeout"
                if isinstance(exc, TimeoutError)
                else "unexpected_error"
            )
            cause = exc.__cause__
            cause_code = getattr(cause, "code", None)
            if isinstance(cause_code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", cause_code):
                cause_error = cause_code
            elif isinstance(cause, TimeoutError):
                cause_error = "timeout"
            raise
        finally:
            # One bounded diagnostic per invocation. No screen, prompt, payload,
            # exception message or credentials enter this diagnostic event.
            row = self.store.db.execute(
                "SELECT state FROM visible_handoffs WHERE id=?", (task["id"],)
            ).fetchone()
            last = self.store.db.execute(
                "SELECT state FROM visible_handoff_events WHERE id=? "
                "AND state NOT IN ('unknown','interrupted') ORDER BY seq DESC LIMIT 1",
                (task["id"],),
            ).fetchone()
            self.store.audit(
                "control.handoff.diagnostic",
                task["principal"],
                None,
                {
                    "handoff_id": task["id"],
                    "at": time.time(),
                    "duration_ms": round((time.monotonic() - started) * 1000, 3),
                    "state": row[0] if row else "not_started",
                    "phase": last[0] if last else "preflight",
                    "error": error,
                    "cause_error": cause_error,
                    "automatic_retry": False,
                },
            )

    async def _execute_selected(self, task, args, running, progress, *, binding_override=None):
        policy = self.security.principal(task["principal"], "agent.execute")
        if args.agent not in policy.agents:
            raise BridgeError("agent_denied", "Selected agent is not granted to this identity")
        for capability in ("agent.execute", "session.inspect", "session.input", "terminal.execute"):
            self.security.principal(task["principal"], capability)
        binding = binding_override or self.config.visible_handoffs.bindings.get(args.agent)
        if binding is None:
            raise BridgeError(
                "visible_target_missing", "Bind an exact existing visible CLI terminal"
            )
        observed = None
        if binding_override is None:
            stored = self.store.db.execute(
                "SELECT binding FROM visible_handoffs WHERE id=?", (task["id"],)
            ).fetchone()
            if stored is None:
                binding, observed = await self.refreshed_binding(
                    task["principal"], args.agent, binding
                )
            else:
                from kirabridge.bridge_core.config import VisibleTerminalBinding

                binding = VisibleTerminalBinding.model_validate_json(stored["binding"])
        async with self.sessions.agent_selection(task["principal"], args.agent, binding):
            return await self._execute(
                task,
                args,
                running,
                progress,
                binding_override=binding,
                observed_sessions=observed,
                explicit_selection=binding_override is not None,
            )

    async def _execute(
        self,
        task,
        args,
        running,
        progress,
        *,
        binding_override=None,
        observed_sessions=None,
        explicit_selection=False,
    ):
        principal, target, identifier = task["principal"], args.agent, task["id"]
        local_reply = {"state": "unavailable", "reason": "independent_thread_binding_unavailable"}
        # All senders use this path. Eve is grok_app; only target selects the CLI window.
        for capability in ("agent.execute", "session.inspect", "session.input", "terminal.execute"):
            self.security.principal(principal, capability)
        binding = binding_override or self.config.visible_handoffs.bindings.get(target)
        if binding is None:
            raise BridgeError(
                "visible_target_missing",
                "Bind an exact existing visible CLI terminal; no background fallback",
            )
        reply_binding = None
        if principal in {"codex", "grok"}:
            reply_binding = self.config.visible_handoffs.bindings.get(principal)
            if reply_binding is None:
                raise BridgeError(
                    "visible_reply_target_missing",
                    "The requesting CLI needs its assigned visible window",
                )
            await self.check_target(principal, principal, reply_binding)
        hash_args = args.model_dump()
        if args.wait_for_reply:
            # Preserve historical handoff hashes for the unchanged reply-wait
            # default. Explicit transport-only mode remains part of identity.
            hash_args.pop("wait_for_reply")
        hashed = digest({"principal": principal, "args": hash_args})
        existing = self.store.db.execute(
            "SELECT * FROM visible_handoffs WHERE id=?", (identifier,)
        ).fetchone()
        if existing:
            if existing["request_hash"] != hashed or existing["binding"] != canonical(
                binding.model_dump()
            ):
                raise BridgeError(
                    "handoff_conflict", "Original visible handoff and target are immutable"
                )
            reconciled = self.reconcile(principal, identifier)
            local_reply = next(
                (
                    event["evidence"]["local_reply_observer"]
                    for event in reversed(reconciled["events"])
                    if event["state"] == "inserted"
                    and isinstance(event["evidence"].get("local_reply_observer"), dict)
                ),
                local_reply,
            )
            existing = {**dict(existing), "state": reconciled["state"]}
            if existing["state"] not in {"sent", "confirmed", "completed"} and not (
                self.body_only_delivery(reconciled)
                and reconciled["evidence"].get("reason") == "body_only_target_ready"
            ):
                raise UncertainExecution(
                    "visible_handoff_unknown",
                    "Prior input must be reconciled; never repeat automatically",
                )
            message_id = existing["message_id"]
        else:
            before = await self.check_target(principal, target, binding, ready=True)
            await self.reconcile_target_reservations(
                principal,
                target,
                binding,
                busy_message="Another handoff owns this terminal; reconcile it first",
                explicit_handoff_task_id=identifier if explicit_selection else None,
                observed_sessions=observed_sessions,
            )
            addressed = task.get("visible_message_id")
            if addressed:
                original = self.messages.get(principal, addressed)
                if original["sender"] != principal or original["recipient"] != target:
                    raise BridgeError(
                        "handoff_conflict", "Original addressed message does not match"
                    )
                if original["body"] != args.prompt:
                    raise BridgeError(
                        "handoff_conflict", "Visible input must match the original addressed body"
                    )
                message_id, conversation = addressed, original["conversation_id"]
            else:
                message_id = conversation = "visible-" + digest(identifier)[:48]
            prompt = self.prompt(
                principal, target, identifier, args.prompt, message_id, conversation
            )
            if len(prompt) > 16384 or "\x00" in prompt:
                raise BridgeError("payload_limit", "Visible prompt exceeds terminal input limit")
            await adapter_for(target).preflight_input(self.sessions, binding, prompt, before)
            # The partial unique index still owns sent/confirmed rows. Parking a
            # proven-dead row as unknown releases that slot and does not resend it.
            await self._park_proven_dead(principal, target, binding, observed_sessions)
            held = self.store.db.execute(
                "SELECT id,binding,state FROM visible_handoffs WHERE target=? AND state IN "
                "('planned','inserting','inserted','submitting','return_sent',"
                "'sent','confirmed')",
                (target,),
            ).fetchall()
            released = {
                row["id"]
                for row in held
                if await self._foreign_dead_reservation(
                    principal, target, row, binding, observed_sessions
                )
            }
            with self.store.transaction():
                self.store.assert_accepting(continuation_id=identifier, owned_execution=True)
                active = self.store.db.execute(
                    "SELECT id FROM visible_handoffs WHERE target=? AND state IN "
                    "('planned','inserting','inserted','submitting','return_sent',"
                    "'sent','confirmed')",
                    (target,),
                ).fetchall()
                if any(row["id"] not in released for row in active):
                    raise BridgeError(
                        "visible_target_busy",
                        "Another handoff owns this terminal; reconcile it first",
                    )
                if not addressed:
                    self.messages._send(
                        principal,
                        MessageSend(
                            message_id=message_id,
                            recipient=target,
                            conversation_id=conversation,
                            idempotency_key=message_id,
                            kind="work",
                            body=args.prompt,
                            request_reply=args.wait_for_reply,
                            dispatch=False,
                        ),
                        visible_internal=True,
                    )
                now = time.time()
                self.store.db.execute(
                    "INSERT INTO visible_handoffs VALUES(?,?,?,?,?,?,'planned',?,?,?)",
                    (
                        identifier,
                        principal,
                        target,
                        hashed,
                        canonical(binding.model_dump()),
                        message_id,
                        now,
                        now,
                        canonical({"agent_confirmed": False}),
                    ),
                )
            input_attempted = False

            async def before_paste():
                nonlocal input_attempted, local_reply
                if adapter_for(target).capabilities.bound_reply and args.wait_for_reply:
                    selection = self.sessions.current_selection()
                    expected_identity = (
                        selection[2].get(binding.agent_pid)
                        if selection
                        and selection[0] == target
                        and selection[1] == binding
                        and isinstance(selection[2], dict)
                        else None
                    )
                    local_reply = await self.codex_reply.prepare(
                        binding,
                        process_identity=self.sessions.terminal_app.process_identity,
                        expected_identity=expected_identity,
                        body=prompt,
                        cwd=args.cwd,
                    )
                # SessionManager invokes this only after its final native
                # identity/readiness checks, immediately before transport.
                # Refusal before this boundary sent no input, while any later
                # failure stays uncertain and must never be automatically retried.
                input_attempted = True
                self.transition(
                    identifier,
                    "inserting",
                    {
                        "agent_confirmed": False,
                        "prompt_format": "body_only_v1",
                        "wait_for_reply": args.wait_for_reply,
                        "empty_input_observed": True,
                        "terminal_input_attempted": True,
                        "local_reply_observer": local_reply,
                    },
                )
                await running(
                    {
                        "handoff_id": identifier,
                        "state": "inserting",
                        "terminal_input_attempted": True,
                        "return_sent": False,
                        "agent_confirmed": False,
                        "automatic_retry": False,
                    }
                )

            try:
                before = await self.check_target(principal, target, binding, ready=True)
                from kirabridge.literal_session_input import _needs_cwd_proof, _task_cwd

                before_cwd = (
                    await _task_cwd(self.sessions, binding)
                    if adapter_for(target).capabilities.cwd_proof
                    and _needs_cwd_proof(before["text"])
                    else None
                )
                await self.sessions.insert(
                    principal,
                    SessionInput(
                        pane_id=binding.pane_id,
                        expected_pid=binding.expected_pid,
                        text=prompt,
                        submit=False,
                    ),
                    before_transport=before_paste,
                )
                inserted = await self.check_target(principal, target, binding)
                observed = await self.verify_inserted_body(
                    principal, target, binding, prompt, before, inserted, before_cwd
                )
                if not observed:
                    raise UncertainExecution(
                        "visible_insert_unknown", "Prompt insertion not observed; no Return sent"
                    )
                if local_reply.get("state") == "ready":
                    local_reply = await self.codex_reply.before_submit(
                        local_reply["cursor"], binding, body=prompt
                    )
                self.transition(
                    identifier,
                    "inserted",
                    {
                        "prompt_observed": True,
                        "prompt_format": "body_only_v1",
                        "wait_for_reply": args.wait_for_reply,
                        "expected_payload_sha256": _text_sha256(prompt),
                        "verified_input_view_sha256": _text_sha256(
                            self.input_view(target, inserted["text"])
                        ),
                        "insertion_representation": observed,
                        "return_sent": False,
                        "agent_confirmed": False,
                        "local_reply_observer": local_reply,
                    },
                )
                await progress(
                    {"handoff_id": identifier, "state": "inserted", "agent_confirmed": False}
                )
                await self.submit_inserted(
                    identifier,
                    principal,
                    target,
                    binding,
                    progress,
                    expected_input_view=self.input_view(target, inserted["text"]),
                    wait_for_reply=args.wait_for_reply,
                )
            except BaseException as exc:
                if not input_attempted and not isinstance(exc, UncertainExecution):
                    self.transition(
                        identifier,
                        "interrupted",
                        {
                            "reason": getattr(exc, "code", "preinput_error"),
                            "preinput_abort": True,
                            "terminal_input_attempted": False,
                            "automatic_retry": False,
                        },
                    )
                    raise  # Only a pre-input readiness error may be deferred by the receiver.
                self.transition(
                    identifier,
                    "unknown",
                    {
                        "reason": getattr(exc, "code", "interrupted"),
                        "agent_confirmed": False,
                        "automatic_retry": False,
                    },
                )
                raise UncertainExecution(
                    "visible_handoff_unknown",
                    "Input outcome requires reconciliation; no automatic resend",
                ) from exc
        current = self.reconcile(principal, identifier)
        cached_local = current["evidence"].get("local_reply_result")
        original = self.messages.get(principal, message_id)
        replied = self.store.db.execute(
            "SELECT 1 FROM messages WHERE reply_to=? AND sender=? AND recipient=? "
            "AND kind IN ('answer','result') LIMIT 1",
            (message_id, target, principal),
        ).fetchone()
        if (
            current["state"] == "completed"
            and isinstance(cached_local, dict)
            and not (original["acknowledged"] and replied)
        ):
            return cached_local  # Same immutable task/body/binding; never another input.
        if (
            not args.wait_for_reply
            and self.body_only_delivery(current)
            and not (original["acknowledged"] and replied)
        ):
            # This is a delivery receipt, never a fabricated agent answer. Real
            # later mailbox ACK/replies retain their own reconciliation path.
            return {
                "success": True,
                "submitted": True,
                "return_sent": True,
                "agent_confirmed": False,
                "request_reply_satisfied": False,
                "message_id": message_id,
                "scope": "visible_input_delivery",
                "work_completion_verified": False,
                "project_completion_verified": False,
                "evidence": {
                    "handoff_id": identifier,
                    "message_id": message_id,
                    "route": "existing_visible_terminal",
                    "prompt_format": "body_only_v1",
                    "agent_confirmed": False,
                    "request_reply_satisfied": False,
                    "return_sent": True,
                    "input_field_cleared": True,
                    "binding": binding.model_dump(),
                    "automatic_retry": False,
                    "expected_payload_sha256": _text_sha256(args.prompt),
                },
            }
        try:
            async with asyncio.timeout(args.timeout):
                confirmed = False
                while True:
                    message = self.messages.get(principal, message_id)
                    current = self.reconcile(principal, identifier)
                    if current["state"] == "interrupted":
                        raise UncertainExecution(
                            "agent_turn_interrupted", "Interrupted turn must not be repeated"
                        )
                    if (
                        message["acknowledged"]
                        and not confirmed
                        and current["state"] != "completed"
                        and not self.body_only_input_released(current)
                    ):
                        confirmed = True
                        self.transition(
                            identifier,
                            "confirmed",
                            {
                                "authenticated_principal": target,
                                "message_id": message_id,
                                "agent_confirmed": True,
                            },
                        )
                        await progress(
                            {
                                "handoff_id": identifier,
                                "state": "confirmed",
                                "agent_confirmed": True,
                            }
                        )
                    reply = self.store.db.execute(
                        "SELECT id,body FROM messages WHERE reply_to=? "
                        "AND sender=? AND recipient=? "
                        "AND kind IN ('answer','result') ORDER BY seq LIMIT 1",
                        (message_id, target, principal),
                    ).fetchone()
                    if message["acknowledged"] and reply:
                        # An answer returns through the active requesting MCP call;
                        # revalidate its assigned original window as well as the worker's.
                        await self.check_target(principal, target, binding)
                        if reply_binding:
                            await self.check_target(principal, principal, reply_binding)
                        evidence = {
                            "handoff_id": identifier,
                            "route": "existing_visible_terminal",
                            "agent_confirmed": True,
                            "reply_id": reply["id"],
                            "binding": binding.model_dump(),
                            "identity_scope": "authenticated_bridge_principal",
                            "reply_route": "active_request_result_and_durable_inbox",
                            "reply_target_binding": reply_binding.model_dump()
                            if reply_binding
                            else None,
                            "reply_visible_rendering": "client_not_attested",
                        }
                        self.transition(identifier, "completed", evidence)
                        return {
                            "success": True,
                            "text": reply["body"],
                            "evidence": evidence,
                            "scope": "agent_turn",
                            "project_completion_verified": False,
                        }
                    if local_reply.get("state") == "ready":
                        observed = await self.codex_reply.observe(
                            local_reply["cursor"],
                            binding,
                            body=args.prompt,
                            process_identity=self.sessions.terminal_app.process_identity,
                        )
                        if observed["state"] == "completed":
                            await self.check_target(principal, target, binding)
                            if reply_binding:
                                await self.check_target(principal, principal, reply_binding)
                            # A genuine mailbox return can arrive while the local
                            # descriptor is checked. It retains its existing priority.
                            original = self.messages.get(principal, message_id)
                            authenticated_reply = self.store.db.execute(
                                "SELECT 1 FROM messages WHERE reply_to=? AND sender=? "
                                "AND recipient=? AND kind IN ('answer','result') LIMIT 1",
                                (message_id, target, principal),
                            ).fetchone()
                            if original["acknowledged"] and authenticated_reply:
                                continue
                            evidence = {
                                **observed["evidence"],
                                "handoff_id": identifier,
                                "message_id": message_id,
                                "route": "existing_visible_terminal",
                                "reply_route": "active_request_and_durable_processing_result",
                                "reply_visible_rendering": "client_not_attested",
                                "completion_scope": "local_agent_turn",
                                "agent_confirmed": False,
                                "request_reply_satisfied": True,
                                "automatic_retry": False,
                            }
                            result = {
                                "success": True,
                                "text": observed["text"],
                                "scope": "local_agent_turn",
                                "reply_source": "bound_local_codex_rollout",
                                "agent_confirmed": False,
                                "request_reply_satisfied": True,
                                "work_completion_verified": False,
                                "project_completion_verified": False,
                                "evidence": evidence,
                            }
                            self.transition(
                                identifier,
                                "completed",
                                {**evidence, "local_reply_result": result},
                            )
                            return result
                        if observed["state"] == "unavailable":
                            local_reply = observed
                            await progress(
                                {
                                    "handoff_id": identifier,
                                    "local_reply_observer": observed,
                                    "agent_confirmed": False,
                                }
                            )
                    await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            # Only the reply observer is gone: paste and Return were already
            # durably recorded above. Preserve them for ACK/late-reply recovery.
            # Cancellation during input is still handled as uncertain input.
            raise
        except BaseException as exc:
            current = self.status(principal, identifier)
            evidence = (
                {
                    **current["evidence"],
                    "reply_observer_error": "reply_unconfirmed",
                    "automatic_retry": False,
                }
                if self.body_only_input_released(current)
                else {
                    "reason": "reply_unconfirmed",
                    "automatic_retry": False,
                    "local_reply_observer": {
                        key: local_reply[key] for key in ("state", "reason") if key in local_reply
                    },
                }
            )
            self.transition(identifier, "unknown", evidence)
            raise UncertainExecution(
                "visible_reply_unknown", "No confirmed final reply; do not resubmit"
            ) from exc
