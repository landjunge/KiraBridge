"""Streaming principal-scoped inventory and exact revisions, without delivery effects."""

import hashlib
import json

from kirabridge.bridge_core.models import BridgeError, digest
from kirabridge.operations import OPERATIONS
from kirabridge.queue_management.schema import SPECS, TERMINAL


def execution_lane(operation):
    spec = OPERATIONS.get(operation)
    return spec.execution_class if spec else "unknown"


def canonical_header(principal, queue_id):
    return bytes.fromhex(digest([principal, queue_id]))


class QueueViews:
    def __init__(self, store, security, tasks, messages, handoffs, teams):
        self.store, self.security, self.tasks = store, security, tasks
        self.messages, self.handoffs, self.teams = messages, handoffs, teams

    def _spec(self, principal, queue_id):
        family, _, target = queue_id.partition("/")
        if family not in SPECS:
            raise BridgeError("not_found", "Queue not found")
        table, key, cap = SPECS[family]
        if cap:
            self.security.principal(principal, cap)
        else:
            policy = self.security.principal(principal)
            if not {"task.read", "message.read"}.intersection(policy.capabilities):
                raise BridgeError("forbidden", "Completion read permission required")
        return family, target, table, key

    def _hold(self, family, identifier):
        return self.store.db.execute(
            "SELECT actor,created,reason FROM queue_holds WHERE queue_id=? AND item_id=?",
            (family, identifier),
        ).fetchone()

    def _access(self, principal, family, row):
        if family in {"tasks", "handoffs", "completions"}:
            if row["principal"] != principal and not (
                family == "handoffs" and row["target"] == principal
            ):
                raise BridgeError("not_found", "Entry not found")
        elif family == "messages":
            self.messages._row(principal, row["id"])
        elif family.startswith("team-"):
            self.teams._team(principal, row["team_id"])
        elif family == "voice-buffers":
            if row["sender"] != principal:
                raise BridgeError("not_found", "Entry not found")
        elif family == "session-input":
            self.store.get(row["task_id"], principal)
        if family == "completions":
            cap = "task.read" if row["source"] == "task" else "message.read"
            self.security.principal(principal, cap)

    def _view(self, principal, family, row):
        identifier = row[SPECS[family][1]]
        if family == "tasks":
            value = self.store.get(identifier, principal)
            state, target = value["state"], value.get("agent") or value["operation"]
        elif family == "messages":
            value = self.messages.get(principal, identifier)
            job = value["processing"] or {}
            state = job.get("state") or ("acknowledged" if row["acknowledged"] else "queued")
            target = row["recipient"]
        elif family == "handoffs":
            value = self.handoffs.status(
                principal, identifier
            )  # Observation only, no reconciliation.
            state, target = row["state"], row["target"]
        else:
            value = dict(row)
            # Whitelist data; receipts/approval tokens are not queue-control capabilities.
            for field in ("receipt", "idem", "request_hash"):
                value.pop(field, None)
            for field in ("request", "payload", "evidence", "result"):
                if field in value and isinstance(value[field], str):
                    value[field] = json.loads(value[field])
            if family == "session-input":
                value["task"] = self.store.get(identifier, principal)
            state = row.get("state") or ("acknowledged" if row.get("acknowledged") else "queued")
            target = row.get("recipient") or row.get("assignee") or row.get("target") or principal
        hold = self._hold(family, identifier)
        active = not hold and state not in TERMINAL | {"acknowledged"}
        version = digest(
            {
                "family": family,
                "row": dict(row),
                "hold": dict(hold) if hold else None,
                "detail": value,
            }
        )
        return {
            "id": identifier,
            "cursor": row["queue_cursor"],
            "target": target,
            "created": row.get("created"),
            "state": state,
            "execution_state": state,
            "delivery_active": bool(active),
            "hold": dict(hold) if hold else None,
            "revision": version,
            "detail": value,
            "stop_confirmed": False,
            "history_preserved": True,
        }

    def entries(self, principal, queue_id, after=0, limit=50, active_only=True):
        if after < 0 or not 1 <= limit <= 100:
            raise BridgeError("invalid_cursor", "Use cursor >=0 and limit 1..100")
        family, target, table, _ = self._spec(principal, queue_id)
        result, cursor, exhausted, position = [], after, False, 0
        # Stream rows with bounded page memory; positions are ranked within this authorized view.
        for row in self.store.db.execute(
            f"SELECT rowid AS queue_cursor,* FROM {table} ORDER BY rowid",
        ):
            if row["queue_cursor"] > after:
                cursor = row["queue_cursor"]
            row = dict(row)
            try:
                self._access(principal, family, row)
            except BridgeError:
                continue
            if family == "tasks" and target:
                lane = execution_lane(row["operation"])
                if lane != target:
                    continue
            elif target and target != (row.get("recipient") or row.get("target")):
                continue
            entry = self._view(principal, family, row)
            if not active_only or entry["delivery_active"]:
                position += 1
                if row["queue_cursor"] <= after:
                    continue
                entry["position"] = position
                entry.pop("detail")  # Full content uses the revision-bound paginated entry tool.
                entry["content_tool"] = "queue_entry"
                result.append(entry)
                if len(result) == limit:
                    break
        else:
            exhausted = (
                len(
                    self.store.db.execute(
                        f"SELECT 1 FROM {table} WHERE rowid>? LIMIT 1", (cursor,)
                    ).fetchall()
                )
                == 0
            )
        return {
            "queue_id": queue_id,
            "entries": result,
            "next_cursor": cursor,
            "has_more": not exhausted,
            "scope": "authorized identity only; immutable history retained",
        }

    def read_entry(
        self, principal, queue_id, identifier, offset=0, max_chars=16384, expected_revision=None
    ):
        if offset < 0 or not 1 <= max_chars <= 16384:
            raise BridgeError("invalid_cursor", "Use content offset >=0 and max_chars 1..16384")
        entry = self.get(principal, queue_id, identifier)
        if expected_revision is not None and expected_revision != entry["revision"]:
            raise BridgeError("queue_changed", "Entry changed during content paging")
        from kirabridge.bridge_core.models import canonical

        content = canonical(entry.pop("detail"))
        if offset > len(content):
            raise BridgeError("invalid_cursor", "Content offset exceeds entry length")
        next_offset = min(len(content), offset + max_chars)
        return {
            **entry,
            "detail_json_chunk": content[offset:next_offset],
            "content_offset": offset,
            "next_content_offset": next_offset,
            "content_total_chars": len(content),
            "has_more_content": next_offset < len(content),
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        }

    def _all(self, principal, queue_id, active_only):
        result, cursor = [], 0
        while True:
            page = self.entries(principal, queue_id, cursor, 100, active_only)
            result.extend(page["entries"])
            if len(result) > 10000:
                raise BridgeError(
                    "queue_batch_limit", "Use individual/page control above 10000 entries"
                )
            if not page["has_more"]:
                return result
            cursor = page["next_cursor"]

    def snapshot(self, principal, queue_id, *, exclude_id=None):
        checksum = hashlib.sha256(canonical_header(principal, queue_id))
        count, cursor = 0, 0
        while True:
            page = self.entries(principal, queue_id, cursor, 100, True)
            for row in page["entries"]:
                if row["id"] == exclude_id:
                    continue
                checksum.update(bytes.fromhex(digest([row["id"], row["revision"]])))
                count += 1
            if not page["has_more"]:
                return {"queue_id": queue_id, "count": count, "revision": checksum.hexdigest()}
            cursor = page["next_cursor"]

    def catalog(self, principal):
        result = []
        for family in SPECS:
            try:
                rows, cursor = [], 0
                while True:
                    page = self.entries(principal, family, cursor, 100, False)
                    rows.extend({"target": r["target"]} for r in page["entries"])
                    if not page["has_more"]:
                        break
                    cursor = page["next_cursor"]
            except BridgeError as exc:
                if exc.code in {"forbidden", "not_found"}:
                    continue
                raise
            targets = {""}
            if family in {"messages", "handoffs", "completions"}:
                targets |= {r["target"] for r in rows}
            if family == "tasks":
                targets |= {"read", "normal", "stop", "unknown"}
            for target in sorted(targets):
                queue = family + ("/" + target if target else "")
                result.append({**self.snapshot(principal, queue), "family": family})
        return {
            "queues": result,
            "scope": "this KiraBridge store and authorized identities",
            "external_queues": (
                "Remote provider queues are outside this store; "
                "use event_queue_entries for the authenticated webhook adapter"
            ),
        }

    def get(self, principal, queue_id, identifier):
        family, _, table, key = self._spec(principal, queue_id)
        row = self.store.db.execute(
            f"SELECT rowid AS queue_cursor,* FROM {table} WHERE {key}=?", (identifier,)
        ).fetchone()
        if row is None:
            raise BridgeError("not_found", "Queue entry not found")
        self._access(principal, family, row)
        # Verify selected subqueue as well as ownership.
        view = self._view(principal, family, dict(row))
        _, _, target = queue_id.partition("/")
        if (
            target
            and (execution_lane(row["operation"]) if family == "tasks" else view["target"])
            != target
        ):
            raise BridgeError("not_found", "Entry is outside selected queue")
        return view
