"""Durable, addressed agent messages. Payloads are data, never shell commands."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Literal

from pydantic import Field, model_validator

from kirabridge.bridge_core.models import BridgeError, Input, canonical, digest


class InterimSession(Input):
    """An explicit current session; never a default or replacement window."""

    pane_id: str = Field(pattern=r"^terminal:[0-9]+:ttys[0-9]+$")
    expected_pid: int = Field(gt=0)
    expected_agent_pid: int = Field(gt=0)


class MessageSend(Input):
    recipient: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    conversation_id: str = Field(min_length=1, max_length=128, pattern=r"^[\w-]+$")
    idempotency_key: str = Field(min_length=1, max_length=128)
    body: str = Field(min_length=1, max_length=65536)
    kind: Literal["question", "answer", "work", "result", "note"] = "question"
    message_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[\w-]+$")
    reply_to: str | None = Field(default=None, min_length=1, max_length=128)
    task_id: str | None = Field(default=None, min_length=1, max_length=128)
    request_reply: bool | None = None
    dispatch: bool | None = None
    interim_session: InterimSession | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="Exact working Codex destination for an interim question/note; no new job",
    )

    @model_validator(mode="after")
    def interim_contract(self):
        if self.interim_session is not None and (
            self.recipient != "codex"
            or self.kind not in {"question", "note"}
            or self.dispatch is False
            or self.request_reply is True
        ):
            raise ValueError("Interim delivery addresses Codex text; no new turn/reply waiter")
        return self


class MessageManager:
    interface_version = "1"

    def activation_work_count(self, *, active_only=False, context=None):
        # An externally ACKed queued job has no delivery left to start. Never
        # infer that a running receiver finished merely because its message is ACKed.
        db = context.db if context is not None else self.store.db
        states = ("running",) if active_only else ("queued", "running")
        return db.execute(
            "SELECT count(*) FROM message_jobs WHERE state IN ("
            + ",".join("?" for _ in states)
            + ") AND (state='running' OR (NOT EXISTS (SELECT 1 FROM queue_holds h "
            "WHERE h.queue_id='messages' AND h.item_id=message_jobs.message_id) "
            "AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.id=message_jobs.message_id "
            "AND m.acknowledged IS NOT NULL)))",
            states,
        ).fetchone()[0]

    def operator_work_count(self):
        return self.store.db.execute(
            "SELECT count(*) FROM message_jobs WHERE state IN ('queued','running') "
            "AND (state='running' OR NOT EXISTS (SELECT 1 FROM queue_holds h "
            "WHERE h.queue_id='messages' AND h.item_id=message_jobs.message_id))"
        ).fetchone()[0]

    def operator_protocol_snapshot(self, message_id, at):
        row = self.store.db.execute(
            "SELECT sender,recipient,body,delivered,acknowledged,created FROM messages WHERE id=?",
            (message_id,),
        ).fetchone()
        if row is None or row["created"] > at:
            return None
        result = {key: row[key] for key in row.keys() if key != "created"}
        for key in ("delivered", "acknowledged"):
            if result[key] is not None and result[key] > at:
                result[key] = None
        return result

    def __init__(self, config, store, security):
        self.config, self.store, self.security = config, store, security
        self.wake = asyncio.Event()
        # Runtime-owned admission of NEW records only. Idempotent reads and
        # historical inbox entries never call this hook.
        self.delivery_hook = None
        self.coordinator_resolver = None
        from kirabridge.voice_channel import VoiceChannel
        from kirabridge.voice_message_policy import VoiceMessagePolicy

        self.voice_channel = VoiceChannel(config, store)
        self.voice_policy = VoiceMessagePolicy(self)

    def _identity(self, principal, capability):
        return self.security.principal(principal, capability)

    def _row(self, principal, message_id):
        row = self.store.db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        if row is None:
            raise BridgeError("not_found", "Message not found")
        members = self.voice_channel.check(principal, row["conversation_id"])
        if not members and principal not in {row["sender"], row["recipient"]}:
            if (
                not self._is_coordinator_conversation_message(message_id)
                or self.coordinator_resolver is None
            ):
                raise BridgeError("not_found", "Message not found")
            try:
                current = self.coordinator_resolver()
            except BridgeError:
                raise BridgeError("not_found", "Message not found") from None
            if current["principal"] != principal:
                raise BridgeError("not_found", "Message not found")
        return row

    def _is_coordinator_message(self, message_id):
        row = self.store.db.execute(
            "SELECT evidence FROM message_events WHERE message_id=? AND kind='message.queued' "
            "ORDER BY seq LIMIT 1",
            (message_id,),
        ).fetchone()
        try:
            return bool(row and json.loads(row["evidence"]).get("recipient_role") == "coordinator")
        except (ValueError, TypeError, AttributeError):
            return False

    def _is_coordinator_conversation_message(self, message_id):
        row = self.store.db.execute(
            "SELECT evidence FROM message_events WHERE message_id=? AND kind='message.queued' "
            "ORDER BY seq LIMIT 1",
            (message_id,),
        ).fetchone()
        try:
            metadata = json.loads(row["evidence"]) if row else {}
        except (ValueError, TypeError):
            return False
        return (
            metadata.get("recipient_role") == "coordinator"
            or metadata.get("coordinator_conversation") is True
        )

    def _event(self, message_id, kind, principal, evidence):
        self.store.db.execute(
            "INSERT INTO message_events(message_id,at,kind,evidence) VALUES(?,?,?,?)",
            (message_id, time.time(), kind, canonical(evidence)),
        )
        self.store.audit(kind, principal, None, {"message_id": message_id, **evidence})

    def get(self, principal, message_id):
        self._identity(principal, "message.read")
        pending = self.voice_policy.get(principal, message_id)
        if pending and (
            pending.get("transport") == "team" or pending["message_buffer"]["state"] != "released"
        ):
            return pending
        result = dict(self._row(principal, message_id))
        result.pop("idem")
        result.pop("request_hash")
        job = self.store.db.execute(
            "SELECT * FROM message_jobs WHERE message_id=?", (message_id,)
        ).fetchone()
        result["processing"] = dict(job) if job else None
        visible = (
            job
            and self.store.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='visible_handoffs'"
            ).fetchone()
            and self.store.db.execute(
                "SELECT 1 FROM visible_handoffs WHERE id=?", (job["run_id"],)
            ).fetchone()
        )
        result["processing_route"] = (
            "existing_visible_terminal"
            if visible
            else "managed_receiver"
            if job
            else "external_client_inbox"
        )
        if job:
            result["processing"]["evidence"] = json.loads(job["evidence"])
            delivery_scope = result["processing"]["evidence"].get("completion_scope")
            if delivery_scope in {"visible_input_delivery", "native_input_delivery"}:
                result["processing"].update(
                    completion_scope=delivery_scope,
                    agent_confirmed=False,
                    agent_work_completion_verified=False,
                    request_reply_satisfied=False,
                )
                if delivery_scope == "native_input_delivery":
                    # Native input only proves delivery. Expose a reply id only
                    # when the final addressed answer can be verified below.
                    result["processing"]["reply_id"] = None
                if (
                    delivery_scope == "native_input_delivery"
                    and job["state"] == "completed"
                    and job["error"] is None
                    and result["request_reply"]
                    and result["acknowledged"] is not None
                    and result["processing"]["evidence"].get("native_input_attempted") is True
                ):
                    replies = self.store.db.execute(
                        "SELECT id FROM messages WHERE reply_to=? AND conversation_id=? "
                        "AND sender=? AND recipient=? AND kind IN ('answer','result') "
                        "ORDER BY seq LIMIT 2",
                        (
                            message_id,
                            result["conversation_id"],
                            result["recipient"],
                            result["sender"],
                        ),
                    ).fetchall()
                    if len(replies) == 1:
                        result["processing"].update(
                            reply_id=replies[0]["id"], request_reply_satisfied=True
                        )
            if result["processing"]["evidence"].get("completion_scope") == "local_agent_turn":
                local = result["processing"]["evidence"].pop("local_reply_result", None)
                result["processing"].update(
                    completion_scope="local_agent_turn",
                    reply_source=result["processing"]["evidence"].get(
                        "reply_source", "bound_local_codex_rollout"
                    ),
                    agent_confirmed=False,
                    request_reply_satisfied=True,
                    agent_work_completion_verified=False,
                    result=local,
                )
            scope = result["processing"]["evidence"].get("session_scope")
            if scope in {"existing_visible_terminal", "existing_native_codex_root"}:
                result["processing_route"] = scope
            elif (
                not visible
                and job["state"] in {"failed", "blocked"}
                and result["processing"]["evidence"].get("phase") == "direct_admission"
            ):
                result["processing_route"] = "failed_visible_admission"
            elif job["state"] == "queued":
                result["processing_route"] = (
                    "pending_visible_terminal"
                    if self.config.visible_handoffs.enabled
                    else "pending_managed_receiver"
                )
        if visible:
            # Preserve the original failure and expose only already-recorded evidence.
            # Reading a message must never release a reservation or repeat input.
            try:
                self._identity(principal, "task.read")
            except BridgeError:
                pass  # Message-only readers keep their existing response.
            else:
                from kirabridge.visible_message_evidence import visible_message_evidence

                handoff = visible_message_evidence(
                    self.store.db, principal, message_id, job["run_id"]
                )
                if handoff is not None:
                    result["processing"]["handoff"] = handoff
        result["request_reply"] = bool(result["request_reply"])
        return {"api_version": "1", **result}

    def interim_target(self, message_id):
        row = self.store.db.execute(
            "SELECT evidence FROM message_events WHERE message_id=? AND kind='message.queued' "
            "ORDER BY seq LIMIT 1",
            (message_id,),
        ).fetchone()
        value = json.loads(row[0]).get("interim_session") if row else None
        return InterimSession.model_validate(value) if value else None

    def send(self, principal, message: MessageSend, *, completion_target=None):
        self._identity(principal, "message.send")
        message = self.voice_channel.route(principal, message)
        return self.voice_policy.send(principal, message, completion_target)

    def _send(
        self,
        principal,
        message,
        *,
        completion_target=None,
        validate_only=False,
        visible_internal=False,
    ):
        from kirabridge.completion_manager import valid_target

        if completion_target is not None:
            valid_target(completion_target)
        policy = self._identity(principal, "message.send")
        if policy.permission_level is None and policy.approval_mode != "automatic":
            raise BridgeError(
                "approval_required", "Messaging requires local automatic authorization"
            )
        requested_message = message
        if (
            principal in self.config.team.coordinator_only_senders
            and message.recipient != "coordinator"
        ):
            message = message.model_copy(update={"recipient": "coordinator"})
        recipient_role = message.recipient if message.recipient == "coordinator" else None
        coordinator_route = None
        if recipient_role:
            # Replays stay attached to their original principal even after a role
            # change. New messages resolve from the persisted coordinator role
            # records and bind that choice into the original queued event below.
            previous_route = self.store.db.execute(
                "SELECT recipient FROM messages WHERE sender=? AND idem=?",
                (principal, message.idempotency_key),
            ).fetchone()
            if previous_route:
                coordinator_route = {"principal": previous_route["recipient"], "session": None}
            else:
                if self.coordinator_resolver is None:
                    raise BridgeError(
                        "coordinator_unavailable", "Coordinator role resolver is not initialized"
                    )
                coordinator_route = self.coordinator_resolver()
            message = message.model_copy(update={"recipient": coordinator_route["principal"]})
        target = self.config.principals.get(message.recipient)
        self_reply = (
            principal == message.recipient
            and message.kind in {"answer", "result"}
            and message.reply_to
            and self.store.db.execute(
                "SELECT 1 FROM visible_handoffs WHERE message_id=? AND principal=? AND target=?",
                (message.reply_to, principal, principal),
            ).fetchone()
        )
        bound_self = principal == message.recipient and (visible_internal or self_reply)
        if (
            (principal == message.recipient and not bound_self)
            or (message.recipient not in policy.message_peers and not bound_self)
            or not target
            or (principal not in target.message_peers and not bound_self)
            or "message.read" not in target.capabilities
        ):
            raise BridgeError("message_peer_denied", "Recipient is not an authorized peer")
        limits = self.config.messaging
        dispatch = message.dispatch
        if (
            self.config.visible_handoffs.enabled
            and not visible_internal
            and message.recipient in self.config.agents
            and message.kind in {"work", "question"}
        ):
            dispatch = True  # A caller's dispatch=false cannot select an invisible work route.
        if dispatch is None:
            dispatch = (
                message.kind not in {"answer", "result"} and message.recipient in limits.receivers
            )
        if dispatch and message.recipient in {"chatgpt", "grok_app", "local"}:
            if message.recipient not in limits.receivers:
                dispatch = False
        if (
            coordinator_route
            and coordinator_route.get("delivery") == "inbox"
            and not (
                self.config.visible_handoffs.enabled
                and message.recipient in self.config.visible_handoffs.bindings
                and message.recipient in limits.receivers
                and message.recipient in self.config.agents
            )
        ):
            dispatch = False  # No bound session: store in the inbox, never drive an agent.
        if len(message.body.encode()) > limits.max_body_bytes:
            raise BridgeError("payload_limit", "Message exceeds configured byte limit")
        wants_reply = False if message.interim_session else message.request_reply
        if wants_reply is None:
            wants_reply = message.kind in {"question", "work"}
        if wants_reply and message.kind not in {"question", "work"}:
            raise BridgeError(
                "reply_loop", "Answers, results and notes cannot request auto replies"
            )
        recorded = self.store.db.execute(
            "SELECT m.id,EXISTS(SELECT 1 FROM message_jobs j "
            "WHERE j.message_id=m.id) AS dispatched "
            "FROM messages m WHERE m.sender=? AND m.idem=?",
            (principal, message.idempotency_key),
        ).fetchone()
        if recorded and (
            message.dispatch is None
            or (self.config.visible_handoffs.enabled and message.dispatch is False)
        ):
            dispatch = bool(recorded["dispatched"])
        if dispatch and not recorded:
            from kirabridge.permissions import decision

            receiver = limits.receivers.get(message.recipient)
            if not receiver:
                raise BridgeError("receiver_unavailable", "No automatic receiver for this identity")
            if not decision(self.config, message.recipient, "agent.execute")["automatic"]:
                raise BridgeError(
                    "approval_required", "Dieser Agentenauftrag benötigt deine Erlaubnis"
                )
            if (
                message.recipient not in self.config.agents
                or message.recipient not in target.agents
            ):
                raise BridgeError(
                    "agent_denied", "Receiver agent is not configured for this identity"
                )
        if validate_only:
            return None
        request_payload = requested_message.model_dump()
        hashed = digest({**request_payload, "dispatch": dispatch})
        message_id = message.message_id or str(uuid.uuid4())
        with self.store.transaction():
            previous = self.store.db.execute(
                "SELECT id,request_hash FROM messages WHERE sender=? AND idem=?",
                (principal, message.idempotency_key),
            ).fetchone()
            if previous:
                previous_hash = hashed
                if message.dispatch is None or (
                    self.config.visible_handoffs.enabled and message.dispatch is False
                ):
                    # Preserve the recorded dispatch decision on retries across
                    # upgrades, including old answers sent to managed receivers.
                    recorded_dispatch = bool(
                        self.store.db.execute(
                            "SELECT 1 FROM message_jobs WHERE message_id=?", (previous["id"],)
                        ).fetchone()
                    )
                    previous_hash = digest({**request_payload, "dispatch": recorded_dispatch})
                if previous["request_hash"] != previous_hash:
                    raise BridgeError("idempotency_conflict", "Key belongs to a different message")
                route = self.store.db.execute(
                    "SELECT target FROM message_completion_routes WHERE message_id=?",
                    (previous["id"],),
                ).fetchone()
                if completion_target is not None and completion_target != (
                    route[0] if route else "default"
                ):
                    raise BridgeError(
                        "completion_route_conflict", "Original return target is fixed"
                    )
                return self.get(principal, previous["id"])
            if recipient_role and coordinator_route and coordinator_route.get("session"):
                current_route = self.coordinator_resolver()
                if any(
                    current_route.get(key) != coordinator_route.get(key)
                    for key in ("principal", "session", "team_id", "revision")
                ):
                    raise BridgeError(
                        "coordinator_route_changed",
                        "Coordinator role changed before the message was committed",
                    )
            if dispatch:
                self.store.assert_accepting()
            role_parent = None
            if message.reply_to and self._is_coordinator_message(message.reply_to):
                role_parent = self.store.db.execute(
                    "SELECT sender,recipient FROM messages WHERE id=?",
                    (message.reply_to,),
                ).fetchone()
            conversation = self.store.db.execute(
                "SELECT * FROM conversations WHERE id=?", (message.conversation_id,)
            ).fetchone()
            if recipient_role:
                parties = {principal, "coordinator"}
            elif role_parent:
                parties = {role_parent["sender"], "coordinator"}
            else:
                parties = {principal, message.recipient}
            members = self.voice_channel.check(principal, message.conversation_id)
            if members and message.recipient not in members:
                raise BridgeError("message_peer_denied", "Recipient is not a conversation member")
            if (
                conversation
                and not members
                and {conversation["party_a"], conversation["party_b"]} != parties
            ):
                raise BridgeError("not_found", "Conversation not found")
            parent = self._row(principal, message.reply_to) if message.reply_to else None
            depth, task_id = 0, message.task_id
            if parent:
                if (
                    parent["conversation_id"] != message.conversation_id
                    or parent["recipient"] != principal
                    or parent["sender"] != message.recipient
                ):
                    raise BridgeError("reply_conflict", "Reply must reverse the addressed message")
                depth = parent["depth"] + 1
                if task_id is not None and task_id != parent["task_id"]:
                    raise BridgeError("reply_conflict", "Reply must preserve the task reference")
                task_id = parent["task_id"]
            elif task_id:
                self.store.get(task_id, principal)
            if depth > limits.max_reply_depth and not members:
                raise BridgeError("reply_loop", "Conversation reply depth limit reached")
            position = (
                self.store.db.execute(
                    "SELECT count(*) FROM messages WHERE conversation_id=?",
                    (message.conversation_id,),
                ).fetchone()[0]
                + 1
            )
            if position > limits.max_conversation_messages and not members:
                # An accepted request must remain answerable, including legacy
                # conversations already at the limit. Only its first final reply
                # gets this bounded allowance; new work/notes cannot extend it.
                final_reply = (
                    parent
                    and parent["request_reply"]
                    and parent["kind"] in {"question", "work"}
                    and message.kind in {"answer", "result"}
                    and not wants_reply
                    and not self.store.db.execute(
                        "SELECT 1 FROM messages WHERE reply_to=? "
                        "AND sender=? AND recipient=? AND kind IN ('answer','result') LIMIT 1",
                        (parent["id"], principal, message.recipient),
                    ).fetchone()
                )
                if not final_reply:
                    raise BridgeError("conversation_full", "Conversation message limit reached")
            if (
                self.store.db.execute("SELECT count(*) FROM messages").fetchone()[0]
                >= limits.max_total
            ):
                raise BridgeError("message_store_full", "Message archive capacity reached")
            pending = self.store.db.execute(
                "SELECT count(*) FROM messages WHERE recipient=? AND acknowledged IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM queue_holds h WHERE "
                "h.queue_id='messages' AND h.item_id=messages.id)",
                (message.recipient,),
            ).fetchone()[0]
            if pending >= limits.max_pending_per_recipient:
                raise BridgeError("message_queue_full", "Recipient queue is full")
            if self.store.db.execute("SELECT 1 FROM messages WHERE id=?", (message_id,)).fetchone():
                raise BridgeError("message_id_conflict", "Message ID is already reserved")
            now = time.time()
            if not conversation:
                self.store.db.execute(
                    "INSERT INTO conversations VALUES(?,?,?,?)",
                    (
                        message.conversation_id,
                        *(sorted(parties) if len(parties) == 2 else (principal, principal)),
                        now,
                    ),
                )
            self.store.db.execute(
                "INSERT INTO messages(id,conversation_id,position,sender,recipient,kind,body,idem,"
                "request_hash,reply_to,task_id,depth,request_reply,created) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    message_id,
                    message.conversation_id,
                    position,
                    principal,
                    message.recipient,
                    message.kind,
                    message.body,
                    message.idempotency_key,
                    hashed,
                    message.reply_to,
                    task_id,
                    depth,
                    int(wants_reply),
                    now,
                ),
            )
            if dispatch:
                self.store.db.execute(
                    "INSERT INTO message_completion_routes(message_id,target) VALUES(?,?)",
                    (message_id, completion_target or "default"),
                )
                self.store.db.execute(
                    "INSERT INTO message_jobs(message_id,state) VALUES(?,'queued')", (message_id,)
                )
            self._event(
                message_id,
                "message.queued",
                principal,
                {
                    "recipient": message.recipient,
                    "conversation_id": message.conversation_id,
                    "position": position,
                    "content_sha256": digest(message.body),
                    "automatic_dispatch": dispatch,
                    **(
                        {
                            "recipient_role": recipient_role,
                            "coordinator_session_sha256": (
                                digest(coordinator_route["session"])
                                if coordinator_route and coordinator_route.get("session")
                                else None
                            ),
                            "coordinator_scope_team_id": (
                                coordinator_route.get("team_id") if coordinator_route else None
                            ),
                            "coordinator_role_revision": (
                                coordinator_route.get("revision") if coordinator_route else None
                            ),
                        }
                        if recipient_role
                        else {}
                    ),
                    **({"coordinator_conversation": True} if recipient_role or role_parent else {}),
                    **(
                        {"interim_session": message.interim_session.model_dump()}
                        if message.interim_session
                        else {}
                    ),
                },
            )
        self.wake.set()
        if dispatch and self.delivery_hook is not None:
            self.delivery_hook(principal, message_id)
        return self.get(principal, message_id)

    def receive(self, principal, after=0, limit=20, conversation_id=None):
        self._identity(principal, "message.read")
        if conversation_id:
            self.voice_channel.check(principal, conversation_id)
        if after < 0 or not 1 <= limit <= 50:
            raise BridgeError("invalid_cursor", "Use nonnegative cursor and limit 1..50")
        with self.store.transaction():
            rows = self.store.db.execute(
                "SELECT id,seq,delivered FROM messages WHERE recipient=? AND seq>? "
                "AND acknowledged IS NULL AND (? IS NULL OR conversation_id=?) "
                "AND NOT EXISTS (SELECT 1 FROM queue_holds h WHERE "
                "h.queue_id='messages' AND h.item_id=messages.id) "
                "AND NOT EXISTS (SELECT 1 FROM message_jobs j WHERE j.message_id=messages.id "
                "AND j.state='queued' "
                "AND json_extract(j.evidence, '$.waiting_for_visible_target') = 1 "
                "AND json_extract(j.evidence, '$.terminal_input_attempted') = 0) "
                "ORDER BY seq LIMIT ?",
                (principal, after, conversation_id, conversation_id, limit),
            ).fetchall()
            for row in rows:
                if row["delivered"] is None:
                    receipt = str(uuid.uuid4())
                    self.store.db.execute(
                        "UPDATE messages SET delivered=?,receipt=? WHERE id=?",
                        (time.time(), receipt, row["id"]),
                    )
                    self._event(row["id"], "message.delivered", principal, {"receipt": receipt})
        return {
            "messages": [self.get(principal, row["id"]) for row in rows],
            "next_cursor": rows[-1]["seq"] if rows else after,
            "redelivery": "Unacknowledged messages remain available with the same ID and receipt.",
        }

    async def wait(self, principal, after=0, limit=20, conversation_id=None, wait_seconds=0):
        if not 0 <= wait_seconds <= 20:
            raise BridgeError("invalid_wait", "Long poll is bounded to 20 seconds")
        deadline = asyncio.get_running_loop().time() + wait_seconds
        while True:
            self.wake.clear()
            result = self.receive(principal, after, limit, conversation_id)
            remaining = deadline - asyncio.get_running_loop().time()
            if result["messages"] or remaining <= 0:
                return result
            try:
                await asyncio.wait_for(self.wake.wait(), min(remaining, 2))
            except TimeoutError:
                pass

    def ack(self, principal, message_id, receipt):
        self._identity(principal, "message.ack")
        with self.store.transaction():
            row = self._row(principal, message_id)
            if row["recipient"] != principal:
                raise BridgeError("not_found", "Incoming message not found")
            if not row["receipt"] or receipt != row["receipt"]:
                raise BridgeError("receipt_conflict", "A matching delivery receipt is required")
            if row["acknowledged"] is None:
                self.store.db.execute(
                    "UPDATE messages SET acknowledged=? WHERE id=?", (time.time(), message_id)
                )
                self._event(message_id, "message.acknowledged", principal, {"receipt": receipt})
        return self.get(principal, message_id)

    def conversation(self, principal, conversation_id, after=0, limit=50):
        self._identity(principal, "message.read")
        if after < 0 or not 1 <= limit <= 50:
            raise BridgeError("invalid_cursor", "Use nonnegative cursor and limit 1..50")
        row = self.store.db.execute(
            "SELECT * FROM conversations WHERE id=?", (conversation_id,)
        ).fetchone()
        members = self.voice_channel.check(principal, conversation_id)
        current_coordinator = False
        if (
            row is not None
            and not members
            and "coordinator" in {row["party_a"], row["party_b"]}
            and self.coordinator_resolver is not None
        ):
            try:
                current_coordinator = self.coordinator_resolver()["principal"] == principal
            except BridgeError:
                current_coordinator = False
        if row is None or (
            not members
            and principal not in {row["party_a"], row["party_b"]}
            and not current_coordinator
        ):
            raise BridgeError("not_found", "Conversation not found")
        rows = self.store.db.execute(
            "SELECT id,seq FROM messages WHERE conversation_id=? AND seq>? ORDER BY seq LIMIT ?",
            (conversation_id, after, limit),
        ).fetchall()
        return {
            "conversation_id": conversation_id,
            "participants": members or [row["party_a"], row["party_b"]],
            "append_only": bool(members),
            "messages": [self.get(principal, r["id"]) for r in rows],
            "next_cursor": rows[-1]["seq"] if rows else after,
        }

    def events(self, principal, message_id, after=0):
        self.get(principal, message_id)
        if after < 0:
            raise BridgeError("invalid_cursor", "Cursor must be nonnegative")
        return {
            "events": [
                {**dict(row), "evidence": json.loads(row["evidence"])}
                for row in self.store.db.execute(
                    "SELECT * FROM message_events WHERE message_id=? AND seq>? "
                    "ORDER BY seq LIMIT 100",
                    (message_id, after),
                )
            ]
        }
