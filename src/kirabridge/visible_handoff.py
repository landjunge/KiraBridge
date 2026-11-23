"""Durable handoffs to exact existing visible terminals; never spawn a fallback."""

import asyncio
import hashlib
import re
import time

from kirabridge.bridge_core.models import BridgeError, UncertainExecution, canonical, digest
from kirabridge.cli_adapters import adapter_for
from kirabridge.message_manager import MessageSend
from kirabridge.process_lifecycle import fresh_generations, same_generation, valid_generation
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
# Two sweeper rounds. An older "available" observation is reported as aged.
PRESENCE_FRESH_SECONDS = 180.0


def peer_route_status(bridge, config, peer):
    """Sanitized route state for one authorized peer: no pane, PID or process data.

    Never reports a recipient as ready. Exact selection, identity and readiness are
    re-validated at the effect point of every attempt.
    """
    base = {"known_ready": False, "effect_point": "exact_target_revalidated_before_input"}
    if peer == "codex" and config.visible_handoffs.native_codex is not None:
        return {**base, "kind": "native_codex_root", "state": "validated_per_attempt"}
    if peer not in config.visible_handoffs.bindings:
        return {**base, "kind": "no_visible_binding", "state": "not_applicable"}
    presence = bridge.visible_handoffs.presence(peer)
    state, observed = presence["state"], presence.get("observed_at")
    age = time.time() - observed if isinstance(observed, (int, float)) else None
    # A negative age means the wall clock stepped back; it is never "fresh".
    if state in {"available", "replaced", "rehomed"} and (
        age is None or age < -5.0 or age > PRESENCE_FRESH_SECONDS
    ):
        state = "observation_aged"
    if age is not None:
        age = max(0.0, age)
    evidence = presence.get("evidence") or {}
    return {
        **base,
        "kind": "visible_terminal",
        "state": state,
        "reason": presence.get("reason"),
        "observed_age_seconds": round(age) if age is not None else None,
        **({"remedy": evidence["remedy"]} if isinstance(evidence.get("remedy"), str) else {}),
    }


