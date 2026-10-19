"""Durable voice outbox: a suffix or a later exact marker releases one message."""

import json
import time
import uuid

from kirabridge.bridge_core.models import BridgeError, canonical, digest
from kirabridge.session_input_policy import SUFFIX, marked
from kirabridge.voice_channel import VOICE_PRINCIPALS


class VoiceMessagePolicy:
    def __init__(self, channel):
        self.channel, self.store = channel, channel.store
        self.teams = None

    def _deliver(self, principal, message, target, transport, message_id=None, validate_only=False):
        if transport == "team":
            result = self.teams._send(
                principal, message, message_id=message_id, validate_only=validate_only
            )
            return (
                {**result, "transport": "team"}
                if result and principal in VOICE_PRINCIPALS
                else result
            )
        return self.channel._send(
            principal, message, completion_target=target, validate_only=validate_only
        )

    def _released(self, principal, row):
        request = json.loads(row["request"])
        if request.get("_transport") == "team":
            self.teams._team(principal, request["team_id"])
            return {**self.teams._message(request["team_id"], row["id"]), "transport": "team"}
        return self.channel.get(principal, row["id"])

    def expire(self):
        with self.store.transaction():
            rows = self.store.db.execute(
                "SELECT id,sender FROM voice_message_buffers WHERE state='waiting' AND expires<=?",
                (time.time(),),
            ).fetchall()
            for row in rows:
                self.store.db.execute(
                    "UPDATE voice_message_buffers SET state='expired' WHERE id=?", (row["id"],)
                )
                self.store.audit("message.expired", row["sender"], None, {"message_id": row["id"]})

    def get(self, principal, message_id):
        self.expire()
        row = self.store.db.execute(
            "SELECT * FROM voice_message_buffers WHERE id=? AND sender=?", (message_id, principal)
        ).fetchone()
        if not row:
            return None
        request = json.loads(row["request"])
        if row["state"] == "released" and request.get("_transport") == "team":
            return self._released(principal, row)
        return {
            "api_version": "1",
            "id": row["id"],
            "sender": principal,
            "recipient": request["recipient"],
            "conversation_id": request.get("conversation_id"),
            "transport": request.get("_transport", "message"),
            "body": request["body"],
            "kind": request["kind"],
            "request_reply": request.get("request_reply", False),
            "created": row["created"],
            "message_buffer": {
                "state": row["state"],
                "expires": row["expires"],
                "released": row["released"],
            },
            "delivered": None,
            "acknowledged": None,
            "processing": None,
        }

    def send(self, principal, message, completion_target, *, transport="message"):
        if principal not in VOICE_PRINCIPALS:
            return self._deliver(principal, message, completion_target, transport)
        self.expire()
        # Pre-policy messages already delivered retain their original retry contract.
        previous = self.store.db.execute(
            "SELECT 1 FROM messages m WHERE m.sender=? AND m.idem=? AND NOT EXISTS "
            "(SELECT 1 FROM voice_message_buffers b WHERE b.id=m.id)",
            (principal, message.idempotency_key),
        ).fetchone()
        if previous and transport == "message":
            return self.channel._send(principal, message, completion_target=completion_target)
        # Validate peers, capabilities, payload limits and execution grants before staging.
        self._deliver(principal, message, completion_target, transport, validate_only=True)
        hashed = digest({"transport": transport, **message.model_dump()})
        key = (
            message.idempotency_key
            if transport == "message"
            else "team-"
            + digest(
                {
                    "team_id": message.team_id,
                    "key": message.idempotency_key,
                }
            )
        )
        with self.store.transaction():
            row = self.store.db.execute(
                "SELECT * FROM voice_message_buffers WHERE sender=? AND idem=?",
                (principal, key),
            ).fetchone()
            if row:
                if row["request_hash"] != hashed:
                    raise BridgeError("idempotency_conflict", "Key belongs to a different message")
                if row["completion_target"] != completion_target:
                    raise BridgeError(
                        "completion_route_conflict", "Original return target is fixed"
                    )
                message_id = row["id"]
            else:
                message_id = getattr(message, "message_id", None) or str(uuid.uuid4())
                if self.store.db.execute(
                    "SELECT 1 FROM messages WHERE id=? UNION ALL "
                    "SELECT 1 FROM voice_message_buffers WHERE id=?",
                    (message_id, message_id),
                ).fetchone():
                    raise BridgeError("message_id_conflict", "Message ID is already reserved")
                body = (
                    message.body.rstrip()[: -len(SUFFIX)].rstrip()
                    if marked(message.body)
                    else message.body
                )
                if not body.strip():
                    raise BridgeError(
                        "invalid_arguments", "Message is empty after removing go-go-go"
                    )
                waiting = self.store.db.execute(
                    "SELECT count(*) FROM voice_message_buffers WHERE sender=? AND state='waiting'",
                    (principal,),
                ).fetchone()[0]
                if waiting >= self.channel.config.messaging.max_pending_per_recipient:
                    raise BridgeError("message_queue_full", "Voice outbox is full")
                total = self.store.db.execute(
                    "SELECT count(*) FROM voice_message_buffers"
                ).fetchone()[0]
                if total >= self.channel.config.messaging.max_total:
                    raise BridgeError("message_store_full", "Voice outbox capacity reached")
                now = time.time()
                changes = {"body": body}
                if transport == "message":
                    changes["message_id"] = message_id
                request = {
                    **message.model_copy(update=changes).model_dump(),
                    "_transport": transport,
                }
                self.store.db.execute(
                    "INSERT INTO voice_message_buffers VALUES(?,?,?,?,?,?,'waiting',?,?,NULL)",
                    (
                        message_id,
                        principal,
                        key,
                        hashed,
                        canonical(request),
                        completion_target,
                        now,
                        now + self.channel.config.voice_messaging.timeout_seconds,
                    ),
                )
                self.store.audit("message.buffered", principal, None, {"message_id": message_id})
            if row and row["state"] == "released":
                return self._released(principal, row)
            if not row and marked(message.body):
                return self.release(principal, message_id, SUFFIX)
        return self.get(principal, message_id)

    def release(self, principal, message_id, token):
        from kirabridge.message_manager import MessageSend

        self.channel.security.principal(principal)
        self.expire()
        if token != SUFFIX:
            raise BridgeError("invalid_release_token", "The exact go-go-go token is required")
        with self.store.transaction():
            row = self.store.db.execute(
                "SELECT * FROM voice_message_buffers WHERE id=? AND sender=?",
                (message_id, principal),
            ).fetchone()
            if not row:
                raise BridgeError("not_found", "Voice message buffer not found")
            if row["state"] == "expired" or (
                row["state"] == "waiting" and row["expires"] <= time.time()
            ):
                raise BridgeError("message_buffer_expired", "Voice message buffer expired")
            if row["state"] == "released":
                return self._released(principal, row)
            payload = json.loads(row["request"])
            transport = payload.pop("_transport", "message")
            if transport == "team":
                from kirabridge.team_manager.models import TeamMessageSend

                request = TeamMessageSend.model_validate(payload)
            else:
                request = MessageSend.model_validate(payload)
            self.store.db.execute(
                "UPDATE voice_message_buffers SET state='released',released=? WHERE id=?",
                (time.time(), message_id),
            )
            result = self._deliver(
                principal, request, row["completion_target"], transport, message_id=message_id
            )
            self.store.audit("message.released", principal, None, {"message_id": message_id})
        return result
