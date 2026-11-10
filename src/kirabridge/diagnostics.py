"""Bounded metadata in the existing audit chain; reports are views, not a second log."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError, canonical, digest
from kirabridge.read_tool_batch import READ_TOOLS as ROUTINE_READ_TOOLS
from kirabridge.task_manager.store import Store

RUNTIME_KEYS = (
    "instance_id",
    "version",
    "started_at",
    "config_sha256",
    "effective_config_sha256",
    "source_tree_sha256",
)
FIELDS = {
    "connection_id",
    "previous_connection_id",
    "peer_ref",
    "transport",
    "phase",
    "outcome",
    "error_code",
    "operation",
    "tool",
    "task_id",
    "workflow_id",
    "runtime",
    "previous_runtime",
    "config_changed",
    "source_changed",
    "effective_config_changed",
    "change_actor",
    "checks",
    "check_id",
    "observer",
    "notification_receipt",
    "external_tunnel",
}


# Successful polls of read tools (ROUTINE_READ_TOOLS) carry no task evidence. They
# stay recorded, but in the overflow archive, so they cannot exhaust the hot budget.
ARCHIVE = "diagnostic-archive.jsonl"
ARCHIVE_SEGMENT_BYTES = 16 * 1024 * 1024
ARCHIVE_SEGMENTS = 8  # rotated segments kept; each removal is anchored in the audit chain


def _tail(path: Path):
    """Last complete record of one segment; a torn final write is cut back."""
    with open(path, "r+b") as handle:
        size = handle.seek(0, os.SEEK_END)
        handle.seek(max(0, size - 16384))
        data = handle.read()
        if data and not data.endswith(b"\n"):
            cut = data.rfind(b"\n") + 1
            handle.truncate(size - len(data) + cut)
            data = data[:cut]
    lines = data.splitlines()
    return json.loads(lines[-1]) if lines else None


def archive_segments(directory: Path) -> list[Path]:
    rotated = sorted(directory.glob("diagnostic-archive.*.jsonl"))
    current = directory / ARCHIVE
    return rotated + ([current] if current.exists() else [])


def append_archive(store, directory: Path, kind, principal, task_id, metadata) -> None:
    """Overflow hash chain. Caller holds the SQLite write lock, which serializes
    appends across processes; hot SQLite rows are never deleted or rewritten."""
    current = directory / ARCHIVE
    segments = archive_segments(directory)
    last = next((r for r in (_tail(s) for s in reversed(segments)) if r), None)
    record = {
        "seq": last["seq"] + 1 if last else 1,
        "at": time.time(),
        "kind": kind,
        "principal": principal,
        "task_id": task_id,
        "metadata": metadata,
        "previous": last["hash"] if last else "0" * 64,
    }
    record["hash"] = digest(record)
    line = (canonical(record) + "\n").encode()
    if current.exists() and current.stat().st_size + len(line) > ARCHIVE_SEGMENT_BYTES:
        rotated = directory / f"diagnostic-archive.{last['seq']:012d}.jsonl"
        os.replace(current, rotated)
        old = sorted(directory.glob("diagnostic-archive.*.jsonl"))[:-ARCHIVE_SEGMENTS]
        store.audit(
            "audit.diagnostic_archive_rotated",
            "local",
            None,
            {
                "segment": rotated.name,
                "segment_sha256": hashlib.sha256(rotated.read_bytes()).hexdigest(),
                "last_seq": last["seq"],
                "last_hash": last["hash"],
                "removed_segments": [x.name for x in old],
            },
        )
        for path in old:
            path.unlink()
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(current, flags, 0o600)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def verify_archive(directory: Path) -> dict:
    previous, count, head = None, 0, None
    for segment in archive_segments(directory):
        for raw in segment.read_bytes().splitlines():
            record = json.loads(raw)
            stated = record.pop("hash")
            if (previous is not None and record["previous"] != previous) or digest(
                record
            ) != stated:
                return {"valid": False, "failed_sequence": record.get("seq")}
            previous, count, head = stated, count + 1, record["seq"]
    return {"valid": True, "records": count, "head_seq": head, "head": previous}


def runtime_ref(runtime: dict) -> dict:
    return {k: runtime.get(k) for k in RUNTIME_KEYS}


def compact_checks(checks: list[dict]) -> list[dict]:
    return [
        {
            "kind": x.get("kind", "read_path"),
            "resource_ref": digest(x.get("path", x.get("operation", ""))),
            "ok": x["ok"],
            "code": x["code"],
        }
        for x in checks[:48]
    ]


class AuditObserver:
    def __init__(self, config, principal, runtime, store=None):
        self.config, self.principal, self.runtime = config, principal, runtime_ref(runtime)
        self.store, self.owned = store, store is None
        self.dropped = self.archived = 0

    def status(self) -> dict:
        policy = self.config.diagnostics
        if not policy.enabled:
            return {"recording": "disabled", "retention": "existing audit; no automatic deletion"}
        if self.store is None:
            self.store = Store(self.config.state_path / "bridge.sqlite3")
        count = self.store.db.execute(
            "SELECT count(*) FROM audit WHERE kind LIKE 'diagnostic.%'"
        ).fetchone()[0]
        today = self.store.db.execute(
            "SELECT count(*) FROM audit WHERE kind LIKE 'diagnostic.%' AND at>=?",
            (time.time() // 86400 * 86400,),
        ).fetchone()[0]
        return {
            "recording": "available"
            if count < policy.max_records and today < policy.max_events_per_day
            else "budget_exhausted",
            "records": count,
            "today": today,
            "max_records": policy.max_records,
            "max_events_per_day": policy.max_events_per_day,
            "dropped_by_this_observer": self.dropped,
            "archived_by_this_observer": self.archived,
            "overflow": ARCHIVE + " (hash chain, rotated segments)",
            "retention": "existing audit preserved; overflow archived, bounded explicit export",
        }

    def __call__(self, kind: str, metadata: dict, task_id: str | None = None) -> bool:
        # All callers are our components. Still discard unexpected fields, never
        # stringify exceptions, command lines, file contents, endpoints or prompts.
        try:
            if not re.fullmatch(r"[a-z_.]{1,64}", kind):
                return False
            data = {k: v for k, v in metadata.items() if k in FIELDS}
            data["runtime"] = self.runtime
            if isinstance(data.get("previous_runtime"), dict):
                data["previous_runtime"] = runtime_ref(data["previous_runtime"])
            for name in ["operation", "tool", "error_code"]:
                if name in data and not re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", str(data[name])):
                    data[name] = "unknown"
            if isinstance(data.get("checks"), list):
                data["checks"] = [
                    {k: v for k, v in check.items() if k in {"kind", "resource_ref", "ok", "code"}}
                    for check in data["checks"][:48]
                ]
            if len(canonical(data).encode()) > 4096:
                self.dropped += 1
                return False
            if self.store is None:
                self.store = Store(self.config.state_path / "bridge.sqlite3")
            routine = (
                data.get("phase") in {"call.started", "call.returned"}
                and data.get("tool") in ROUTINE_READ_TOOLS
                and task_id is None
                and "error_code" not in data
            )
            with self.store.transaction():
                if routine or self.status()["recording"] != "available":
                    append_archive(
                        self.store,
                        self.config.state_path,
                        "diagnostic." + kind,
                        self.principal,
                        task_id,
                        data,
                    )
                    self.archived += 1
                else:
                    self.store.audit("diagnostic." + kind, self.principal, task_id, data)
            return True
        except Exception:
            # Logging failure must never turn a completed remote write into a retry.
            self.dropped += 1
            return False

    def close(self):
        if self.owned and self.store is not None:
            self.store.close()
            self.store = None


def task_report(bridge, principal: str, task_id: str) -> dict:
    bridge.security.principal(principal, "task.read")
    task = bridge.store.get(task_id, principal)
    preflight = bridge.store.db.execute(
        "SELECT seq,at,metadata FROM audit WHERE principal=? AND task_id=? "
        "AND kind='task.preflight' ORDER BY seq DESC LIMIT 1",
        (principal, task_id),
    ).fetchone()
    refs = bridge.store.db.execute(
        "SELECT seq,at,kind,metadata FROM audit WHERE principal=? AND task_id=? "
        "AND kind LIKE 'diagnostic.%' ORDER BY seq DESC LIMIT 16",
        (principal, task_id),
    ).fetchall()
    trace = [
        {
            "audit_seq": r["seq"],
            "at": r["at"],
            "kind": r["kind"],
            "metadata": json.loads(r["metadata"]),
        }
        for r in refs
    ]
    connections = {r["metadata"].get("connection_id") for r in trace}
    connections.discard(None)
    if connections:
        ids = sorted(connections)[:4]
        markers = ",".join("?" for _ in ids)
        rows = bridge.store.db.execute(
            "SELECT seq,at,kind,metadata FROM audit WHERE principal=? "
            "AND kind='diagnostic.connection' "
            f"AND json_extract(metadata,'$.connection_id') IN ({markers}) "
            "AND (json_extract(metadata,'$.phase') NOT LIKE 'call.%' OR task_id=?) "
            "ORDER BY seq LIMIT 16",
            (principal, *ids, task_id),
        ).fetchall()
        trace = [
            {
                "audit_seq": r["seq"],
                "at": r["at"],
                "kind": r["kind"],
                "metadata": json.loads(r["metadata"]),
            }
            for r in rows
        ]
    trace = [
        {
            "audit_seq": r["audit_seq"],
            "at": r["at"],
            **{
                key: r["metadata"].get(key)
                for key in (
                    "connection_id",
                    "previous_connection_id",
                    "phase",
                    "error_code",
                    "notification_receipt",
                    "external_tunnel",
                )
                if key in r["metadata"]
            },
        }
        for r in trace
    ]
    execution = json.loads(preflight["metadata"]) if preflight else None
    code = (task["error"] or {}).get("code")
    if (
        code is None
        and task["state"] == "failed"
        and (task["result"] or {}).get("scope") == "workflow_operation_rejected"
        and task["evidence"].get("rejected") is True
    ):
        # Workflow rejections preserve the existing result contract rather than
        # populating the exception column. Read only the bounded technical code,
        # never context, exception messages or arbitrary nested agent results.
        candidate = task["evidence"].get("error_code")
        code = (
            candidate
            if type(candidate) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", candidate)
            else "workflow_rejected"
        )
    return {
        "schema": "1",
        "diagnostic_id": "task-" + digest([principal, task_id])[:24],
        "task_id": task_id,
        "at": time.time(),
        "operation": task["operation"],
        "error_code": code or ("outcome_unknown" if task["state"] == "unknown" else None),
        "state": task["state"],
        "accepted": task["accepted"] is not None,
        "accepted_at": task["accepted"],
        "started": task["started"] is not None,
        "started_at": task["started"],
        "finished_at": task["finished"],
        "created_at": task["created"],
        "completed": task["state"] == "completed",
        "receipt": task["receipt"],
        "execution_runtime": execution.get("runtime")
        if execution
        else "unknown; no execution-runtime record",
        "reader_runtime": runtime_ref(bridge.runtime),
        "preflight": execution,
        "connection_evidence": trace,
        "external_tunnel_lifecycle": "unknown; not observed by task dispatcher",
        "automatic_retry": False,
        "safe_to_retry_proven_before_start": bool(task["evidence"].get("safe_to_retry")),
        "guidance": "Read original task/events first. Do not repeat an unknown write. "
        "For denials, correct explicit policy or use file tools; no interpreter workaround.",
        "storage": bridge.diagnostics.status(),
    }


def rejection_report(
    runtime: dict, operation: str, code: str, task_id=None, workflow_id=None
) -> dict:
    return {
        "schema": "1",
        "diagnostic_id": "rejection-"
        + digest([runtime.get("instance_id"), task_id, workflow_id, operation, code])[:24],
        "task_id": task_id,
        "workflow_id": workflow_id,
        "at": time.time(),
        "operation": operation if re.fullmatch(r"[a-z_.]{1,80}", operation) else "unknown",
        "error_code": code,
        "state": "not_submitted",
        "accepted": False,
        "started": False,
        "completed": False,
        "execution_runtime": "unknown; execution did not start",
        "reader_runtime": runtime_ref(runtime),
        "automatic_retry": False,
        "external_tunnel_lifecycle": "unknown",
    }


def export_audit(store: Store, destination: Path, after: int = 0, limit: int = 500) -> dict:
    """One bounded segment of the SAME chain. Never prune/rewrite history or overwrite a file."""
    from kirabridge.local_runtime import write_private

    if after < 0 or not 1 <= limit <= 1000:
        raise BridgeError("invalid_cursor", "Use nonnegative cursor and limit1..1000")
    records = []
    size = 0
    for row in store.db.execute(
        "SELECT * FROM audit WHERE seq>? ORDER BY seq LIMIT ?", (after, limit)
    ):
        record = dict(row)
        record["metadata"] = json.loads(record["metadata"])
        size += len(canonical(record).encode())
        if size > 1000000:
            if not records:
                raise BridgeError(
                    "audit_record_limit", "One historical record exceeds export limit"
                )
            break
        records.append(record)
    result = {
        "schema": "1",
        "after": after,
        "next_cursor": records[-1]["seq"] if records else after,
        "records": records,
        "retention": "export only; database unchanged",
    }
    write_private(destination, canonical(result) + "\n")
    return {
        "exported_records": len(records),
        "next_cursor": result["next_cursor"],
        "bytes_bounded": True,
        "database_pruned": False,
    }
