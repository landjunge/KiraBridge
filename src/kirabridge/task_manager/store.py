from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from kirabridge.bridge_core.config import private_directory
from kirabridge.bridge_core.models import TRANSITIONS, BridgeError, State, canonical, digest

SCHEMA_VERSION = 2

MESSAGE_SCHEMA = """
CREATE TABLE conversations (
 id TEXT PRIMARY KEY, party_a TEXT NOT NULL, party_b TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE messages (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
 conversation_id TEXT NOT NULL REFERENCES conversations(id), position INTEGER NOT NULL,
 sender TEXT NOT NULL, recipient TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL,
 idem TEXT NOT NULL, request_hash TEXT NOT NULL, reply_to TEXT REFERENCES messages(id),
 task_id TEXT REFERENCES tasks(id), depth INTEGER NOT NULL, request_reply INTEGER NOT NULL,
 created REAL NOT NULL, delivered REAL, receipt TEXT, acknowledged REAL,
 UNIQUE(sender,idem), UNIQUE(conversation_id,position)
);
CREATE INDEX message_inbox ON messages(recipient,acknowledged,seq);
CREATE TABLE message_jobs (
 message_id TEXT PRIMARY KEY REFERENCES messages(id), state TEXT NOT NULL,
 run_id TEXT UNIQUE, claimed REAL, started REAL, finished REAL,
 reply_id TEXT REFERENCES messages(id), evidence TEXT NOT NULL DEFAULT '{}', error TEXT
);
CREATE INDEX message_queue ON message_jobs(state);
CREATE TABLE message_events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT NOT NULL REFERENCES messages(id),
 at REAL NOT NULL, kind TEXT NOT NULL, evidence TEXT NOT NULL
);
PRAGMA user_version=2;
"""

SCHEMA = """
CREATE TABLE tasks (
 id TEXT PRIMARY KEY, principal TEXT NOT NULL, idem TEXT NOT NULL,
 request_hash TEXT NOT NULL, operation TEXT NOT NULL, args TEXT NOT NULL,
 agent TEXT, parent_id TEXT REFERENCES tasks(id), state TEXT NOT NULL,
 created REAL NOT NULL, updated REAL NOT NULL, accepted REAL, started REAL, finished REAL,
 receipt TEXT, evidence TEXT NOT NULL DEFAULT '{}', result TEXT, error TEXT,
 lease_owner TEXT, lease_until REAL, attempt INTEGER NOT NULL DEFAULT 1,
 UNIQUE(principal, idem)
);
CREATE INDEX queue_idx ON tasks(state, created);
CREATE TABLE events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(id),
 at REAL NOT NULL, state TEXT NOT NULL, evidence TEXT NOT NULL
);
CREATE TABLE approvals (
 token_hash TEXT PRIMARY KEY, principal TEXT NOT NULL, task_id TEXT NOT NULL,
 request_hash TEXT NOT NULL, expires REAL NOT NULL, used REAL
);
CREATE TABLE audit (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, kind TEXT NOT NULL,
 principal TEXT NOT NULL, task_id TEXT, metadata TEXT NOT NULL,
 previous TEXT NOT NULL, hash TEXT NOT NULL
);
PRAGMA user_version=1;
"""


