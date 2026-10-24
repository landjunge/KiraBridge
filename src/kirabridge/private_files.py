"""Owner-only bounded file IO, independent of daemon clients and UI coordination."""

import json
import os
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError


def private_json(path: Path) -> dict:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "r", encoding="utf-8") as source:
        info = os.fstat(source.fileno())
        if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise BridgeError("unsafe_credentials", "Credentials must be owner-only")
        raw = source.read(65537)
        if len(raw) > 65536:
            raise BridgeError("unsafe_credentials", "Credentials file exceeds limit")
        return json.loads(raw)


def write_private(path: Path, text: str | bytes, *, mode: int = 0o600) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    with os.fdopen(fd, "wb") as output:
        output.write(text.encode() if isinstance(text, str) else text)
        output.flush()
        os.fsync(output.fileno())
