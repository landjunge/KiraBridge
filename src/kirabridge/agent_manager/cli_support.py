"""Small shared bounds for optional CLI adapters; no shell or implicit credentials."""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.terminal_manager import TerminalManager, minimal_environment


def login_identity() -> dict[str, str]:
    """USER/LOGNAME of the account this process runs as, derived from its uid.

    Agent CLIs such as Claude Code look up their stored login in the macOS keychain by
    this account name. The value never comes from the inherited environment.
    """
    try:
        import pwd

        name = pwd.getpwuid(os.getuid()).pw_name
    except (ImportError, AttributeError, KeyError):
        return {}
    return {"USER": name, "LOGNAME": name} if name else {}


def cli_environment(config, terminal: TerminalManager | None = None) -> dict[str, str]:
    """Forward only a deliberately selected credential variable to its CLI."""
    env = terminal.environment.copy() if terminal else minimal_environment()
    env.setdefault("HOME", str(Path.home()))
    env.update(login_identity())
    paths = env["PATH"].split(os.pathsep)
    if config.executable and Path(config.executable).is_absolute():
        directory = str(Path(config.executable).parent)
        if directory not in paths:
            paths.append(directory)
    if sys.platform == "darwin":
        for directory in ("/usr/sbin", "/sbin"):
            if directory not in paths:
                paths.append(directory)
    env["PATH"] = os.pathsep.join(paths)
    key = config.api_key_env
    forbidden = {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "PYTHONPATH",
        "PYTHONHOME",
        "NODE_OPTIONS",
        "NODE_PATH",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
    }
    if key and (not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", key) or key in forbidden):
        raise BridgeError("agent_config", "Use a dedicated credential environment name")
    if key and key in os.environ:
        env[key] = os.environ[key]
    return env


class BoundedText:
    """Keep at most a fixed UTF-8 byte budget without retaining discarded text."""

    def __init__(self, max_bytes: int = 65536):
        if type(max_bytes) is not int or not 1 <= max_bytes <= 1048576:
            raise ValueError("invalid text bound")
        self.max_bytes = max_bytes
        self._data = bytearray()
        self.truncated = False

    def append(self, text: str) -> None:
        if not isinstance(text, str):
            raise UncertainExecution("agent_protocol", "Agent returned invalid text")
        raw = text.encode("utf-8")
        remaining = self.max_bytes - len(self._data)
        self._data.extend(raw[:remaining])
        self.truncated = self.truncated or len(raw) > remaining

    @property
    def text(self) -> str:
        return self._data.decode("utf-8", errors="ignore")


_BEARER = re.compile(r"(?i)\bBearer\s+\S+")
_ASSIGNMENT = re.compile(
    r"(?i)(?<![A-Za-z0-9])(api_key|token|password|secret|authorization)(\s*[=:]\s*)\S+"
)
_LONG_TOKEN = re.compile(r"[A-Za-z0-9_-]{24,}")


def _redact_assignment(match: re.Match) -> str:
    return f"{match.group(1)}{match.group(2)}[redacted]"


def safe_diagnostic(text: str, limit: int = 200) -> str:
    """Bounded CLI diagnostic: no control characters, collapsed space, secrets masked.

    Callers pass an already captured error stream only. The result is never a prompt,
    a model reply, or a file body. At most ``limit`` characters, and never more than 200.
    """
    if not isinstance(text, str):
        return ""
    if type(limit) is not int or not 1 <= limit <= 200:
        limit = 200
    cleaned: list[str] = []
    for char in text[:4096]:
        if char.isspace():
            cleaned.append(" ")
        elif unicodedata.category(char) == "Cc":
            continue
        else:
            cleaned.append(char)
    collapsed = re.sub(r" {2,}", " ", "".join(cleaned)).strip()
    collapsed = _BEARER.sub("Bearer [redacted]", collapsed)
    collapsed = _ASSIGNMENT.sub(_redact_assignment, collapsed)
    collapsed = _LONG_TOKEN.sub("[redacted]", collapsed)
    return collapsed[:limit]


def note_cli_failure(exc, result):
    """Attach provider_error['diagnostic'] from stderr only, never from stdout."""
    if isinstance(result, dict):
        text = result.get("stderr")
        if isinstance(text, str) and text.strip():
            diagnostic = safe_diagnostic(text)
            if diagnostic:
                exc.provider_error = {"diagnostic": diagnostic}
    return exc


def bind_session(current: str | None, new: str) -> str:
    """A provider may announce one bounded session, never silently switch it."""
    if (
        not isinstance(new, str)
        or not new
        or len(new.encode("utf-8")) > 256
        or any(ord(char) < 32 or ord(char) == 127 for char in new)
    ):
        raise UncertainExecution("agent_identity", "Agent returned an invalid session ID")
    if current is not None and current != new:
        raise UncertainExecution("agent_identity", "Agent changed session identity")
    return new
