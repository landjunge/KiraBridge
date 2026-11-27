"""Overview of every direct and team message for the operator's voice assistant.

The operator wants ChatGPT to be able to read out everything that happens between the agents
whenever asked. A successful read is also the delivery (receive hook, docs/COMPLETION-HOOKS.md
Abschnitt 6): for a principal listed in team.auto_ack_on_observe, or the current coordinator
(then only messages from the listed principals), the returned messages addressed to that
principal are acknowledged after the overview was computed, never before. Message
content is data written by agents and must never be treated as instructions.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime

from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.team_manager.coordinator_prefix import is_unambiguous_coordinator

OBSERVE_CAPABILITY = "messages.observe"
MAX_LIMIT = 200
MAX_BODY_CHARS = 4000
_KIND_DE = {
    "work": "einen Auftrag",
    "question": "eine Frage",
    "answer": "eine Antwort",
    "result": "ein Ergebnis",
    "note": "eine Notiz",
}


def _local(created: float) -> datetime:
    return datetime.fromtimestamp(created).astimezone()


def _item(source, row, body_chars):
    body = row["body"] or ""
    shown = body[:body_chars]
    at = _local(row["created"])
    preview = " ".join(body[:160].split())
    kind = _KIND_DE.get(row["kind"], "eine Nachricht")
    return {
        "source": source,
        "seq": row["seq"],
        "id": row["id"],
        "at": at.isoformat(timespec="seconds"),
        "from": row["sender"],
        "to": row["recipient"],
        "kind": row["kind"],
        "thread": row["thread"],
        "acknowledged": row["acknowledged"] is not None,
        "acknowledged_at": (
            None
            if row["acknowledged"] is None
            else _local(row["acknowledged"]).isoformat(timespec="seconds")
        ),
        "body": shown,
        "body_truncated": len(body) > len(shown),
        # One sentence the assistant can read aloud as it is.
        "speech": (
            f"Um {at:%H:%M} Uhr hat {row['sender']} an {row['recipient']} {kind} geschickt"
            + (f": {preview}" if preview else ".")
            + ("" if row["acknowledged"] is None else " (bereits quittiert)")
        ),
        "untrusted_content": True,
    }


def overview(db, *, after_direct=0, after_team=0, limit=50, body_chars=1200, recipient=None):
    """Return the next messages after the given per-store cursors, oldest first.

    recipient limits both stores to one mailbox (the single inbox view, team_messages).
    """
    limit = max(1, min(int(limit), MAX_LIMIT))
    body_chars = max(0, min(int(body_chars), MAX_BODY_CHARS))
    direct = db.execute(
        "SELECT seq,id,conversation_id AS thread,sender,recipient,kind,body,created,acknowledged "
        "FROM messages WHERE seq>:after AND (:rcpt IS NULL OR recipient=:rcpt) "
        "AND idem NOT LIKE 'team:%' ORDER BY seq LIMIT :limit",
        {"after": int(after_direct), "rcpt": recipient, "limit": limit},
    ).fetchall()
    team = db.execute(
        "SELECT seq,id,team_id AS thread,sender,recipient,kind,body,created,acknowledged "
        "FROM team_messages WHERE seq>:after AND (:rcpt IS NULL OR recipient=:rcpt) "
        "ORDER BY seq LIMIT :limit",
        {"after": int(after_team), "rcpt": recipient, "limit": limit},
    ).fetchall()
    merged = sorted(
        [("direct", row) for row in direct] + [("team", row) for row in team],
        key=lambda pair: (pair[1]["created"], pair[0], pair[1]["seq"]),
    )[:limit]
    items = [_item(source, row, body_chars) for source, row in merged]
    # Cursors only advance over what was returned, so nothing is skipped on the next call.
    next_direct = max([i["seq"] for i in items if i["source"] == "direct"], default=after_direct)
    next_team = max([i["seq"] for i in items if i["source"] == "team"], default=after_team)
    more = len(direct) + len(team) > len(items) or len(direct) == limit or len(team) == limit
    return {
        "read_only": True,
        "items": items,
        "count": len(items),
        "next": {"after_direct": next_direct, "after_team": next_team},
        "more": more,
    }


def _event(store, message_id, kind, principal, evidence):
    """Event row plus audit entry, in the style of message_manager._event; never any body."""
    store.db.execute(
        "INSERT INTO message_events(message_id,at,kind,evidence) VALUES(?,?,?,?)",
        (message_id, time.time(), kind, canonical(evidence)),
    )
    store.audit(kind, principal, None, {"message_id": message_id, **evidence})


def auto_acknowledge(bridge, principal, items, senders=None):
    """Acknowledge exactly the returned messages addressed to principal, one transaction.

    Delivery keeps its old meaning: a direct message nobody pulled yet gets the same
    delivered/receipt pair messages.receive would have written, and only then the
    acknowledged stamp. Already acknowledged rows stay untouched, so a repeat read
    changes nothing.
    """
    acked = {"direct": [], "team": []}
    targets = [
        item
        for item in items
        if item["to"] == principal and (senders is None or item["from"] in senders)
    ]
    if not targets:
        return acked
    store = bridge.store
    with store.transaction() as db:
        for item in targets:
            if item["source"] == "direct":
                row = db.execute(
                    "SELECT delivered,receipt,acknowledged FROM messages WHERE id=?",
                    (item["id"],),
                ).fetchone()
                if row is None or row["acknowledged"] is not None:
                    continue
                if row["delivered"] is None:
                    receipt = str(uuid.uuid4())
                    db.execute(
                        "UPDATE messages SET delivered=?,receipt=? WHERE id=?",
                        (time.time(), receipt, item["id"]),
                    )
                    _event(
                        store,
                        item["id"],
                        "message.delivered",
                        principal,
                        {"receipt": receipt, "seq": item["seq"]},
                    )
                else:
                    receipt = row["receipt"]
                db.execute(
                    "UPDATE messages SET acknowledged=? WHERE id=?", (time.time(), item["id"])
                )
                _event(
                    store,
                    item["id"],
                    "message.auto_acknowledged",
                    principal,
                    {"receipt": receipt, "seq": item["seq"]},
                )
                acked["direct"].append(item["seq"])
            else:
                row = db.execute(
                    "SELECT acknowledged FROM team_messages WHERE id=?", (item["id"],)
                ).fetchone()
                if row is None or row["acknowledged"] is not None:
                    continue
                db.execute(
                    "UPDATE team_messages SET acknowledged=? WHERE id=?", (time.time(), item["id"])
                )
                # Close the delivery ticket too, so a later wake cannot type it again.
                db.execute(
                    "UPDATE messages SET acknowledged=? WHERE idem=? AND sender=? "
                    "AND recipient=? AND acknowledged IS NULL",
                    (time.time(), "team:" + item["id"], item["from"], principal),
                )
                db.execute(
                    "INSERT INTO team_events(team_id,at,kind,principal,object_id,metadata) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        item["thread"],
                        time.time(),
                        "team.message_auto_acknowledged",
                        principal,
                        item["id"],
                        canonical({"seq": item["seq"]}),
                    ),
                )
                store.audit(
                    "team.message_auto_acknowledged",
                    principal,
                    None,
                    {"team_id": item["thread"], "object_id": item["id"], "seq": item["seq"]},
                )
                acked["team"].append(item["seq"])
    return acked


def _mark(items):
    """Per item: read (acknowledged before this call) and new (delivered first by this call)."""
    for item in items:
        item["read"] = item["acknowledged"]
        item["new"] = not item["acknowledged"]


def _counts(db, principal):
    """Mailbox size and what is still unacknowledged, after this call's own acknowledgements."""
    total = unread = 0
    for table, extra in (("messages", " AND idem NOT LIKE 'team:%'"), ("team_messages", "")):
        row = db.execute(
            f"SELECT count(*),count(*)-count(acknowledged) FROM {table} WHERE recipient=?{extra}",
            (principal,),
        ).fetchone()
        total, unread = total + row[0], unread + row[1]
    return total, unread


