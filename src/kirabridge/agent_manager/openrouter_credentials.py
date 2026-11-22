"""OpenRouter local credential access; values stay in memory and outside argv/logs."""

from __future__ import annotations

import subprocess
import sys

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
