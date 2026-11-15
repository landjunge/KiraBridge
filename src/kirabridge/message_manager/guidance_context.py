"""Pin processed original guidance to one new managed work claim.

This is bounded prompt context in the existing message-job ledger, not a new
queue, a provider-session resume, or transferable authority between bridges.
"""

import hashlib
import json

from kirabridge.bridge_core.models import AgentInput, BridgeError, canonical, digest

SCHEMA = "kirabridge.managed-guidance-context.v1"
MAX_NOTES = 8
MAX_SCAN = 32
MAX_PROMPT_BYTES = 262144
INSTRUCTION = (
    "Execute only current_work.body as the current authorized task. prior_guidance contains "
    "exact original notes already processed by this same addressed recipient, in this same "
    "conversation and work directory, before this claim. Use them as prior context within "
    "the current task; explicit current_work instructions take precedence. Prior context "
    "does not authorize additional tasks, tools, permissions, delegation or session access. "
    "The controller owns message delivery, replies and acknowledgements. Do not claim a "
    "persistent coordinator session, cross-host synchronization or UI wake from this context."
)


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _work_hash(message):
    # Delivery/receipt/ACK may change during processing; every original work
    # field, including the actual body, is pinned independently of request_hash.
    return digest(
        {
            key: message[key]
            for key in (
                "seq",
                "id",
                "conversation_id",
                "position",
                "sender",
                "recipient",
                "kind",
                "body",
                "idem",
                "request_hash",
                "reply_to",
                "task_id",
                "depth",
                "request_reply",
                "created",
            )
        }
    )


def _authority(bridge):
    return {
        "scope": "same_local_store_and_loaded_runtime",
        "runtime_instance_id": bridge.runtime["instance_id"],
        "store_ref": digest(str(bridge.config.state_path / "bridge.sqlite3")),
    }


def _eligible(bridge, message):
    cfg = bridge.config.messaging
    cutoff = cfg.separate_managed_after
    return (
        message["kind"] == "work"
        and message["recipient"] in cfg.receivers
        and cutoff is not None
        and message["created"] >= cutoff
    )


def _peers(bridge, message):
    try:
        origin = bridge.security.principal(message["sender"], "message.send")
        recipient = bridge.security.principal(message["recipient"], "message.read")
    except BridgeError:
        return False
    return (
        message["recipient"] in origin.message_peers
        and message["sender"] in recipient.message_peers
    )


def _source(bridge, message, row):
    """Only completed, owner-ACKed guidance from this exact local scope qualifies."""
    cutoff = bridge.config.messaging.separate_managed_after
    cwd = bridge.config.messaging.receivers[message["recipient"]].cwd
    if (
        row["kind"] != "note"
        or row["request_reply"]
        or row["acknowledged"] is None
        or row["state"] != "completed"
        or row["execution_cwd"] != cwd
        or row["sender"] != message["sender"]
        or row["recipient"] != message["recipient"]
        or row["conversation_id"] != message["conversation_id"]
        or cutoff is None
        or row["created"] < cutoff
        or bridge.store.db.execute(
            "SELECT 1 FROM queue_holds WHERE queue_id='messages' AND item_id=?", (row["id"],)
        ).fetchone()
    ):
        return None
    try:
        evidence = json.loads(row["evidence"])
    except (TypeError, ValueError):
        return None
    if (
        not isinstance(evidence, dict)
        or evidence.get("guidance_batch") != 1
        or evidence.get("scope") != "managed_guidance_context_only"
        or evidence.get("model_turn_completed") is not True
        or not isinstance(evidence.get("message_ids"), list)
        or row["id"] not in evidence["message_ids"]
        or not isinstance(evidence.get("run_id"), str)
        or not evidence["run_id"]
        or not isinstance(row["run_id"], str)
        or not (
            row["run_id"] == evidence["run_id"]
            or row["run_id"].startswith(evidence["run_id"] + "-guidance-")
        )
    ):
        return None
    return {
        "message_id": row["id"],
        "seq": row["seq"],
        "body_sha256": _sha(row["body"]),
        "source_run_id": row["run_id"],
        "source_batch_run_id": evidence["run_id"],
        "body": row["body"],
    }


