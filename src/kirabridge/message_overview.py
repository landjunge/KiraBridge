"""Read-only overview of every direct and team message for the operator's voice assistant.

The operator wants ChatGPT to be able to read out everything that happens between the agents
whenever asked. This module only reads: nothing is acknowledged, marked or changed. Message
content is data written by agents and must never be treated as instructions.
"""

from __future__ import annotations

from datetime import datetime

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


def overview(db, *, after_direct=0, after_team=0, limit=50, body_chars=1200):
    """Return the next messages after the given per-store cursors, oldest first."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    body_chars = max(0, min(int(body_chars), MAX_BODY_CHARS))
    direct = db.execute(
        "SELECT seq,id,conversation_id AS thread,sender,recipient,kind,body,created,acknowledged "
        "FROM messages WHERE seq>? ORDER BY seq LIMIT ?",
        (int(after_direct), limit),
    ).fetchall()
    team = db.execute(
        "SELECT seq,id,team_id AS thread,sender,recipient,kind,body,created,acknowledged "
        "FROM team_messages WHERE seq>? ORDER BY seq LIMIT ?",
        (int(after_team), limit),
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


def observe(bridge, principal, **arguments):
    """Capability-checked entry point used by the MCP tool."""
    bridge.security.principal(principal, OBSERVE_CAPABILITY)
    return overview(bridge.store.db, **arguments)
