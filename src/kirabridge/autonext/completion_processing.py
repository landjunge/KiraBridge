"""Opt-in accepted-result consumer on the existing AutoNext/Completion ledgers.

This is a processing receipt, not another queue. The manager owns its lifecycle;
the claim transaction revalidates the original binding instead of trusting a wakeup.
"""

import hashlib
import json
import time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kirabridge.autonext.models import ID, SHA, ReadyCard
from kirabridge.bridge_core.models import BridgeError, canonical, digest
from kirabridge.team_manager.dispatcher import parse_team_turn
from kirabridge.whiteboard_read import read_whiteboard

Hash = Annotated[str, Field(pattern=SHA)]
Identifier = Annotated[str, Field(min_length=1, max_length=128)]

SCHEMA = """
CREATE TABLE IF NOT EXISTS autonext_processed_completions (
 task_id TEXT PRIMARY KEY REFERENCES autonext_items(task_id),
 grant_id TEXT NOT NULL, notice_id TEXT UNIQUE NOT NULL, record TEXT NOT NULL
)
"""


def text_sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AcceptedIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1] = 1
    principal: Literal["codex"]
    target: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    grant_id: str = Field(pattern=ID)
    team_id: Identifier
    team_revision: int = Field(ge=0)
    board_id: Identifier
    task_id: str = Field(pattern=ID)
    work_id: Identifier
    core_task_id: Identifier
    core_request_sha256: Hash
    core_attempt: Literal[1]
    core_receipt_sha256: Hash
    core_result_sha256: Hash
    source_sha256: Hash
    acceptance_receipt_sha256: Hash
    result_sha256: Hash


class ProcessedCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    identity: AcceptedIdentity
    notice_id: Identifier
    outbox_key: Identifier
    content_sha256: Hash
    payload_sha256: Hash
    notice_receipt_sha256: Hash
    acknowledged: float = Field(gt=0)
    processed_at: float = Field(gt=0)


