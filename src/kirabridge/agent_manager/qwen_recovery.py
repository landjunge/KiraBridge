"""Explicit operator-owned Qwen recovery binding, never inferred from a prompt.

The old Core store may be gone. Its receipt remains historical evidence, not a
live task; a new Core task loads only the exact proven provider session and cwd.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from kirabridge.bridge_core.models import BridgeError


class QwenRecoveryBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    original_task_id: str
    original_core_task_id: str
    owner: str
    session_id: str
    cwd: str
    model: str
    auth_type: str
    effort: str
    transcript_path: str
    transcript_sha256: str
    receipt_path: str
    receipt_sha256: str
    source_handoff_sha256: str

    def validate_effect(self, task, args, config):
        if (
            task["id"] == self.original_core_task_id
            or task["principal"] != self.owner
            or str(Path(args.cwd).resolve()) != self.cwd
            or config.model != self.model
            or config.qwen_auth_type != self.auth_type
            or config.qwen_reasoning_effort != self.effort
        ):
            raise BridgeError(
                "agent_recovery_denied", "Qwen recovery differs from its original binding"
            )
        receipt_path = Path(self.receipt_path)
        fd = os.open(receipt_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if info.st_uid != os.getuid() or info.st_mode & 0o077 or not stat.S_ISREG(info.st_mode):
                raise BridgeError("agent_recovery_denied", "Recovery receipt must be owner-only")
            receipt_raw = source.read(1024 * 1024 + 1)
        if hashlib.sha256(receipt_raw).hexdigest() != self.receipt_sha256:
            raise BridgeError("agent_recovery_denied", "Original recovery receipt changed")
        receipt = json.loads(receipt_raw)
        native = receipt.get("last_native_observation", {})
        if (
            receipt.get("task_id") != self.original_task_id
            or receipt.get("core_task_id") != self.original_core_task_id
            or native.get("session_id") != self.session_id
            or native.get("owner") != self.owner
            or native.get("cwd") != self.cwd
            or receipt.get("core_state") != "unknown"
            or receipt.get("source_handoff_sha256") != self.source_handoff_sha256
        ):
            raise BridgeError(
                "agent_recovery_denied", "Historical receipt does not prove this session"
            )
        path = Path(self.transcript_path)
        expected = (
            Path.home()
            / ".qwen/projects"
            / self.cwd.replace("/", "-")
            / "chats"
            / f"{self.session_id}.jsonl"
        )
        if path != expected:
            raise BridgeError("agent_recovery_denied", "Qwen recovery transcript path differs")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as source:
            st = os.fstat(source.fileno())
            # Qwen itself writes 0644 transcripts. Integrity comes from the
            # exact native path, uid, non-writable parent chain and pinned hash;
            # this adapter never changes the user's native file permissions.
            if st.st_uid != os.getuid() or st.st_mode & 0o022 or not stat.S_ISREG(st.st_mode):
                raise BridgeError(
                    "agent_recovery_denied", "Qwen history ownership/integrity differs"
                )
            private_ancestor = False
            for parent in [path.parent, *path.parent.parents]:
                if parent == Path.home():
                    break
                info = parent.lstat()
                private_ancestor |= not bool(info.st_mode & 0o077)
                if parent.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o022:
                    raise BridgeError(
                        "agent_recovery_denied", "Qwen history parent ownership differs"
                    )
            if not private_ancestor:
                raise BridgeError("agent_recovery_denied", "Qwen history lacks a private ancestor")
            raw = source.read(8 * 1024 * 1024 + 1)
        if hashlib.sha256(raw).hexdigest() != self.transcript_sha256:
            raise BridgeError("agent_recovery_denied", "Qwen transcript changed before recovery")
        for line in raw.splitlines():
            record = json.loads(line)
            if (
                record.get("sessionId") != self.session_id
                or record.get("cwd") != self.cwd
                or (
                    record.get("type") == "assistant"
                    and record.get("model") not in (None, self.model)
                )
            ):
                raise BridgeError("agent_recovery_denied", "Qwen history session/cwd differs")