class Store:
    """Short synchronous WAL transactions; no network or await inside a transaction."""

    def __init__(self, path: Path):
        private_directory(path.parent)
        if path.is_symlink():
            raise BridgeError("unsafe_state", "Database must not be a symlink")
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        if os.name != "nt" and path.stat().st_mode & 0o077:
            raise BridgeError("unsafe_state", "Database must be owner-only")
        self.db = sqlite3.connect(path, isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        try:
            # Re-read under the write lock: concurrent daemon/client starts must not migrate twice.
            with self.transaction():
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
                scripts = []
                if version == 0:
                    scripts.append(SCHEMA)
                    version = 1
                if version == 1:
                    scripts.append(MESSAGE_SCHEMA)
                elif version != SCHEMA_VERSION:
                    raise BridgeError("schema_version", "Unsupported database schema")
                for script in scripts:
                    for statement in script.split(";"):
                        if statement.strip():
                            self.db.execute(statement)
        except BaseException:
            self.db.close()
            raise

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def audit(self, kind: str, principal: str, task_id: str | None, metadata: dict) -> None:
        # Call inside the transaction that performs the audited action.
        previous = self.db.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        record = {
            "at": time.time(),
            "kind": kind,
            "principal": principal,
            "task_id": task_id,
            "metadata": metadata,
            "previous": previous[0] if previous else "0" * 64,
        }
        self.db.execute(
            "INSERT INTO audit(at,kind,principal,task_id,metadata,previous,hash) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                record["at"],
                kind,
                principal,
                task_id,
                canonical(metadata),
                record["previous"],
                digest(record),
            ),
        )

    def get(self, task_id: str, principal: str | None = None) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None or (principal is not None and row["principal"] != principal):
            raise BridgeError("not_found", "Task not found")
        result = dict(row)
        for key in ("args", "evidence", "result", "error"):
            result[key] = json.loads(result[key]) if result[key] is not None else None
        result.pop("request_hash")
        return result

    def transition(
        self,
        task_id: str,
        state: State,
        evidence: dict,
        *,
        result: dict | None = None,
        error: dict | None = None,
        owner: str | None = None,
        expected_hash: str | None = None,
        expected_states: set[State] | None = None,
    ) -> None:
        with self.transaction():
            row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise BridgeError("not_found", "Task not found")
            if expected_hash is not None and expected_hash != row["request_hash"]:
                raise BridgeError("review_conflict", "The reviewed request does not match")
            if expected_states is not None and row["state"] not in expected_states:
                raise BridgeError("state_conflict", "Task is no longer awaiting this decision")
            if state not in TRANSITIONS[State(row["state"])]:
                raise BridgeError("state_conflict", "Invalid task state transition")
            if owner and row["lease_owner"] != owner:
                raise BridgeError("lease_lost", "Worker no longer owns this task")
            if not evidence:
                raise BridgeError("missing_evidence", "A state transition requires evidence")
            now = time.time()
            finished = now if state in {State.COMPLETED, State.FAILED, State.CANCELLED} else None
            self.db.execute(
                "UPDATE tasks SET state=?,updated=?,started=COALESCE(started,?),finished=?,"
                "evidence=?,result=?,error=? WHERE id=?",
                (
                    state,
                    now,
                    now if state == State.RUNNING else None,
                    finished,
                    canonical(evidence),
                    canonical(result) if result is not None else None,
                    canonical(error) if error else None,
                    task_id,
                ),
            )
            self.db.execute(
                "INSERT INTO events(task_id,at,state,evidence) VALUES(?,?,?,?)",
                (task_id, now, state, canonical(evidence)),
            )
            self.audit(
                "task.transition",
                row["principal"],
                task_id,
                {"from": row["state"], "to": state, "evidence_hash": digest(evidence)},
            )

    def claim(self, owner: str, lease_seconds: float, control: bool = False) -> dict | None:
        with self.transaction():
            comparison = "IN" if control else "NOT IN"
            row = self.db.execute(
                f"SELECT id,principal FROM tasks WHERE state='queued' AND operation {comparison} "
                "('process.list','process.inspect','process.terminate') ORDER BY created,id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            now, receipt = time.time(), str(uuid.uuid4())
            evidence = {"receiver": "kirabridge.dispatcher", "receipt_id": receipt, "worker": owner}
            self.db.execute(
                "UPDATE tasks SET state='accepted',accepted=?,updated=?,receipt=?,evidence=?,"
                "lease_owner=?,lease_until=? WHERE id=? AND state='queued'",
                (now, now, receipt, canonical(evidence), owner, now + lease_seconds, row["id"]),
            )
            self.db.execute(
                "INSERT INTO events(task_id,at,state,evidence) VALUES(?,?,?,?)",
                (row["id"], now, "accepted", canonical(evidence)),
            )
            self.audit("task.accepted", row["principal"], row["id"], {"receipt_id": receipt})
        return self.get(row["id"])

    def recover(self) -> int:
        # Runtime exclusive lock proves the previous dispatcher no longer owns this DB.
        rows = self.db.execute(
            "SELECT id FROM tasks WHERE state IN ('accepted','running')"
        ).fetchall()
        for row in rows:
            previous = self.get(row[0])["evidence"]
            self.transition(
                row[0],
                State.UNKNOWN,
                {"reason": "dispatcher_restart", "last_observation": previous},
            )
        return len(rows)

    def close(self) -> None:
        self.db.close()
