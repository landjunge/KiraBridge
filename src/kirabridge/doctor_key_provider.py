"""Platform-independent read-only loading of provisioned doctor signing keys."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def load_systemd_credential(name: str = "doctor-hmac-key") -> bytes:
    if "/" in name or name in ("", ".", ".."):
        raise ValueError("invalid credential name")
    directory = os.environ.get("CREDENTIALS_DIRECTORY")
    if not directory:
        raise RuntimeError("systemd credentials unavailable")
    path = Path(directory) / name
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("credential must be a regular file")
        key = os.read(fd, 65)
        if len(key) != 32:
            raise ValueError("doctor credential must contain exactly 32 bytes")
        return key
    finally:
        os.close(fd)


def load_doctor_key(platform: str | None = None) -> bytes:
    """Load a provisioned key; never silently fall back to a local receipt key."""
    import sys

    selected = platform or sys.platform
    if selected.startswith("linux"):
        return load_systemd_credential()
    if selected == "darwin":
        raise RuntimeError("macOS Keychain doctor key adapter not yet configured")
    raise RuntimeError("unsupported doctor key provider")
