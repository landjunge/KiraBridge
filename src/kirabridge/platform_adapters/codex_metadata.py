"""Bounded read-only Codex title metadata; never discover a thread or control it.

The caller supplies an already independently bound rollout and thread identity.
The credential JSON helper is inappropriate for this non-credential JSONL file.
"""

import json
import os
import re
import stat
from pathlib import Path

MAX_INDEX_BYTES = 1048576


def read_thread_title(rollout_path, thread_id):
    if not rollout_path or not thread_id:
        return None
    rollout = Path(rollout_path)
    # Existing bound layout: CODEX_HOME/sessions/YYYY/MM/DD/rollout.jsonl.
    if (
        not rollout.is_absolute()
        or len(rollout.parents) < 5
        or rollout.parents[3].name != "sessions"
    ):
        return None
    descriptor = None
    try:
        descriptor = os.open(
            rollout.parents[4] / "session_index.jsonl", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_size > MAX_INDEX_BYTES
        ):
            return None
        chunks, length = [], 0
        while True:
            part = os.read(descriptor, min(65536, MAX_INDEX_BYTES + 1 - length))
            if not part:
                break
            chunks.append(part)
            length += len(part)
            if length > MAX_INDEX_BYTES:
                return None
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            length != before.st_size
            or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
            or not raw.endswith(b"\n")
        ):
            return None
        title = None
        for line in raw.decode("utf-8").splitlines():
            item = json.loads(line)
            if isinstance(item, dict) and item.get("id") == thread_id:
                title = item.get("thread_name")
        return (
            title
            if isinstance(title, str) and re.fullmatch(r"[^\x00-\x1f\x7f]{1,512}", title)
            else None
        )
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)
