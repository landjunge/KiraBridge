"""OpenRouter local credential access; values stay in memory and outside argv/logs."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError

SERVICE = "KiraBridge.OpenRouter"
ACCOUNT = "openrouter"
_SECURITY = "/usr/bin/security"


def _require_macos() -> None:
    if sys.platform != "darwin":
        raise BridgeError("agent_auth", "OpenRouter Keychain credentials require macOS")


def keychain_credential() -> str:
    """Read one exact Keychain item into memory; never return it beyond caller."""
    _require_macos()
    try:
        result = subprocess.run(
            [
                _SECURITY,
                "find-generic-password",
                "-s",
                SERVICE,
                "-a",
                ACCOUNT,
                "-w",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise BridgeError("agent_auth", "OpenRouter Keychain credential is unavailable") from None
    if result.returncode != 0 or len(result.stdout) > 4097:
        raise BridgeError("agent_auth", "OpenRouter Keychain credential is unavailable")
    try:
        value = result.stdout.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError:
        raise BridgeError("agent_auth", "OpenRouter Keychain credential is invalid") from None
    if not value:
        raise BridgeError("agent_auth", "OpenRouter Keychain credential is unavailable")
    return value


def _opencode_auth_path() -> Path:
    return Path.home() / ".local/share/opencode/auth.json"


def _opencode_credential() -> str | None:
    """Read OpenCode's mapped OpenRouter API credential without exposing it."""
    path = _opencode_auth_path()
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
            or info.st_size > 1048576
        ):
            return None
        with os.fdopen(fd, "rb") as stream:
            fd = None
            raw = stream.read(1048577)
        if len(raw) > 1048576:
            return None
        data = json.loads(raw)
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    finally:
        if fd is not None:
            os.close(fd)
    if not isinstance(data, dict):
        return None
    entry = data.get("openrouter")
    if not isinstance(entry, dict) or entry.get("type") != "api":
        return None
    value = entry.get("key")
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 4096
        or value.strip() != value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        return None
    return value


def keychain_or_opencode_credential() -> str:
    """Prefer the exact KiraBridge Keychain item, then OpenCode's local mapping."""
    try:
        return keychain_credential()
    except BridgeError:
        value = _opencode_credential()
        if value:
            return value
        raise BridgeError(
            "agent_auth", "OpenRouter credential is unavailable in local credential stores"
        ) from None


def import_from_hidden_tty() -> bool:
    """Ask `security` to prompt invisibly; no secret passes through this process."""
    _require_macos()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise BridgeError(
            "credential_tty_required", "Credential import requires an interactive TTY"
        )
    try:
        result = subprocess.run(
            [
                _SECURITY,
                "add-generic-password",
                "-U",
                "-s",
                SERVICE,
                "-a",
                ACCOUNT,
                "-w",
            ],
            stdin=None,
            stdout=None,
            stderr=None,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise BridgeError("credential_import", "OpenRouter Keychain import failed") from None
    if result.returncode != 0:
        raise BridgeError("credential_import", "OpenRouter Keychain import failed")
    return True


def keychain_status() -> bool:
    """Return presence only; no `-w`, stdout, stderr, or secret value is read."""
    _require_macos()
    try:
        result = subprocess.run(
            [_SECURITY, "find-generic-password", "-s", SERVICE, "-a", ACCOUNT],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise BridgeError("agent_auth", "OpenRouter Keychain status is unavailable") from None
    return result.returncode == 0


def credential_status() -> bool:
    """Report availability only; never return or print a credential value."""
    try:
        if keychain_status():
            return True
    except BridgeError:
        pass
    return _opencode_credential() is not None