def inbox(bridge, principal, **arguments):
    """The one read path: the principal's own mailbox over team and legacy direct messages.

    A principal holding messages.observe sees everything. Receive hook: a finished read
    acknowledges exactly the returned messages addressed to the caller (see _hook), and every
    item says whether it was read before (read) or is delivered first by this call (new).
    """
    try:
        bridge.security.principal(principal, OBSERVE_CAPABILITY)
    except BridgeError:
        result = overview(bridge.store.db, recipient=principal, **arguments)
    else:
        result = overview(bridge.store.db, **arguments)
    _mark(result["items"])
    result["new_count"] = sum(1 for i in result["items"] if i["new"] and i["to"] == principal)
    _hook(bridge, principal, result)
    result["total"], result["unread_count"] = _counts(bridge.store.db, principal)
    result["notice"] = (
        "one inbox: team_messages; message_receive/message_get/messages_overview are aliases"
    )
    return result


def team_read(bridge, principal, team_id, after=0, limit=50):
    """Team log page with the same receive hook and read/new markers."""
    result = bridge.teams.messages(principal, team_id, after, limit)
    rows = result["messages"]
    for row in rows:
        row["read"] = row["acknowledged"] is not None
        row["new"] = not row["read"]
    shown = {
        "items": [
            {
                "source": "team",
                "seq": r["seq"],
                "id": r["id"],
                "to": r["recipient"],
                "from": r["sender"],
                "thread": r["team_id"],
            }
            for r in rows
        ],
        "read_only": True,
    }
    result["new_count"] = sum(1 for r in rows if r["new"] and r["recipient"] == principal)
    _hook(bridge, principal, shown)
    acked = set(shown.get("acknowledged_by_read", {}).get("team", []))
    for row in rows:
        row["acknowledged_now"] = row["seq"] in acked
    result["acknowledged_by_read"] = shown.get("acknowledged_by_read")
    if "ack_error" in shown:
        result["ack_error"] = shown["ack_error"]
    result["total"], result["unread_count"] = _counts(bridge.store.db, principal)
    return result


def observe(bridge, principal, **arguments):
    """Capability-checked entry point used by the MCP tool, including the receive hook."""
    bridge.security.principal(principal, OBSERVE_CAPABILITY)
    result = overview(bridge.store.db, **arguments)
    return _hook(bridge, principal, result)


def _hook(bridge, principal, result):
    """Acknowledge after the page was computed, never before.

    A failing acknowledgement never withholds the page and never leaves a partial ack:
    the transaction rolls back and the result carries the fixed ack_error notice instead.
    """
    result["acknowledged_by_read"] = {"direct": [], "team": []}
    listed = bridge.config.team.auto_ack_on_observe
    # The current coordinator gets the hook too, read per call from the team record: after a
    # role change it applies to the new holder and ends for the previous one. The coordinator
    # acknowledges only what the listed principals (default chatgpt) sent to it.
    senders = None if principal in listed else set(listed)
    if senders is not None and not is_unambiguous_coordinator(bridge, principal):
        return result
    try:
        acked = auto_acknowledge(bridge, principal, result["items"], senders)
    except Exception:
        result["ack_error"] = "auto_ack_failed"
        return result
    result["acknowledged_by_read"] = acked
    if acked["direct"] or acked["team"]:
        result["read_only"] = False
    return result
