"""Bounded guidance intake for explicitly registered managed receivers only."""

import time

from kirabridge.bridge_core.models import AgentInput, BridgeError, canonical, digest
from kirabridge.message_manager.receiver import separate_managed_eligible


def _payload(rows):
    return {
        "managed_guidance_batch": 1,
        "instruction": "Read these original guidance notes as context at this safe boundary. "
        "Summarize the accepted priorities and unresolved limits briefly. Do not execute old "
        "work, send messages, call Apps/tools/network, delegate, change services or claim UI "
        "wake. The controller owns delivery and ACK. Notes request no automatic reply.",
        "messages": [
            {k: row[k] for k in ("id", "sender", "recipient", "conversation_id", "body")}
            for row in rows
        ],
    }


def ready(receiver, recipient):
    cfg = receiver.bridge.config
    if recipient not in cfg.messaging.receivers or cfg.messaging.separate_managed_after is None:
        return False
    return (
        receiver.bridge.store.db.execute(
            "SELECT 1 FROM messages m WHERE recipient=? AND kind='note' AND request_reply=0 "
            "AND acknowledged IS NULL AND created>=? "
            "AND NOT EXISTS(SELECT 1 FROM message_jobs j WHERE j.message_id=m.id) "
            "AND NOT EXISTS(SELECT 1 FROM queue_holds h "
            "WHERE h.queue_id='messages' AND h.item_id=m.id) LIMIT 1",
            (recipient, cfg.messaging.separate_managed_after),
        ).fetchone()
        is not None
    )


