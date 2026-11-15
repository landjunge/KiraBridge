"""Private readiness for the existing persistent Events sender, never a chat receipt."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path

from kirabridge.event_push import canonical


class SenderReadiness:
    """Attest one live lock-owning generation, source, route and successful cycle."""

    def __init__(self, journal, config, principal, allowed_hosts, *, max_age=15.0):
        self.journal = journal
        self.directory = Path(journal.db.execute("PRAGMA database_list").fetchone()[2]).parent
        self.max_age = max_age
        self.lease = None
        root = Path(__file__).resolve().parents[2]
        source = hashlib.sha256()
        for relative in (
            "src/kirabridge/event_readiness.py",
            "src/kirabridge/event_push.py",
            "src/kirabridge/mcp_gateway/event_envelope.py",
            "integrations/chat-events/serve.py",
            "integrations/chat-events/connect.py",
        ):
            source.update(relative.encode() + b"\0" + (root / relative).read_bytes())
        self.binding = hashlib.sha256(
            canonical(
                {
                    "principal": principal,
                    "config": config.model_dump(mode="json"),
                    "source_db": str((config.state_path / "bridge.sqlite3").resolve()),
                    "allowed_hosts": sorted(set(allowed_hosts)),
                    "source": source.hexdigest(),
                }
            ).encode()
        ).hexdigest()

    @staticmethod
    def process_start(pid):
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise ValueError("invalid_sender_pid")
        if sys.platform.startswith("linux"):
            # proc field 22; the parenthesized process name may contain spaces.
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            if fields[0] not in {"Z", "X"}:
                return fields[19]
        if sys.platform == "darwin":
            import ctypes

            # Darwin sys/proc_info.h: proc_bsdinfo / PROC_PIDTBSDINFO.
            # Use the kernel's microsecond birth time, not ps's rounded time.
            class BSDInfo(ctypes.Structure):
                _fields_ = [
                    ("ids", ctypes.c_uint32 * 12),
                    ("comm", ctypes.c_char * 16),
                    ("name", ctypes.c_char * 32),
                    ("info", ctypes.c_uint32 * 6),
                    ("seconds", ctypes.c_uint64),
                    ("micros", ctypes.c_uint64),
                ]

            query = ctypes.CDLL("/usr/lib/libproc.dylib").proc_pidinfo
            query.argtypes = [
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint64,
                ctypes.c_void_p,
                ctypes.c_int,
            ]
            query.restype = ctypes.c_int
            value = BSDInfo()
            if (
                query(pid, 3, 0, ctypes.byref(value), ctypes.sizeof(value)) == ctypes.sizeof(value)
                and value.ids[3] == pid
                and value.ids[1] != 5
            ):  # SZOMB
                return f"{value.seconds}:{value.micros}"
        raise ValueError("sender_process_generation_unavailable")

    def start(self, lock_fd):
        """Invalidate the previous generation immediately after singleton acquisition."""
        self.lease = {
            "pid": os.getpid(),
            "process_start": self.process_start(os.getpid()),
            "generation": uuid.uuid4().hex,
            "binding": self.binding,
        }
        # A partial write or startup failure fails closed against the old marker.
        os.ftruncate(lock_fd, 0)
        os.pwrite(lock_fd, canonical(self.lease).encode(), 0)
        self.publish("starting")

    def publish(self, state):
        # The persistent sender calls this only while owning sender.lock. No
        # callback URL, signing secret, token, config contents or payload is stored.
        if self.lease is None:
            raise RuntimeError("sender_generation_not_started")
        value = canonical(
            {
                **self.lease,
                "role": "persistent_event_sender",
                "binding": self.binding,
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
                lease = json.loads(os.pread(fd, 4096, 0))
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
                and all(
                    value.get(key) == lease.get(key)
                    for key in ("pid", "process_start", "generation", "binding")
                )
                and isinstance(lease.get("generation"), str)
                and len(lease["generation"]) == 32
                and self.process_start(lease.get("pid")) == lease.get("process_start")
                and 0 <= age <= self.max_age
            )
        except (OSError, ValueError, TypeError, AttributeError, IndexError):
            return False
