"""Owner-only webhook delivery queue views; no callback secrets or invented UI receipts."""

import hashlib
import json


def rows(push):
    return push.db.execute(
        "SELECT d.rowid AS position,d.*,s.task_id,s.principal,s.verified AS created "
        "FROM deliveries d JOIN subscriptions s ON s.id=d.subscription_id "
        "WHERE s.principal=? ORDER BY d.rowid",
        (push.principal,),
    ).fetchall()


def revision(row):
    return hashlib.sha256(json.dumps(dict(row), sort_keys=True).encode()).hexdigest()


def snapshot(push):
    return hashlib.sha256(
        json.dumps([(r["event_id"], revision(r)) for r in rows(push)]).encode()
    ).hexdigest()


def entries(push, after=0, limit=50):
    from kirabridge.event_push import EventError

    if type(after) is not int or type(limit) is not int or after < 0 or not 1 <= limit <= 100:
        raise EventError("invalid_queue_cursor")
    result = []
    for row in rows(push):
        if row["position"] <= after:
            continue
        body = json.loads(row["body"])
        body.pop("receipt_token", None)
        result.append(
            {
                **{
                    key: row[key]
                    for key in (
                        "event_id",
                        "subscription_id",
                        "task_id",
                        "state",
                        "position",
                        "created",
                        "attempts",
                        "reason",
                        "http_status",
                    )
                },
                "body": body,
                "revision": revision(row),
                "execution_stop_claimed": False,
            }
        )
        if len(result) == limit:
            break
    return {
        "entries": result,
        "next_cursor": result[-1]["position"] if result else after,
        "scope": "own webhook delivery only; task execution unaffected",
        "queue_revision": snapshot(push),
    }


async def inspect_entries(push, after=0, limit=50):
    """Revalidate source access before exposing a previously captured task payload."""
    result = entries(push, after, limit)
    for entry in result["entries"]:
        try:
            allowed = await push.authorize_task(entry["task_id"])
        except Exception:
            allowed = None
        if allowed is not True:
            entry.pop("body", None)
            entry["content_authorization"] = "denied" if allowed is False else "unconfirmed"
        else:
            entry["content_authorization"] = "authorized"
    return result


def control(push, event_id, expected_revision, action):
    from kirabridge.event_push import EventError

    if action == "clear":
        with push.journal.transaction():
            if snapshot(push) != expected_revision:
                raise EventError("queue_changed")
            changed, unresolved = [], []
            for row in rows(push):
                if row["state"] == "sending":
                    unresolved.append(row["event_id"])
                elif row["state"] in {"pending", "unknown", "authorization_unknown"}:
                    push.db.execute(
                        "UPDATE deliveries SET state='paused' WHERE event_id=?", (row["event_id"],)
                    )
                    push.journal.observe("queue.cancel", row["subscription_id"], row["event_id"])
                    changed.append(row["event_id"])
            return {
                "paused": changed,
                "inflight_unresolved": unresolved,
                "task_execution_changed": False,
                "history_preserved": True,
            }
    with push.journal.transaction():
        candidates = [row for row in rows(push) if row["event_id"] == event_id]
        if not candidates:
            raise EventError("delivery_not_found")
        row = candidates[0]
        if revision(row) != expected_revision:
            raise EventError("queue_changed")
        if action == "cancel":
            if row["state"] == "sending":
                raise EventError("delivery_inflight_unresolved")
            if row["state"] not in {"pending", "unknown", "authorization_unknown"}:
                raise EventError("delivery_not_pending")
            next_state = "paused"
        elif action == "restore":
            if row["state"] != "paused" or row["attempts"]:
                raise EventError("cannot_replay_attempted_delivery")
            next_state = "pending"
        else:
            raise EventError("invalid_queue_action")
        push.db.execute("UPDATE deliveries SET state=? WHERE event_id=?", (next_state, event_id))
        push.journal.observe("queue." + action, row["subscription_id"], event_id)
    return {
        "event_id": event_id,
        "state": next_state,
        "history_preserved": True,
        "task_execution_changed": False,
        "prior_delivery_unconfirmed": bool(row["attempts"]),
    }