class AcceptedCompletionConsumer:
    def __init__(self, manager):
        self.manager = manager
        self.store = manager.store
        self.pending = {}
        with self.store.transaction():
            self.store.db.execute(SCHEMA)

    def identity(self, item):
        m, settings = self.manager, self.manager.settings
        receipt = json.loads(item["receipt"] or "null")
        approved = next((p for p in settings.cards if p.task_id == item["task_id"]), None)
        card = ReadyCard.model_validate_json(item["card"])
        if (
            item["state"] != "completed"
            or item["grant_id"] != settings.grant_id
            or approved is None
            or approved.content_sha256 != item["source_ref"]
            or m._card(approved) != card
            or not isinstance(receipt, dict)
        ):
            raise BridgeError("autonext_completion_unconfirmed", "Accepted source is unproven")
        work = m.bridge.teams.work_get(settings.principal, settings.team_id, item["work_id"])
        team = m.bridge.teams.get(settings.principal, settings.team_id)
        if team["revision"] != settings.team_revision:
            raise BridgeError("autonext_identity_changed", "Accepted team revision differs")
        core = m._core_proof(item, work)
        native = core.get("result") or {}
        final = native.get("final_message", native.get("text", ""))
        worker = m.bridge.config.team.workers["codex"]
        turn = parse_team_turn(
            final, max_bytes=m.bridge.config.team.max_result_bytes, framing=worker.response_framing
        )
        if (
            work["state"] != "completed"
            or work["assignee"] != "codex"
            or core["id"] != "team-" + work["id"]
            or core["principal"] != "codex"
            or core["operation"] != "agent.execute"
            or core["args"].get("agent") != "codex"
            or core["attempt"] != 1
            or not core.get("receipt")
            or core.get("error") is not None
            or turn.actions
            or turn.result != work["result"]
            or work["evidence"].get("actions") != []
            or any(
                receipt.get(key) != value
                for key, value in {
                    "task_id": item["task_id"],
                    "work_id": work["id"],
                    "core_task_id": core["id"],
                    "source_sha256": item["source_ref"],
                    "result_sha256": text_sha(work["result"]),
                    "acceptance": card.acceptance.kind,
                }.items()
            )
        ):
            raise BridgeError("autonext_completion_unconfirmed", "Original accepted result differs")
        return AcceptedIdentity(
            principal=settings.principal,
            target=settings.completion_target,
            grant_id=settings.grant_id,
            team_id=settings.team_id,
            team_revision=settings.team_revision,
            board_id=settings.board_id,
            task_id=item["task_id"],
            work_id=work["id"],
            core_task_id=core["id"],
            core_request_sha256=core["request_sha256"],
            core_attempt=core["attempt"],
            core_receipt_sha256=text_sha(core["receipt"]),
            core_result_sha256=digest(native),
            source_sha256=item["source_ref"],
            acceptance_receipt_sha256=digest(receipt),
            result_sha256=text_sha(work["result"]),
        )

    def candidate(self, item):
        identity = self.identity(item)
        key = "autonext-" + digest([identity.grant_id, identity.task_id, "completed"])[:48]
        outbox = self.store.db.execute(
            "SELECT rowid AS event_seq,* FROM autonext_outbox WHERE key=?", (key,)
        ).fetchone()
        if outbox is None or not outbox["verified"] or not outbox["entry_id"]:
            return None
        expected_content = canonical(
            {
                "autonext": 1,
                "task_id": identity.task_id,
                "grant_id": identity.grant_id,
                "phase": "completed",
                "receipt_sha256": identity.acceptance_receipt_sha256,
                "result_sha256": identity.result_sha256,
                "completion_binding_sha256": digest(identity.model_dump()),
            }
        )
        if (
            outbox["grant_id"] != identity.grant_id
            or outbox["task_id"] != identity.task_id
            or outbox["phase"] != "completed"
            or outbox["content"] != expected_content
        ):
            return None
        published = read_whiteboard(
            self.manager._workspace("threaddesk.read"), identity.board_id, outbox["entry_id"]
        )["entry"]
        if published["truncated"] or published["content"] != expected_content:
            return None
        refs = {
            "autonext_outbox_key": key,
            "content_sha256": text_sha(expected_content),
            "receipt_sha256": identity.acceptance_receipt_sha256,
            "result_sha256": identity.result_sha256,
            "completion_binding_sha256": digest(identity.model_dump()),
        }
        payload = {
            "source": "autonext",
            "task_id": identity.task_id,
            "grant_id": identity.grant_id,
            "team_id": identity.team_id,
            "phase": "completed",
            "state": "completed",
            "outcome": "success",
            "completion_scope": "accepted_autonext_task",
            "agent_work_completion_verified": True,
            "project_completion_verified": False,
            "chat_completion_verified": False,
            "automatic_retry": False,
            "event_seq": outbox["event_seq"],
            "evidence_refs": refs,
        }
        notice = self.store.db.execute(
            "SELECT * FROM completion_notices WHERE source='autonext' AND event_seq=?",
            (outbox["event_seq"],),
        ).fetchone()
        if (
            notice is None
            or notice["id"] != f"completion-autonext-{outbox['event_seq']}"
            or notice["principal"] != identity.principal
            or notice["target"] != identity.target
            or notice["source_id"] != identity.task_id
            or json.loads(notice["payload"]) != payload
            or self.store.db.execute(
                "SELECT 1 FROM queue_holds WHERE queue_id='completions' AND item_id=?",
                (notice["id"],),
            ).fetchone()
        ):
            return None
        return identity, outbox, notice

    @staticmethod
    def matches(record, candidate):
        identity, outbox, notice = candidate
        return (
            record.identity == identity
            and record.notice_id == notice["id"]
            and record.outbox_key == outbox["key"]
            and record.content_sha256 == text_sha(outbox["content"])
            and record.payload_sha256 == digest(json.loads(notice["payload"]))
            and bool(notice["receipt"])
            and record.notice_receipt_sha256 == text_sha(notice["receipt"])
            and record.acknowledged == notice["acknowledged"]
        )

    def items(self):
        return self.store.db.execute(
            "SELECT * FROM autonext_items WHERE grant_id=? ORDER BY rowid",
            (self.manager.settings.grant_id,),
        ).fetchall()

    def process(self):
        self.pending = {}
        for item in self.items():
            if item["state"] != "completed":
                continue
            try:
                with self.store.transaction():
                    candidate = self.candidate(item)
                    if candidate is None:
                        raise ValueError("Unconfirmed original completion")
                    identity, outbox, notice = candidate
                    old = self.store.db.execute(
                        "SELECT * FROM autonext_processed_completions WHERE task_id=?",
                        (item["task_id"],),
                    ).fetchone()
                    if old:
                        record = ProcessedCompletion.model_validate_json(old["record"])
                        if old["grant_id"] != identity.grant_id or not self.matches(
                            record, candidate
                        ):
                            raise ValueError("Processing receipt differs")
                        continue
                    delivered = None
                    if notice["acknowledged"] is not None and notice["receipt"]:
                        # An already processed exact original is idempotent, including
                        # an ACK committed by its owner before this consumer restarted.
                        delivered = {
                            "id": notice["id"],
                            "receipt": notice["receipt"],
                            "payload": json.loads(notice["payload"]),
                        }
                    else:
                        received = self.manager.bridge.completions.receive(
                            identity.principal,
                            identity.target,
                            limit=50,
                            source_id=identity.task_id,
                        )
                        delivered = next(
                            (n for n in received["notices"] if n["id"] == notice["id"]), None
                        )
                    if delivered is None:
                        raise ValueError("Original completion not delivered to this consumer")
                    ack = self.manager.bridge.completions.ack(
                        identity.principal, delivered["id"], delivered["receipt"]
                    )
                    record = ProcessedCompletion(
                        identity=identity,
                        notice_id=notice["id"],
                        outbox_key=outbox["key"],
                        content_sha256=text_sha(outbox["content"]),
                        payload_sha256=digest(delivered["payload"]),
                        notice_receipt_sha256=text_sha(delivered["receipt"]),
                        acknowledged=ack["acknowledged"],
                        processed_at=time.time(),
                    )
                    self.store.db.execute(
                        "INSERT INTO autonext_processed_completions VALUES(?,?,?,?)",
                        (
                            identity.task_id,
                            identity.grant_id,
                            notice["id"],
                            canonical(record.model_dump()),
                        ),
                    )
                    self.store.audit(
                        "autonext.completion_processed",
                        identity.principal,
                        identity.core_task_id,
                        {
                            "task_id": identity.task_id,
                            "binding_sha256": digest(record.model_dump()),
                        },
                    )
            except (BridgeError, ValueError, TypeError, KeyError, ValidationError):
                self.pending[item["task_id"]] = "original_completion_unconfirmed"

    def barrier(self):
        """Read only; caller owns the claim's BEGIN IMMEDIATE transaction."""
        predecessor = None
        for item in self.items():
            try:
                if item["state"] != "completed":
                    return False, None
                candidate = self.candidate(item)
                row = self.store.db.execute(
                    "SELECT * FROM autonext_processed_completions WHERE task_id=?",
                    (item["task_id"],),
                ).fetchone()
                if candidate is None or row is None or row["grant_id"] != item["grant_id"]:
                    self.pending[item["task_id"]] = "original_completion_unconfirmed"
                    return False, None
                record = ProcessedCompletion.model_validate_json(row["record"])
                if not self.matches(record, candidate):
                    self.pending[item["task_id"]] = "original_completion_unconfirmed"
                    return False, None
                predecessor = {
                    "task_id": item["task_id"],
                    "notice_id": record.notice_id,
                    "binding_sha256": digest(record.model_dump()),
                    "acknowledged": record.acknowledged,
                }
            except (BridgeError, ValueError, TypeError, KeyError, ValidationError):
                self.pending[item["task_id"]] = "original_completion_unconfirmed"
                return False, None
        return True, predecessor