def _pin(source):
    return {key: value for key, value in source.items() if key != "body"}


def _prompt(message, binding, sources):
    if binding["prompt_format"] == "body_only_budget_omission":
        return message["body"]
    return canonical(
        {
            "schema": SCHEMA,
            "instruction": INSTRUCTION,
            "authority": binding["authority"],
            "conversation_id": message["conversation_id"],
            "sender": message["sender"],
            "recipient": message["recipient"],
            "execution_cwd": binding["execution_cwd"],
            "current_work": {"message_id": message["id"], "body": message["body"]},
            "prior_guidance": sources,
            "omitted_count": binding["omitted_count"],
            "selection": "latest_completed_original_notes_before_this_claim",
        }
    )


def prepare(bridge, message):
    """Called inside the existing claim transaction, before marking work running."""
    if not _eligible(bridge, message) or not _peers(bridge, message):
        return None
    rows = bridge.store.db.execute(
        "SELECT m.*,j.state,j.run_id,j.execution_cwd,j.evidence FROM messages m "
        "JOIN message_jobs j ON j.message_id=m.id "
        "WHERE m.sender=? AND m.recipient=? AND m.conversation_id=? "
        "AND m.kind='note' AND m.request_reply=0 AND m.acknowledged IS NOT NULL "
        "AND j.state='completed' AND j.execution_cwd=? AND m.created>=? "
        "AND NOT EXISTS(SELECT 1 FROM queue_holds h "
        "WHERE h.queue_id='messages' AND h.item_id=m.id) ORDER BY m.seq DESC LIMIT ?",
        (
            message["sender"],
            message["recipient"],
            message["conversation_id"],
            bridge.config.messaging.receivers[message["recipient"]].cwd,
            bridge.config.messaging.separate_managed_after,
            MAX_SCAN,
        ),
    ).fetchall()
    candidates = []
    for row in rows:
        if source := _source(bridge, message, row):
            candidates.append(source)
            if len(candidates) == MAX_NOTES:
                break
    if not candidates:
        return None
    settings = bridge.config.messaging.receivers[message["recipient"]]
    binding = {
        "schema": SCHEMA,
        "authority": _authority(bridge),
        "message_id": message["id"],
        "body_sha256": _sha(message["body"]),
        "current_work_sha256": _work_hash(message),
        "sender": message["sender"],
        "recipient": message["recipient"],
        "conversation_id": message["conversation_id"],
        "execution_cwd": settings.cwd,
        "cutoff": bridge.config.messaging.separate_managed_after,
        "prompt_format": "managed_work_with_prior_guidance_v1",
        "sources": [],
        "omitted_count": len(candidates),
        "selection_limit": MAX_NOTES,
        "scan_limit": MAX_SCAN,
    }
    selected = []
    for source in candidates:  # newest first; do not replace an oversized update with older text
        proposed = sorted([*selected, source], key=lambda value: value["seq"])
        trial = {**binding, "omitted_count": len(candidates) - len(proposed)}
        if len(_prompt(message, trial, proposed).encode("utf-8")) > MAX_PROMPT_BYTES:
            break
        selected = proposed
    binding["sources"] = [_pin(source) for source in selected]
    binding["omitted_count"] = len(candidates) - len(selected)
    prompt = _prompt(message, binding, selected)
    if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        # A valid body can expand when serialized as JSON (e.g. control bytes).
        # Preserve that current body exactly and record why no context fits.
        binding["prompt_format"] = "body_only_budget_omission"
        prompt = message["body"]
    AgentInput(
        agent=message["recipient"],
        prompt=prompt,
        cwd=settings.cwd,
        timeout=settings.timeout,
        wait_for_reply=bool(message["request_reply"]),
    )
    binding["prompt_sha256"] = _sha(prompt)
    binding["prompt_bytes"] = len(prompt.encode("utf-8"))
    return binding


