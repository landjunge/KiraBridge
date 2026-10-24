"""Bounded, participant-only handoff evidence. Reads never reconcile or resend."""

from __future__ import annotations

import json
import math
import sqlite3

STATES = frozenset(
    {
        "planned",
        "inserting",
        "inserted",
        "submitting",
        "return_sent",
        "sent",
        "confirmed",
        "completed",
        "interrupted",
        "unknown",
    }
)
REASONS = frozenset(
    {
        "visible_insert_unknown",
        "visible_submit_unknown",
        "visible_handoff_unknown",
        "target_idle_reply_unconfirmed",
        "reply_unconfirmed",
        "interrupted",
        "preinput_error",
        "desktop_locked",
        "desktop_session_inactive",
        "visible_target_changed",
        "visible_target_busy",
        "visible_input_not_empty",
        "visible_target_scrolled",
        "visible_target_unknown",
        "visible_target_working",
    }
)
EVENT_LIMIT = 32
EVIDENCE_LIMIT = 8192


def _state(value):
    return value if isinstance(value, str) and value in STATES else "unknown"


def _time(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def visible_message_evidence(
    db: sqlite3.Connection, principal: str, message_id: str, run_id: str | None
) -> dict | None:
    """Caller must already enforce message.read and task.read; no raw payloads.

    The joins independently bind the handoff to the exact addressed message and
    participant. Shared conversation membership alone does not grant access.
    Evidence is historical, not an atomic snapshot or proof of current UI state.
    """
    if not run_id:
        return None
    tables = {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('visible_handoffs','visible_handoff_events')"
        )
    }
    if "visible_handoffs" not in tables:
        return None
    row = db.execute(
        "SELECT h.id,h.state,h.updated,substr(CAST(h.evidence AS BLOB),1,?) "
        "FROM visible_handoffs h JOIN messages m ON m.id=h.message_id "
        "WHERE h.id=? AND h.message_id=? AND h.principal=m.sender "
        "AND h.target=m.recipient AND (h.principal=? OR h.target=?)",
        (EVIDENCE_LIMIT + 1, run_id, message_id, principal, principal),
    ).fetchone()
    if row is None:
        return None
    raw = row[3]
    evidence_status = "available"
    if not isinstance(raw, bytes) or len(raw) > EVIDENCE_LIMIT:
        evidence, evidence_status = {}, "unavailable_or_over_limit"
    else:
        try:
            evidence = json.loads(raw)
            if not isinstance(evidence, dict):
                evidence, evidence_status = {}, "invalid"
        except (ValueError, UnicodeError, RecursionError):
            evidence, evidence_status = {}, "invalid"
    reason = evidence.get("reason")
    if reason is None:
        reason = "not_recorded" if evidence_status == "available" else "unavailable"
    elif not isinstance(reason, str) or reason not in REASONS:
        reason = "other_recorded_reason"
    events = []
    history_available = "visible_handoff_events" in tables
    if history_available:
        events = db.execute(
            "SELECT seq,state,at FROM visible_handoff_events WHERE id=? ORDER BY seq DESC LIMIT ?",
            (run_id, EVENT_LIMIT + 1),
        ).fetchall()
    history_truncated = len(events) > EVENT_LIMIT
    events = events[:EVENT_LIMIT]
    return {
        "scope": "stored_handoff_evidence_not_live_terminal",
        "handoff_id": row[0],
        "state": _state(row[1]),
        "updated": _time(row[2]),
        "recorded_reason": reason,
        "evidence_status": evidence_status,
        "history_available": history_available,
        "history_truncated": history_truncated,
        "events": [
            {
                "seq": event[0] if type(event[0]) is int else None,
                "state": _state(event[1]),
                "at": _time(event[2]),
            }
            for event in reversed(events)
        ],
        "automatic_retry_permitted": False,
        "reconciliation_performed": False,
        "next_step": "inspect_original_handoff_without_repeating_input",
    }