async def consume(receiver, recipient, pool):
    bridge, store = receiver.bridge, receiver.bridge.store
    cfg = bridge.config
    if recipient not in cfg.messaging.receivers or cfg.messaging.separate_managed_after is None:
        return False
    # This function runs under the existing recipient turn lock. Also respect
    # separately submitted native work; never steer/interrupt an active turn.
    if (
        store.db.execute(
            "SELECT 1 FROM message_jobs j JOIN messages m ON m.id=j.message_id "
            "WHERE m.recipient=? AND j.state='running'",
            (recipient,),
        ).fetchone()
        or store.db.execute(
            "SELECT 1 FROM tasks WHERE agent=? "
            "AND state IN ('created','queued','accepted','running')",
            (recipient,),
        ).fetchone()
    ):
        return False
    rows = store.db.execute(
        "SELECT m.* FROM messages m WHERE m.recipient=? AND m.kind='note' "
        "AND m.request_reply=0 AND m.acknowledged IS NULL AND m.created>=? "
        "AND NOT EXISTS(SELECT 1 FROM message_jobs j WHERE j.message_id=m.id) "
        "AND NOT EXISTS(SELECT 1 FROM queue_holds h "
        "WHERE h.queue_id='messages' AND h.item_id=m.id) "
        "ORDER BY m.seq LIMIT 8",
        (recipient, cfg.messaging.separate_managed_after),
    ).fetchall()
    if not rows:
        return False
    # Batch only one authenticated origin/conversation; preserve normal peer and
    # voice-channel isolation rather than mixing unrelated instructions.
    first = rows[0]
    rows = [
        dict(r)
        for r in rows
        if r["sender"] == first["sender"] and r["conversation_id"] == first["conversation_id"]
    ]
    policy = bridge.security.principal(recipient, "message.read")
    from kirabridge.permissions import decision

    bridge.security.principal(recipient, "agent.execute")
    origin = bridge.security.principal(first["sender"], "message.send")
    if not decision(cfg, recipient, "agent.execute")["automatic"]:
        return False
    if recipient not in origin.message_peers:
        return False
    if first["sender"] not in policy.message_peers:
        return False
    for row in rows:
        if not separate_managed_eligible(cfg, row["created"]):
            return False
        receiver.messages._row(recipient, row["id"])
    # Validate the complete serialized envelope, not just individual note
    # lengths, before reservation or delivery. Remaining notes stay pending.
    settings = cfg.messaging.receivers[recipient]
    selected, prepared = [], None
    for row in rows:
        prompt = canonical(_payload([*selected, row]))
        if len(prompt.encode("utf-8")) > 262144:
            break
        prepared = AgentInput(
            agent=recipient,
            prompt=prompt,
            cwd=settings.cwd,
            timeout=settings.timeout,
            wait_for_reply=True,
        )
        selected.append(row)
    if prepared is None:
        return False
    rows = selected
    with store.transaction():
        # Existing job reservation is the sole deduplication ledger. UNKNOWNs
        # already have a row and never enter this query or get redispatched.
        for row in rows:
            if store.db.execute(
                "SELECT 1 FROM message_jobs WHERE message_id=?", (row["id"],)
            ).fetchone():
                return False
        if not store.can_claim(first["created"]):
            return False
        store.db.execute(
            "INSERT INTO message_jobs(message_id,state) VALUES(?,'queued')", (first["id"],)
        )
        claimed = receiver._claim(first["id"])
        if not claimed:
            # _claim may retain a quota/stale blocked outcome. Only retract our
            # own never-claimed queued reservation on transient denial, so it
            # cannot escape to the ordinary raw-work dispatcher.
            store.db.execute(
                "DELETE FROM message_jobs WHERE message_id=? AND state='queued' "
                "AND run_id IS NULL AND claimed IS NULL AND started IS NULL",
                (first["id"],),
            )
            return False
        _, run_id = claimed
        for n, row in enumerate(rows[1:], 1):
            store.db.execute(
                "INSERT INTO message_jobs(message_id,state,run_id,execution_cwd) "
                "VALUES(?,'running',?,?)",
                (row["id"], run_id + "-guidance-" + str(n), cfg.messaging.receivers[recipient].cwd),
            )
    ids = [r["id"] for r in rows]
    evidence = {
        "guidance_batch": 1,
        "message_ids": ids,
        "run_id": run_id,
        "scope": "managed_guidance_context_only",
        "automatic_retry": False,
    }

    async def call(tool, args):
        result = await pool.call("daemon", tool, args)
        if (
            result.isError
            or not isinstance(result.structuredContent, dict)
            or result.structuredContent.get("error")
        ):
            raise BridgeError("guidance_protocol", "Bound recipient call rejected")
        return result.structuredContent

    async def progress(value):
        with store.transaction():
            for row in rows:
                store.db.execute(
                    "UPDATE message_jobs SET evidence=? WHERE message_id=?",
                    (canonical({**evidence, "native": value}), row["id"]),
                )

    async def running(value):
        with store.transaction():
            for row in rows:
                store.db.execute(
                    "UPDATE message_jobs SET started=COALESCE(started,?) WHERE message_id=?",
                    (time.time(), row["id"]),
                )
        await progress(value)

    try:
        receipts = {}
        for row in rows:
            delivered = await call(
                "message_receive",
                {"after": row["seq"] - 1, "limit": 1, "conversation_id": row["conversation_id"]},
            )
            item = delivered["messages"][0] if delivered["messages"] else None
            if not item or item["id"] != row["id"]:
                raise BridgeError("guidance_delivery", "Original guidance delivery changed")
            receipts[row["id"]] = item["receipt"]
        result = await bridge.agents.execute(
            {"id": run_id, "principal": recipient},
            prepared,
            policy,
            running,
            progress,
            separate_managed=True,
        )
        if (
            not result.get("success")
            or not isinstance(result.get("text"), str)
            or not result["text"].strip()
        ):
            raise BridgeError("guidance_unconfirmed", "Guidance processing was not confirmed")
        completed = {
            **evidence,
            "model_turn_completed": True,
            "native": result.get("evidence", {}),
            "processing_summary": result["text"][:8192],
            "processing_summary_sha256": digest(result["text"]),
            "request_reply_satisfied": False,
        }
        # The actual addressed recipient acknowledges only after successful
        # model processing. No reply is manufactured for request_reply=false.
        for row in rows:
            await call("message_ack", {"message_id": row["id"], "receipt": receipts[row["id"]]})
            with store.transaction():
                receiver._finish(row["id"], "completed", completed)
        return True
    except BaseException:
        with store.transaction():
            for row in rows:
                job = store.db.execute(
                    "SELECT state FROM message_jobs WHERE message_id=?", (row["id"],)
                ).fetchone()
                if job and job["state"] == "running":
                    receiver._finish(row["id"], "unknown", evidence, "guidance_processing_unknown")
        raise