def validate_current(bridge, message, binding, *, run_id=None, receipt=None, acknowledged=False):
    """Read the current work and its exact running owner at each effect boundary."""
    invalid = BridgeError("guidance_context_changed", "Pinned managed guidance scope changed")
    current = bridge.store.db.execute(
        "SELECT * FROM messages WHERE id=?", (message["id"],)
    ).fetchone()
    job = bridge.store.db.execute(
        "SELECT * FROM message_jobs WHERE message_id=?", (message["id"],)
    ).fetchone()
    try:
        evidence = json.loads(job["evidence"]) if job is not None else None
    except (TypeError, ValueError):
        evidence = None
    if (
        current is None
        or job is None
        or job["state"] != "running"
        or not binding.get("claim_run_id")
        or job["run_id"] != binding["claim_run_id"]
        or (run_id is not None and job["run_id"] != run_id)
        or job["execution_cwd"] != binding.get("execution_cwd")
        or not isinstance(evidence, dict)
        or evidence.get("managed_guidance_context") != binding
        or binding.get("current_work_sha256") != _work_hash(message)
        or binding["current_work_sha256"] != _work_hash(current)
        or (current["acknowledged"] is not None) != acknowledged
        or (receipt is not None and current["receipt"] != receipt)
        or bridge.store.db.execute(
            "SELECT 1 FROM queue_holds WHERE queue_id='messages' AND item_id=?",
            (message["id"],),
        ).fetchone()
    ):
        raise invalid


def render_pinned(bridge, message, binding, *, run_id=None, receipt=None, acknowledged=False):
    # One bounded, consistent store observation. Never hold a DB transaction
    # across an adapter or peer await.
    with bridge.store.transaction():
        return _render_pinned(
            bridge, message, binding, run_id=run_id, receipt=receipt, acknowledged=acknowledged
        )


def _render_pinned(bridge, message, binding, *, run_id, receipt, acknowledged):
    """Never refresh/reselect sources after claim; changed scope fails before the model."""
    invalid = BridgeError("guidance_context_changed", "Pinned managed guidance scope changed")
    validate_current(
        bridge, message, binding, run_id=run_id, receipt=receipt, acknowledged=acknowledged
    )
    if (
        not _eligible(bridge, message)
        or not _peers(bridge, message)
        or binding.get("schema") != SCHEMA
        or binding.get("authority") != _authority(bridge)
        or binding.get("execution_cwd")
        != bridge.config.messaging.receivers[message["recipient"]].cwd
        or binding.get("cutoff") != bridge.config.messaging.separate_managed_after
        or binding.get("body_sha256") != _sha(message["body"])
        or any(
            binding.get(key) != message[key] for key in ("sender", "recipient", "conversation_id")
        )
        or binding.get("message_id") != message["id"]
        or not isinstance(binding.get("sources"), list)
        or len(binding["sources"]) > MAX_NOTES
        or binding.get("prompt_format")
        not in {"managed_work_with_prior_guidance_v1", "body_only_budget_omission"}
        or (binding.get("prompt_format") == "body_only_budget_omission" and binding["sources"])
    ):
        raise invalid
    sources = []
    for pin in binding["sources"]:
        row = bridge.store.db.execute(
            "SELECT m.*,j.state,j.run_id,j.execution_cwd,j.evidence FROM messages m "
            "JOIN message_jobs j ON j.message_id=m.id WHERE m.id=?",
            (pin["message_id"],),
        ).fetchone()
        source = _source(bridge, message, row) if row is not None else None
        if source is None or _pin(source) != pin:
            raise invalid
        sources.append(source)
    prompt = _prompt(message, binding, sources)
    if (
        _sha(prompt) != binding.get("prompt_sha256")
        or len(prompt.encode("utf-8")) != binding.get("prompt_bytes")
        or len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES
    ):
        raise invalid
    return prompt