def _text_sha256(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# Raised by the native insert script's guards before the Paste menu action is performed.
PRE_PASTE_REFUSALS = frozenset(
    {
        "clipboard_changed",
        "visible_input_not_empty",
        "visible_input_changed",
        "visible_target_changed",
        "session_busy",
    }
)


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
            # Kernel generation of an exact binding triple, recorded once at an
            # authorized, fresh native match. Equality-only; legacy rows stay absent.
            store.db.execute(
                "CREATE TABLE IF NOT EXISTS binding_generations ("
                "pane_id TEXT NOT NULL,expected_pid INTEGER NOT NULL,"
                "agent_pid INTEGER NOT NULL,target TEXT NOT NULL,"
                "generations TEXT NOT NULL,recorded_at REAL NOT NULL,"
                "source TEXT NOT NULL DEFAULT 'exact_match_bootstrap',"
                "PRIMARY KEY(pane_id,expected_pid,agent_pid))"
            )
            # Current per-target receiver presence; reporting only, never an effect.
            store.db.execute(
                "CREATE TABLE IF NOT EXISTS receiver_presence ("
                "target TEXT PRIMARY KEY,state TEXT NOT NULL,binding TEXT NOT NULL,"
                "evidence TEXT NOT NULL,observed_at REAL NOT NULL)"
            )

    PRESENCE_STATES = frozenset(
        {"available", "stale", "absent", "ambiguous", "replaced", "rehomed", "unknown"}
    )
    # The only receiver-management owner: the local operator identity. Capabilities
    # such as session.open/terminal.execute are granted to remote callers too and
    # are not authority to replace a persistent assignment.
    OWNER_PRINCIPAL = "local"
    # Lineage: a legacy triple first matched exactly, or a fresh owner assignment.
    GENERATION_SOURCES = frozenset({"exact_match_bootstrap", "owner_started_assignment"})

    # Injectable for tests: (pids) -> {pid: generation} or None when unverifiable.
    generation_observer = staticmethod(fresh_generations)

    def recorded_generations(self, binding, target=None):
        """Recorded generations of this exact triple (scoped to ``target`` if given).

        A malformed record is returned as an empty mapping: it exists, so it can
        never be bootstrapped over, and it never compares equal.
        """
        import json

        query = (
            "SELECT generations FROM binding_generations "
            "WHERE pane_id=? AND expected_pid=? AND agent_pid=?"
        )
        values = [binding.pane_id, binding.expected_pid, binding.agent_pid]
        if target is not None:
            query += " AND target=?"
            values.append(target)
        row = self.store.db.execute(query, values).fetchone()
        if row is None:
            return None
        try:
            saved = json.loads(row["generations"])
            return {
                int(pid): value
                for pid, value in saved.items()
                if valid_generation(value) and value["pid"] == int(pid)
            }
        except (TypeError, ValueError, AttributeError):
            return {}

    def generation_source(self, binding, target):
        row = self.store.db.execute(
            "SELECT source FROM binding_generations WHERE pane_id=? AND expected_pid=? "
            "AND agent_pid=? AND target=?",
            (binding.pane_id, binding.expected_pid, binding.agent_pid, target),
        ).fetchone()
        return row["source"] if row else None

    def _store_generation(self, target, binding, observed, source):
        if source not in self.GENERATION_SOURCES:
            raise ValueError(source)
        pids = (binding.expected_pid, binding.agent_pid)
        with self.store.transaction():
            self.store.db.execute(
                "INSERT OR IGNORE INTO binding_generations VALUES(?,?,?,?,?,?,?)",
                (
                    binding.pane_id,
                    binding.expected_pid,
                    binding.agent_pid,
                    target,
                    canonical({str(p): observed[p] for p in pids}),
                    time.time(),
                    source,
                ),
            )

    def fresh_pair(self, binding):
        """Two kernel reads of the binding PIDs; equal means one stable generation."""
        pids = (binding.expected_pid, binding.agent_pid)
        try:
            first = self.generation_observer(pids)
            second = self.generation_observer(pids)
        except Exception:  # noqa: BLE001 - an adapter fault is unverifiable, never "same"
            return None
        if (
            not isinstance(first, dict)
            or not isinstance(second, dict)
            or not all(same_generation(first.get(p), second.get(p)) for p in pids)
        ):
            return None
        return second

    def effect_generation_guard(self, target, binding):
        """Immediately before transport: a recorded lineage must still be the same.

        No record keeps the legacy route unchanged. A record that cannot be
        re-verified, or differs, refuses before any input.
        """
        recorded = self.recorded_generations(binding, target)
        if recorded is None:
            return "unverified"
        current = self.fresh_pair(binding)
        pids = (binding.expected_pid, binding.agent_pid)
        if current is None or not all(
            same_generation(recorded.get(p), current.get(p)) for p in pids
        ):
            error = BridgeError(
                "visible_target_changed",
                "Receiver process generation changed or unverifiable at input; no input",
            )
            error.observation = {
                "state": "target_changed",
                "reason": "process_generation_changed"
                if current is not None
                else "process_generation_unverifiable",
                "target": target,
            }
            raise error
        return "verified"

    def verify_generation(self, target, binding, before, after):
        """Effect-point identity for one exact native match. Never infers legacy birth.

        ``before``/``after`` are kernel observations taken around the catalog match;
        equal values prove the matched PIDs belonged to those generations. The first
        such fresh match records the generation; later matches must be equal.
        Returns ``verified`` or ``unverified``; raises on a proven different process.
        """
        pids = (binding.expected_pid, binding.agent_pid)
        recorded = self.recorded_generations(binding, target)
        fresh = (
            isinstance(before, dict)
            and isinstance(after, dict)
            and all(same_generation(before.get(p), after.get(p)) for p in pids)
        )
        if recorded is not None:
            if not fresh:
                raise BridgeError(
                    "visible_target_unknown",
                    "Recorded process generation cannot be re-verified now; no input",
                )
            if not all(same_generation(recorded.get(p), after.get(p)) for p in pids):
                error = BridgeError(
                    "visible_target_changed",
                    "Same PID number, different kernel process generation; no input",
                )
                error.observation = {
                    "state": "target_changed",
                    "reason": "process_generation_changed",
                    "target": target,
                }
                raise error
            return "verified"
        if not fresh:
            return "unverified"
        # Bootstrap of an exactly matched legacy triple: what holds it now is, by the
        # existing binding definition, the bound process. Never back-dated.
        self._store_generation(target, binding, after, "exact_match_bootstrap")
        return "verified"

    def record_presence(self, principal, target, state, binding, evidence):
        import json

        if state not in self.PRESENCE_STATES:
            raise ValueError(state)
        now = time.time()
        with self.store.transaction():
            previous = self.store.db.execute(
                "SELECT state,evidence FROM receiver_presence WHERE target=?", (target,)
            ).fetchone()
            self.store.db.execute(
                "INSERT INTO receiver_presence VALUES(?,?,?,?,?) ON CONFLICT(target) DO UPDATE "
                "SET state=excluded.state,binding=excluded.binding,"
                "evidence=excluded.evidence,observed_at=excluded.observed_at",
                (target, state, canonical(binding.model_dump()), canonical(evidence), now),
            )
            if (
                previous is None
                or previous["state"] != state
                or (json.loads(previous["evidence"]).get("reason") != evidence.get("reason"))
            ):
                self.store.audit(
                    "receiver_presence_changed",
                    principal,
                    None,
                    {
                        "target": target,
                        "state": state,
                        "previous_state": previous["state"] if previous else None,
                        "reason": evidence.get("reason"),
                        "pane_id": binding.pane_id,
                        "automatic_retry": False,
                    },
                )

    def presence(self, target):
        import json

        row = self.store.db.execute(
            "SELECT * FROM receiver_presence WHERE target=?", (target,)
        ).fetchone()
        if row is None:
            return {"target": target, "state": "unknown", "reason": "never_observed"}
        evidence = json.loads(row["evidence"])
        return {
            "target": target,
            "state": row["state"],
            "reason": evidence.get("reason"),
            "evidence": evidence,
            "binding": json.loads(row["binding"]),
            "observed_at": row["observed_at"],
        }

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

    async def reconcile_observed(self, principal, identifier):
        """Reconcile a manually completed Codex turn from its original pre-paste cursor.

        This path only reads the bound Codex rollout and visible process binding. It
        never retries the paste or sends Return.
        """
        status = self.reconcile(principal, identifier)
        if (
            status["state"] not in {"unknown", "confirmed"}
            or not any(
                event["state"] == "unknown"
                and event["evidence"].get("reason") == "visible_paste_unconfirmed"
                for event in status["events"]
            )
            or status["target"] != "codex"
        ):
            return status

        from kirabridge.bridge_core.config import VisibleTerminalBinding

        try:
            binding = VisibleTerminalBinding.model_validate(status["binding"])
        except (TypeError, ValueError):
            return status
        if self.config.visible_handoffs.bindings.get("codex") != binding:
            return status

        message = self.messages.get(principal, status["message_id"])
        if (
            message["sender"] != principal
            or message["recipient"] != "codex"
            or not isinstance(message["body"], str)
            or not message["request_reply"]
        ):
            return status

        inserting = next(
            (
                event["evidence"]
                for event in status["events"]
                if event["state"] == "inserting"
                and isinstance(event["evidence"].get("local_reply_observer"), dict)
            ),
            None,
        )
        observer_record = inserting.get("local_reply_observer") if inserting else None
        cursor = observer_record.get("cursor") if observer_record else None
        if (
            inserting is None
            or inserting.get("wait_for_reply") is not True
            or not isinstance(observer_record, dict)
            or observer_record.get("state") != "ready"
            or not isinstance(cursor, dict)
        ):
            return status

        try:
            async with self.sessions.agent_selection(principal, "codex", binding):
                await self.check_target(principal, "codex", binding)
                observed = await self.codex_reply.observe(
                    cursor,
                    binding,
                    body=message["body"],
                    process_identity=self.sessions.terminal_app.process_identity,
                )
                await self.check_target(principal, "codex", binding)
        except BridgeError:
            return self.status(principal, identifier)

        if (
            not isinstance(observed, dict)
            or observed.get("state") != "completed"
            or observed.get("reply_source") != "bound_local_codex_rollout"
            or observed.get("agent_confirmed") is not False
            or not isinstance(observed.get("evidence"), dict)
        ):
            return self.status(principal, identifier)

        # Recheck authenticated completion after the local observation. If a
        # mailbox ACK arrived meanwhile, its existing reconciliation wins.
        status = self.reconcile(principal, identifier)
        if status["state"] not in {"unknown", "confirmed"}:
            return status

        evidence = {
            **observed["evidence"],
            "handoff_id": identifier,
            "message_id": status["message_id"],
            "route": "existing_visible_terminal",
            "reply_route": "bound_local_codex_rollout_reconciliation",
            "reply_visible_rendering": "client_not_attested",
            "completion_scope": "local_agent_turn",
            "agent_confirmed": False,
            "request_reply_satisfied": True,
            "reconciled_without_input": True,
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
        mailbox_acknowledged = False
        with self.store.transaction():
            current = self.store.db.execute(
                "SELECT state,evidence FROM visible_handoffs WHERE id=?", (identifier,)
            ).fetchone()
            if current and current["state"] in {"unknown", "confirmed"}:
                import json

                current_evidence = json.loads(current["evidence"])
                if current["state"] == "confirmed" or "visible_paste_unconfirmed" in {
                    current_evidence.get("reason"),
                    current_evidence.get("previous_reason"),
                }:
                    message_row = self.store.db.execute(
                        "SELECT acknowledged,conversation_id FROM messages WHERE id=?",
                        (status["message_id"],),
                    ).fetchone()
                    mailbox_reply = (
                        self.store.db.execute(
                            "SELECT 1 FROM messages WHERE reply_to=? AND sender=? "
                            "AND recipient=? AND conversation_id=? "
                            "AND kind IN ('answer','result') LIMIT 1",
                            (
                                status["message_id"],
                                "codex",
                                principal,
                                message_row["conversation_id"],
                            ),
                        ).fetchone()
                        if message_row
                        else None
                    )
                    mailbox_acknowledged = bool(message_row and message_row["acknowledged"])
                    if not mailbox_acknowledged or not mailbox_reply:
                        self.transition(
                            identifier,
                            "completed",
                            {**evidence, "local_reply_result": result},
                        )
        if mailbox_acknowledged:
            return self.reconcile(principal, identifier)
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
        observation = assess(target, output["text"], binding, protocol)
        if not self.config.visible_handoffs.allow_interim_messages:
            observation["interim_ready"] = False
            observation["allowed_actions"] = [
                action
                for action in observation.get("allowed_actions", [])
                if action != "interim_message"
            ]
        return {
            **observation,
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
            if (
                status["state"] == "unknown"
                and status["binding"] == binding.model_dump()
                and self.body_only_delivery(status)
                and status["evidence"].get("reason")
                in {"reply_unconfirmed", "reply_unconfirmed_target_ready"}
            ):
                # The input was delivered and returned; only its ANSWER is unknown and its
                # waiter has ended. The lock exists to protect pending input, so a fresh
                # positive ready check of this same target releases it. Never replayed.
                if status["evidence"].get("reason") == "reply_unconfirmed_target_ready":
                    continue
                await self.check_target(principal, target, binding, ready=True)
                self.transition(
                    row["id"],
                    "unknown",
                    {
                        **status["evidence"],
                        "reason": "reply_unconfirmed_target_ready",
                        "previous_reason": status["evidence"].get("reason"),
                        "input_reservation_released": True,
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
            if self._unconfirmed_input(status):
                # The paste/insert outcome stayed unknown. The lock protects possibly
                # pending input, so only a FRESH ready observation (empty, idle input of
                # this same window) releases it. Text still in the field keeps the lock.
                await self.check_target(principal, target, binding, ready=True)
                if status["evidence"].get("reason") != "unconfirmed_input_lock_released":
                    self.transition(
                        row["id"],
                        "unknown",
                        {
                            **status["evidence"],
                            "reason": "unconfirmed_input_lock_released",
                            "previous_reason": status["evidence"].get("reason"),
                            "input_reservation_released": True,
                            "automatic_retry": False,
                            "target_readiness": "verified_ready_before_new_input",
                        },
                    )
                continue  # The old message stays unknown and is never sent again.
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
    def _unconfirmed_input(status):
        """Paste/insert outcome unknown; its lock ends only after a fresh ready check."""
        return status["state"] == "unknown" and status["evidence"].get("reason") in {
            "visible_paste_unconfirmed",
            "visible_insert_unknown",
            "unconfirmed_input_lock_released",
        }

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
        presence = self.presence(target)
        try:
            await self.check_target(principal, target, binding, ready=True)
        except BridgeError as error:
            # Same pre-input code as before; the sender additionally learns the
            # persisted receiver state. Never starts, picks or rebinds an agent.
            if (
                error.code == "session_selection_changed"
                and presence["state"] in {"stale", "absent", "ambiguous", "unknown"}
                and getattr(error, "observation", None) is None
            ):
                error.observation = {
                    "state": presence["state"],
                    "reason": presence["reason"] or "unobserved",
                    "target": target,
                }
            raise

    async def refreshed_binding(self, principal, target, binding, *, only_candidate=None):
        """Use the saved binding while its process lives. Replace only a dead unique agent.

        The returned session list is the catalog snapshot that proved the replacement.
        Callers may use it to ignore reservations on that dead pane. A matched binding
        returns no snapshot, so an unrelated reservation keeps its existing lock.
        Every outcome is recorded as receiver presence; none of them sends input.
        """
        selection_reason = None
        try:
            selected = await self.sessions.selected(
                principal, binding.pane_id, binding.expected_pid
            )
        except BridgeError as error:
            selected = None
            detail = getattr(error, "provider_error", None)
            selection_reason = (
                detail.get("reason") if isinstance(detail, dict) else None
            ) or error.code
        if selected is not None and self.sessions.binding_matches(selected, binding, target):
            self.record_presence(principal, target, "available", binding, {"reason": "matched"})
            return binding, None
        lifecycle = self._lifecycle_change(target, binding, selected, selection_reason)
        try:
            catalog = await self.sessions.catalog(principal)
        except BridgeError as error:
            self.record_presence(
                principal, target, "unknown", binding, {"reason": "catalog_" + error.code}
            )
            return binding, None
        if not catalog_can_replace(catalog):
            self.record_presence(
                principal, target, "unknown", binding, {"reason": "catalog_incomplete"}
            )
            return binding, None
        sessions = catalog.get("sessions") or []
        if selected is None and only_candidate is None:
            moved = self._same_process_moved(target, binding, sessions)
            if moved is not None:
                rehomed = await self._rehome(principal, target, binding, moved)
                if rehomed is not None:
                    return rehomed, None
        try:
            await self.sessions.prove_original_target_gone(principal, binding.model_dump())
        except BridgeError as error:
            # Strict proof failed (e.g. an original PID number is occupied). A
            # legacy binding has no kernel generation, so nothing can be proven:
            # the operator must assign the receiver again, exactly, once.
            self.record_presence(
                principal,
                target,
                "stale",
                binding,
                {
                    "reason": error.code,
                    "selection_reason": selection_reason,
                    "lifecycle": lifecycle,
                    "identity": (
                        "generation_recorded"
                        if self.recorded_generations(binding, target) is not None
                        else "unverified_legacy"
                    ),
                    "remedy": "new_exact_assignment_required",
                },
            )
            return binding, None
        updated = replacement_binding(target, binding, sessions)
        if (
            updated is not None
            and only_candidate is not None
            and (
                (updated.pane_id, updated.expected_pid, updated.agent_pid) != tuple(only_candidate)
            )
        ):
            # A launch-driven refresh may adopt only the handle that launch started,
            # never a different live same-CLI session.
            updated = None
        if updated is None:
            # The catalog is complete and the configured pane is proven gone;
            # retain that snapshot even without a replacement so an orphaned
            # reservation on this exact binding can be released.
            candidates = [
                row
                for row in sessions
                if row.get("agent_candidate") == target
                or row.get("agent_candidates_ambiguous")
                and any(p.get("name") == target for p in row.get("processes", []))
            ]
            self.record_presence(
                principal,
                target,
                "ambiguous" if candidates else "absent",
                binding,
                {
                    "reason": (
                        "replacement_not_unique"
                        if candidates
                        else "original_target_gone_no_replacement"
                    ),
                    "candidates": len(candidates),
                    "remedy": "new_exact_assignment_required",
                },
            )
            return binding, sessions
        self.config.visible_handoffs.bindings[target] = updated
        save_refresh(self.config, target, binding, updated)
        self.record_presence(
            principal,
            target,
            "replaced",
            updated,
            {
                "reason": "unique_replacement_bound",
                "previous_pane_id": binding.pane_id,
            },
        )
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

    def _lifecycle_change(self, target, binding, selected, selection_reason):
        """Name what changed in the bound tab; reporting only, never a rebind."""
        if selected is None:
            return {
                "expected_pid_changed": "shell_restarted_or_replaced",
                "window_changed": "tty_in_other_window",
                "pane_missing": "window_closed_or_moved",
            }.get(selection_reason, "unobserved")
        agents, _ = self.sessions.agent_registry()
        names = {p.get("name") for p in selected.get("processes", []) if p.get("name") in agents}
        if any(
            p.get("pid") == binding.agent_pid and p.get("name") != target
            for p in selected.get("processes", [])
        ):
            return "agent_pid_now_other_program"
        if target in names:
            return "agent_restarted_new_process"
        if names:
            return "agent_switched"
        return "agent_exited"

    @staticmethod
    def _exact_row(row, target, pane_id, shell, agent):
        """One native, unambiguous row for exactly this pane/TTY/shell/agent handle."""
        try:
            if (
                not isinstance(row, dict)
                or not isinstance(pane_id, str)
                or not isinstance(row.get("processes"), list)
                or type(shell) is not int
                or type(agent) is not int
                or shell <= 0
                or agent <= 0
                or shell == agent
            ):
                return False
            tty = pane_id.rsplit(":", 1)[-1]
            processes = row["processes"]
            if not all(isinstance(p, dict) for p in processes):
                return False
            return (
                bool(re.fullmatch(r"terminal:[1-9][0-9]*:ttys[0-9]+", pane_id))
                and row.get("pane_id") == pane_id
                and row.get("expected_pid") == shell
                and row.get("transport") == "terminal_app"
                and row.get("identity_ambiguous") is not True
                and not row.get("selection_ambiguous")
                and row.get("tty") == "/dev/" + tty
                and sum(p.get("pid") == agent for p in processes) == 1
                and sum(p.get("pid") == agent and p.get("name") == target for p in processes) == 1
            )
        except (TypeError, AttributeError, ValueError):
            return False

    def _same_process_moved(self, target, binding, sessions):
        """The same kernel processes now appear in exactly one other native tab.

        Requires a recorded lineage, a well-formed complete catalog, one row per old
        shell PID / old TTY / old agent PID that is the same exact row, and equal fresh
        generations. Name/geometry never count; a corrupted observation is None.
        """
        recorded = self.recorded_generations(binding, target)
        pids = (binding.expected_pid, binding.agent_pid)
        if not recorded or not all(p in recorded for p in pids):
            return None
        try:
            if not isinstance(sessions, list) or not all(
                isinstance(r, dict)
                and isinstance(r.get("processes", []), list)
                and all(isinstance(p, dict) for p in r.get("processes", []))
                for r in sessions
            ):
                return None  # any malformed row makes the whole observation untrusted
            if any(r.get("pane_id") == binding.pane_id for r in sessions):
                return None
            tty = "/dev/" + binding.pane_id.rsplit(":", 1)[1]
            by_shell = [
                r
                for r in sessions
                if binding.expected_pid in {r.get("expected_pid"), r.get("legacy_expected_pid")}
            ]
            by_tty = [r for r in sessions if r.get("tty") == tty]
            by_agent = [
                r
                for r in sessions
                if isinstance(r.get("processes"), list)
                and any(
                    isinstance(p, dict) and p.get("pid") == binding.agent_pid
                    for p in r["processes"]
                )
            ]
        except (TypeError, AttributeError, ValueError):
            return None
        if not (len(by_shell) == len(by_tty) == len(by_agent) == 1):
            return None
        row = by_shell[0]
        if row is not by_tty[0] or row is not by_agent[0]:
            return None
        pane_id = row.get("pane_id")
        if not self._exact_row(row, target, pane_id, binding.expected_pid, binding.agent_pid):
            return None
        if not pane_id.endswith(":" + binding.pane_id.rsplit(":", 1)[1]):
            return None
        current = self.fresh_pair(binding)
        if current is None or not all(
            same_generation(recorded.get(p), current.get(p)) for p in pids
        ):
            return None
        return binding.model_copy(update={"pane_id": pane_id})

    def _persist_assignment(self, target, previous, updated, generations, source):
        """Ledger, then overlay, then RAM. Returns a refusal reason or None.

        A ledger row without an overlay is inert evidence: no mapping refers to it.
        An existing lineage row for the new triple must be identical (same target,
        source and generations); it is never silently overwritten or reinterpreted.
        """
        import sqlite3

        pids = (updated.expected_pid, updated.agent_pid)
        try:
            existing = self.store.db.execute(
                "SELECT target,source,generations FROM binding_generations "
                "WHERE pane_id=? AND expected_pid=? AND agent_pid=?",
                (updated.pane_id, updated.expected_pid, updated.agent_pid),
            ).fetchone()
            if existing is not None:
                saved = self.recorded_generations(updated, target) or {}
                if (
                    existing["target"] != target
                    or existing["source"] != source
                    or not all(same_generation(saved.get(p), generations.get(p)) for p in pids)
                ):
                    return "lineage_conflict"
            else:
                self._store_generation(target, updated, generations, source)
        except (sqlite3.Error, ValueError, TypeError):
            return "lineage_write_failed"
        try:
            save_refresh(self.config, target, previous, updated)
        except OSError:
            return "overlay_write_failed"
        self.config.visible_handoffs.bindings[target] = updated
        return None

    async def _rehome(self, principal, target, binding, moved):
        """Same processes, new window id: carry lineage; reservations keep their locks.

        Re-selects the new pane after the catalog and requires both recorded
        generations before and after that read, then compare-and-sets the mapping.
        Returns None (no change) on any doubt.
        """
        recorded = self.recorded_generations(binding, target)
        source = self.generation_source(binding, target)
        pids = (moved.expected_pid, moved.agent_pid)
        before = self.fresh_pair(moved)
        try:
            row = await self.sessions.selected(principal, moved.pane_id, moved.expected_pid)
        except BridgeError:
            return None
        after = self.fresh_pair(moved)
        if (
            not recorded
            or source is None
            or before is None
            or after is None
            or not self._exact_row(row, target, moved.pane_id, *pids)
            or not all(
                same_generation(recorded.get(p), before.get(p))
                and same_generation(recorded.get(p), after.get(p))
                for p in pids
            )
            or self.config.visible_handoffs.bindings.get(target) != binding
        ):
            return None
        if self._persist_assignment(target, binding, moved, after, source) is not None:
            return None
        self.record_presence(
            principal,
            target,
            "rehomed",
            moved,
            {"reason": "same_generation_new_window", "previous_pane_id": binding.pane_id},
        )
        self.store.audit(
            "visible_binding_rehomed",
            principal,
            None,
            {
                "target": target,
                "previous_pane_id": binding.pane_id,
                "pane_id": moved.pane_id,
                "expected_pid": moved.expected_pid,
                "agent_pid": moved.agent_pid,
                "lineage_source": source,
                "automatic_retry": False,
            },
        )
        return moved

    async def _owner_assignment(self, principal, target, binding, started, current):
        """Bind exactly the handle the local owner's launch started, as a new lineage.

        Only ``OWNER_PRINCIPAL`` may do this. Refusals keep the unchanged ``unresolved``
        result and audit their reason. After every await the exact candidate is
        resolved again with a stable kernel pair; immediately before persisting, a
        synchronous compare-and-set re-validates authority, the original mapping,
        active reservations and handle ownership. Old messages, reservations and
        history are never touched or re-sent.
        """

        def refused(reason):
            self.store.audit(
                "visible_binding_assignment_refused",
                principal,
                None,
                {"target": target, "reason": reason, "automatic_retry": False},
            )
            return {"state": "unresolved", "target": target}

        def authorized():
            if principal != self.OWNER_PRINCIPAL:
                return False
            try:
                for capability in ("session.open", "terminal.execute"):
                    self.security.principal(principal, capability)
            except BridgeError:
                return False
            return True

        def active_reservation():
            return self.store.db.execute(
                "SELECT 1 FROM visible_handoffs WHERE target=? AND state IN ('planned',"
                "'inserting','inserted','submitting','return_sent','sent','confirmed') LIMIT 1",
                (target,),
            ).fetchone()

        if not authorized():
            return refused("owner_authority_required")
        pane, shell, agent = (
            started.get("pane_id"),
            started.get("expected_pid"),
            started.get("agent_pid"),
        )
        if not self._exact_row(current, target, pane, shell, agent):
            return refused("started_handle_not_exact")
        if active_reservation():
            return refused("active_reservation")
        updated = binding.model_copy(
            update={
                "pane_id": pane,
                "expected_pid": shell,
                "agent_pid": agent,
                "codex_thread_id": None,
                "codex_rollout_path": None,
            }
        )
        pids = (shell, agent)
        before = self.fresh_pair(updated)
        if before is None:
            return refused("generation_unverifiable")
        try:
            catalog = await self.sessions.catalog(principal)
        except BridgeError:
            return refused("catalog_unavailable")
        sessions = catalog.get("sessions") if isinstance(catalog, dict) else None
        if (
            not catalog_can_replace(catalog)
            or not isinstance(sessions, list)
            or not all(isinstance(r, dict) for r in sessions)
        ):
            return refused("catalog_incomplete")
        if (
            sum(self._exact_row(r, target, pane, shell, agent) for r in sessions) != 1
            or sum(r.get("pane_id") == pane for r in sessions) != 1
        ):
            return refused("candidate_not_in_catalog")
        if binding_still_present(binding, sessions):
            return refused("old_target_still_present")
        try:
            final = await self.sessions.selected(principal, pane, shell)
        except BridgeError:
            return refused("candidate_changed")
        if not self._exact_row(final, target, pane, shell, agent):
            return refused("candidate_changed")
        after = self.fresh_pair(updated)
        if after is None or not all(same_generation(before.get(p), after.get(p)) for p in pids):
            return refused("generation_changed")
        # Compare-and-set: no await from here until the mapping is published.
        if not authorized():
            return refused("owner_authority_required")
        if self.config.visible_handoffs.bindings.get(target) != binding:
            return refused("binding_changed")
        if active_reservation():
            return refused("active_reservation")
        handle = {pane, shell, agent}
        if any(
            other != target and handle & {item.pane_id, item.expected_pid, item.agent_pid}
            for other, item in self.config.visible_handoffs.bindings.items()
        ):
            return refused("handle_assigned_to_other_target")
        previous_source = self.generation_source(binding, target)
        failure = self._persist_assignment(
            target, binding, updated, after, "owner_started_assignment"
        )
        if failure is not None:
            return refused(failure)
        self.record_presence(
            principal,
            target,
            "replaced",
            updated,
            {
                "reason": "owner_started_assignment",
                "previous_pane_id": binding.pane_id,
                "previous_identity": previous_source or "unverified_legacy",
                "provider_context": "not_carried",
            },
        )
        self.store.audit(
            "visible_binding_assigned",
            principal,
            None,
            {
                "target": target,
                "mode": "owner_started_assignment",
                "previous_pane_id": binding.pane_id,
                "previous_expected_pid": binding.expected_pid,
                "previous_agent_pid": binding.agent_pid,
                "pane_id": updated.pane_id,
                "expected_pid": updated.expected_pid,
                "agent_pid": updated.agent_pid,
                "automatic_retry": False,
            },
        )
        return {
            "state": "bound",
            "target": target,
            "pane_id": updated.pane_id,
            "expected_pid": updated.expected_pid,
            "agent_pid": updated.agent_pid,
            "mode": "owner_started_assignment",
        }

    async def started_binding(self, principal, target, started):
        """Bind a newly started CLI only after its exact live process is observed.

        This reuses the existing dead-binding proof and durable refresh overlay.
        A missing configured contract stays explicitly unbound.
        """
        binding = self.config.visible_handoffs.bindings.get(target)
        if binding is None:
            return {"state": "unbound", "target": target}
        try:
            current = await self.sessions.selected(
                principal, started["pane_id"], started["expected_pid"]
            )
        except BridgeError:
            return {"state": "unresolved", "target": target}
        if not any(
            item.get("name") == target and item.get("pid") == started.get("agent_pid")
            for item in current.get("processes", [])
        ):
            return {"state": "unresolved", "target": target}
        if self.sessions.binding_matches(current, binding, target):
            return {"state": "unchanged", "target": target}
        if principal == self.OWNER_PRINCIPAL:
            # The local owner's own launch: bind exactly this started handle as a new
            # lineage (e.g. #581). No generic refresh runs first, so no other live
            # same-CLI session can be adopted on the way.
            return await self._owner_assignment(principal, target, binding, started, current)
        # Unchanged compatibility path for other principals: the strict proven-dead
        # refresh, restricted to this launch's own handle. No new override.
        updated, _ = await self.refreshed_binding(
            principal,
            target,
            binding,
            only_candidate=(started["pane_id"], started["expected_pid"], started.get("agent_pid")),
        )
        if updated == binding:
            return {"state": "unresolved", "target": target}
        if (
            updated.pane_id != started["pane_id"]
            or updated.expected_pid != started["expected_pid"]
            or updated.agent_pid != started.get("agent_pid")
        ):
            return {"state": "unresolved", "target": target}
        return {
            "state": "bound",
            "target": target,
            "pane_id": updated.pane_id,
            "expected_pid": updated.expected_pid,
            "agent_pid": updated.agent_pid,
        }

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
        pids = (binding.expected_pid, binding.agent_pid)
        try:
            before = self.generation_observer(pids)
        except Exception:  # noqa: BLE001 - unverifiable, never "same"
            before = None
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
            if row.get("transport") == "terminal_app" and row.get("expected_pid") == pids[0]:
                # Only a real native row is an authorized exact OS observation.
                try:
                    after = self.generation_observer(pids)
                except Exception:  # noqa: BLE001
                    after = None
                try:
                    self.verify_generation(target, binding, before, after)
                except BridgeError as error:
                    # A previously persisted "available" must not survive this.
                    self.record_presence(
                        principal,
                        target,
                        "stale",
                        binding,
                        {
                            "reason": (getattr(error, "observation", None) or {}).get(
                                "reason", error.code
                            )
                        },
                    )
                    raise
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
            # The empty composer may be a rendered placeholder ("Build
            # anything", "Ask anything..."), which no bare ready pattern
            # recognizes. The adapter owns the clear/empty semantics.
            if assess(target, view["text"], binding).get("input_empty"):
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
                # Effect point: the recorded lineage (if any) must still hold now.
                self.effect_generation_guard(target, binding)
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
                try:
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
                except BridgeError as refusal:
                    # These guards run in the native script strictly BEFORE the paste
                    # action, so such a refusal proves nothing was sent: a definite,
                    # retry-safe failure rather than a lock-holding unknown.
                    if not isinstance(refusal, UncertainExecution) and (
                        refusal.code in PRE_PASTE_REFUSALS
                    ):
                        input_attempted = False
                    raise
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
