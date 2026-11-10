"""Explicit, backed-up and reversible compaction of historical large task results.

Run only with KiraBridge stopped, never automatically:

    python -m kirabridge.storage_compaction BRIDGE_DB BACKUP_DIR            # dry run
    python -m kirabridge.storage_compaction BRIDGE_DB BACKUP_DIR --apply
    python -m kirabridge.storage_compaction BRIDGE_DB BACKUP_DIR --restore MANIFEST

Only finished tasks (completed/failed/cancelled/blocked) are touched; UNKNOWN,
queued and running work, events, approvals and the audit hash chain stay byte-
identical. Large result fields move to a gzip archive with per-task SHA256; the
task keeps small fields, evidence and an ``output_archived`` reference.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

from kirabridge.audit_manager import verify
from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.output_history import INLINE_KEYS, LARGE_FIELD_BYTES, LARGE_RESULT_BYTES
from kirabridge.task_manager.store import Store

FINISHED = ("completed", "failed", "cancelled", "blocked")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _size(path: Path) -> int:
    return sum(
        os.path.getsize(str(path) + suffix)
        for suffix in ("", "-wal")
        if os.path.exists(str(path) + suffix)
    )


def _split(result: dict) -> dict:
    return {
        key: value
        for key, value in result.items()
        if key not in INLINE_KEYS
        and not key.startswith("output_")
        and len(canonical(value).encode()) > LARGE_FIELD_BYTES
    }


def _candidates(db):
    return db.execute(
        "SELECT id,operation,result FROM tasks WHERE state IN (?,?,?,?) "
        "AND length(result)>? AND json_extract(result,'$.output_codec') IS NULL "
        "AND json_extract(result,'$.output_archived') IS NULL ORDER BY created,id",
        (*FINISHED, LARGE_RESULT_BYTES),
    )


def _private_write(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def compact(db_path: Path, backup_dir: Path, *, apply: bool = False) -> dict:
    db_path, backup_dir = Path(db_path), Path(backup_dir)
    store = Store(db_path)
    try:
        rows = _candidates(store.db).fetchall()
        plan = {
            "tasks": len(rows),
            "result_bytes": sum(len(r["result"].encode()) for r in rows),
            "db_bytes_before": _size(db_path),
            "applied": False,
        }
        if not apply:
            return plan
        if store.db.execute(
            "SELECT count(*) FROM tasks WHERE state IN ('accepted','running')"
        ).fetchone()[0]:
            raise BridgeError("compaction_busy", "Stop KiraBridge before compaction")
        backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        backup = backup_dir / f"bridge-before-compaction-{stamp}.sqlite3"
        target = sqlite3.connect(backup)
        store.db.backup(target)
        target.execute("PRAGMA journal_mode=DELETE")  # one self-contained backup file
        target.close()
        os.chmod(backup, 0o600)
        check = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BridgeError("compaction_backup", "Backup integrity check failed")
        check.close()
        backup_sha = _sha256(backup)
        chain_before = verify(store)
        if not chain_before["valid"]:
            raise BridgeError("compaction_chain", "Audit chain invalid; nothing changed")
        archive = backup_dir / f"task-results-{stamp}.jsonl.gz"
        lines, updates, removed = [], [], 0
        for row in rows:
            original = json.loads(row["result"])
            payload = _split(original)
            if not payload:
                continue
            raw = canonical(payload).encode()
            kept = {k: v for k, v in original.items() if k not in payload}
            kept["output_archived"] = {
                "archive": archive.name,
                "fields": sorted(payload),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }
            text = canonical(kept)
            lines.append(
                canonical(
                    {
                        "task_id": row["id"],
                        "operation": row["operation"],
                        "original_sha256": hashlib.sha256(row["result"].encode()).hexdigest(),
                        "payload": payload,
                    }
                )
            )
            updates.append((text, row["id"], row["result"]))
            removed += len(row["result"].encode()) - len(text.encode())
        _private_write(archive, gzip.compress(("\n".join(lines) + "\n").encode()))
        archive_sha = _sha256(archive)
        with store.transaction():
            for text, task_id, previous in updates:
                changed = store.db.execute(
                    "UPDATE tasks SET result=? WHERE id=? AND result=? AND state IN (?,?,?,?)",
                    (text, task_id, previous, *FINISHED),
                ).rowcount
                if changed != 1:
                    raise BridgeError("compaction_conflict", "Task changed; nothing applied")
            store.audit(
                "control.storage_compacted",
                "local",
                None,
                {
                    "tasks": len(updates),
                    "result_bytes_removed": removed,
                    "backup": backup.name,
                    "backup_sha256": backup_sha,
                    "archive": archive.name,
                    "archive_sha256": archive_sha,
                    "unknown_tasks_touched": 0,
                    "reversible": True,
                },
            )
        store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        store.db.execute("VACUUM")
        store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        chain_after = verify(store)
        manifest = {
            **plan,
            "applied": True,
            "tasks": len(updates),
            "result_bytes_removed": removed,
            "db_bytes_after": _size(db_path),
            "backup": str(backup),
            "backup_sha256": backup_sha,
            "archive": str(archive),
            "archive_sha256": archive_sha,
            "audit_before": chain_before,
            "audit_after": chain_after,
            "restore": "--restore this manifest, or copy the backup back with KiraBridge stopped",
        }
        manifest_path = backup_dir / f"compaction-{stamp}.json"
        _private_write(manifest_path, (canonical(manifest) + "\n").encode())
        return {**manifest, "manifest": str(manifest_path)}
    finally:
        store.close()


def restore(db_path: Path, manifest_path: Path) -> dict:
    manifest = json.loads(Path(manifest_path).read_text())
    archive = Path(manifest["archive"])
    if _sha256(archive) != manifest["archive_sha256"]:
        raise BridgeError("compaction_archive", "Archive checksum mismatch; nothing restored")
    store = Store(Path(db_path))
    try:
        restored = 0
        with store.transaction():
            for line in gzip.decompress(archive.read_bytes()).decode().splitlines():
                item = json.loads(line)
                row = store.db.execute(
                    "SELECT result FROM tasks WHERE id=?", (item["task_id"],)
                ).fetchone()
                current = json.loads(row["result"])
                if (current.get("output_archived") or {}).get("archive") != archive.name:
                    continue
                current.pop("output_archived")
                text = canonical({**current, **item["payload"]})
                if hashlib.sha256(text.encode()).hexdigest() != item["original_sha256"]:
                    raise BridgeError("compaction_restore", "Restored result does not match")
                store.db.execute("UPDATE tasks SET result=? WHERE id=?", (text, item["task_id"]))
                restored += 1
            store.audit(
                "control.storage_restored",
                "local",
                None,
                {"tasks": restored, "archive": archive.name, "archive_sha256": _sha256(archive)},
            )
        return {"restored": restored, "audit": verify(store)}
    finally:
        store.close()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("db", type=Path)
    parser.add_argument("backup_dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restore", type=Path, metavar="MANIFEST")
    args = parser.parse_args(argv)
    result = (
        restore(args.db, args.restore)
        if args.restore
        else compact(args.db, args.backup_dir, apply=args.apply)
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
