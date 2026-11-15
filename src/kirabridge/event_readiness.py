"""Private readiness for the existing persistent Events sender, never a chat receipt."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from kirabridge.event_push import canonical


class SenderReadiness:
    """Require the singleton lock plus a fresh marker for this exact route/config."""

    def __init__(self, journal, config, principal, allowed_hosts, *, max_age=15.0):
        self.journal = journal
        self.directory = Path(journal.db.execute("PRAGMA database_list").fetchone()[2]).parent
        self.max_age = max_age
        self.binding = hashlib.sha256(
            canonical(
                {
                    "principal": principal,
                    "config": config.model_dump(mode="json"),
                    "source_db": str((config.state_path / "bridge.sqlite3").resolve()),
                    "allowed_hosts": sorted(set(allowed_hosts)),
                }
            ).encode()
        ).hexdigest()

    def publish(self, state):
        # The persistent sender calls this only while owning sender.lock. No
        # callback URL, signing secret, token, config contents or payload is stored.
        value = canonical(
            {
                "role": "persistent_event_sender",
                "binding": self.binding,
                "pid": os.getpid(),
                "heartbeat": time.time(),
                "state": state,
            }
        )
        self.journal.db.execute(
            "INSERT INTO settings(key,value) VALUES('sender_readiness',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (value,),
        )

    def is_ready(self):
        if os.name != "posix":
            return False  # This server integration has no Windows lock attestation.
        import fcntl

        try:
            fd = os.open(self.directory / "sender.lock", os.O_RDONLY | os.O_NOFOLLOW)
            try:
                info = os.fstat(fd)
                if info.st_uid != os.getuid() or info.st_mode & 0o077:
                    return False
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    locked = True
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    locked = False
            finally:
                os.close(fd)
            if not locked:
                return False
            row = self.journal.db.execute(
                "SELECT value FROM settings WHERE key='sender_readiness'"
            ).fetchone()
            value = json.loads(row[0]) if row else {}
            age = time.time() - value.get("heartbeat", 0)
            return (
                value.get("role") == "persistent_event_sender"
                and value.get("binding") == self.binding
                and value.get("state") == "ready"
                and 0 <= age <= self.max_age
            )
        except (OSError, ValueError, TypeError):
            return False
