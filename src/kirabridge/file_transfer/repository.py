"""Principal-scoped additive checkpoints in the existing durable task database."""

from __future__ import annotations

import json
import time

from kirabridge.bridge_core.models import BridgeError, canonical, digest


class TransferRepository:
    def __init__(self, db, transaction, audit):
        self.db, self.transaction, self.audit = db, transaction, audit
        with transaction():
            db.execute(
                "CREATE TABLE IF NOT EXISTS kb_file_transfers ("
                "id TEXT PRIMARY KEY, principal TEXT NOT NULL, manifest TEXT NOT NULL,"
                "manifest_hash TEXT NOT NULL, snapshot TEXT NOT NULL, state TEXT NOT NULL,"
                "offset INTEGER NOT NULL DEFAULT 0, operation_id TEXT NOT NULL,"
                "receipt TEXT, error_code TEXT, updated REAL NOT NULL, "
                "pause_requested INTEGER NOT NULL DEFAULT 0)"
            )

    def add(self, principal, manifest, snapshot):
        encoded = manifest.model_dump(mode="json")
        identifier = digest([principal, encoded])
        operation_id = "kb_file_" + identifier
        with self.transaction():
            self.db.execute(
                "INSERT OR IGNORE INTO kb_file_transfers"
                "(id,principal,manifest,manifest_hash,snapshot,state,offset,operation_id,updated)"
                " VALUES(?,?,?,?,?,'authorized',0,?,?)",
                (
                    identifier,
                    principal,
                    canonical(encoded),
                    digest(encoded),
                    str(snapshot),
                    operation_id,
                    time.time(),
                ),
            )
        return self.get(principal, identifier)

    def get(self, principal, identifier):
        row = self.db.execute(
            "SELECT * FROM kb_file_transfers WHERE id=? AND principal=?", (identifier, principal)
        ).fetchone()
        if not row:
            raise BridgeError("not_found", "Transfer not found for this principal")
        result = dict(row)
        result["manifest"] = json.loads(result["manifest"])
        result["receipt"] = json.loads(result["receipt"]) if result["receipt"] else None
        return result

    def update(self, principal, identifier, state, *, offset=None, receipt=None, error_code=None):
        current = self.get(principal, identifier)
        with self.transaction():
            self.db.execute(
                "UPDATE kb_file_transfers SET state=?,offset=?,receipt=?,error_code=?,updated=?"
                " WHERE id=? AND principal=?",
                (
                    state,
                    current["offset"] if offset is None else offset,
                    canonical(receipt)
                    if receipt
                    else current["receipt"] and canonical(current["receipt"]),
                    error_code,
                    time.time(),
                    identifier,
                    principal,
                ),
            )
            self.audit(
                "file_transfer." + state,
                principal,
                None,
                {
                    "transfer_id": identifier,
                    "bytes": current["offset"] if offset is None else offset,
                    "sha256": current["manifest"]["sha256"],
                    "error_code": error_code,
                },
            )
        return self.get(principal, identifier)

    def pause(self, principal, identifier):
        current = self.get(principal, identifier)
        if current["state"] == "stored":
            raise BridgeError(
                "transfer_already_stored", "Stored import cannot be undone by a transfer pause"
            )
        with self.transaction():
            self.db.execute(
                "UPDATE kb_file_transfers SET pause_requested=1 WHERE id=? AND principal=?",
                (identifier, principal),
            )
        return self.public(self.get(principal, identifier))

    def reset_pause(self, principal, identifier):
        with self.transaction():
            self.db.execute(
                "UPDATE kb_file_transfers SET pause_requested=0 WHERE id=? AND principal=?",
                (identifier, principal),
            )

    def list(self, principal, after="", limit=100):
        rows = self.db.execute(
            "SELECT id FROM kb_file_transfers WHERE principal=? AND id>? ORDER BY id LIMIT ?",
            (principal, after, limit),
        ).fetchall()
        return [self.get(principal, row[0]) for row in rows]

    @staticmethod
    def public(record):
        from kirabridge.file_transfer.diagnostics import public_record

        return public_record(record)
