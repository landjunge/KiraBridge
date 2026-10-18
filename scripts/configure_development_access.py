"""Explicit local operator policy change. No credentials, daemon restart or sudoers writes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import tomllib
import uuid
from pathlib import Path

from kirabridge.bridge_core.config import Config, private_directory
from kirabridge.filesystem_manager import PathScope
from kirabridge.terminal_manager import TerminalManager


def configure(
    path: Path,
    backup_dir: Path,
    roots: list[str],
    search_path: list[str],
    *,
    full_terminal: bool,
    expected_sha256: str,
) -> dict:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Configuration must be an owner-only regular file")
    raw = path.read_bytes()
    before = hashlib.sha256(raw).hexdigest()
    if before != expected_sha256:
        raise ValueError("Configuration changed since inspection; do not overwrite")
    old = Config.model_validate(tomllib.loads(raw.decode()))
    for value in roots:
        with PathScope([value]).directory(value) as fd:
            if os.fstat(fd).st_uid != os.getuid():
                raise ValueError("Project directory must belong to the local operator")
    text = raw.decode()
    principals = [name for name in ("local", "chatgpt") if name in old.principals]
    if not principals:
        raise ValueError("No existing operator principal; do not create an identity implicitly")
    for name in principals:
        policy = old.principals[name]
        updates = {
            "approval_mode": "automatic",
            "roots": list(dict.fromkeys(policy.roots + roots)),
            "capabilities": list(
                dict.fromkeys(
                    policy.capabilities
                    + [
                        "policy.inspect",
                        "agent.status",
                        "agent.inspect",
                        "admin.execute",
                        "agent.local_tools",
                        "message.send",
                        "message.read",
                        "message.ack",
                    ]
                )
            ),
            "message_peers": list(
                dict.fromkeys(
                    policy.message_peers + [p for p in ("codex", "grok") if p in old.principals]
                )
            ),
        }
        if full_terminal:
            updates.update(allow_any_executable=True, terminal_roots=["/"])
        pattern = r"(\[principals\." + re.escape(name) + r"\]\n)(.*?)(?=\n\[|\Z)"

        def replace(match, updates=updates):
            body = match[2]
            for key, value in updates.items():
                line = key + " = " + json.dumps(value, ensure_ascii=False)
                body, count = re.subn(
                    r"^" + key + r"\s*=.*$", lambda _, line=line: line, body, flags=re.M
                )
                if not count:
                    body = line + "\n" + body
            return match[1] + body

        text, count = re.subn(pattern, replace, text, flags=re.S)
        if count != 1:
            raise ValueError("Unsupported principal table layout; leave original intact")
    if old.agents.get("grok") and old.agents["grok"].kind == "grok_acp":
        pattern = r"(\[agents\.grok\]\n)(.*?)(?=\n\[|\Z)"

        def grok(match):
            body = re.sub(r"^allow_local_tools\s*=.*\n?", "", match[2], flags=re.M)
            return match[1] + "allow_local_tools = true\n" + body

        text, count = re.subn(pattern, grok, text, flags=re.S)
        if count != 1:
            raise ValueError("Unsupported agent table layout")
    terminal = (
        "[terminal]\nsearch_path = "
        + json.dumps(list(dict.fromkeys(old.terminal.search_path + search_path)))
        + "\nhome = "
        + json.dumps(old.terminal.home or str(Path.home()))
        + "\n"
    )
    if re.search(r"^\[terminal\]", text, re.M):
        text, count = re.subn(
            r"^\[terminal\]\n.*?(?=\n\[|\Z)", lambda _: terminal, text, flags=re.M | re.S
        )
        if count != 1:
            raise ValueError("Unsupported terminal table layout; original retained")
    else:
        text += "\n" + terminal
    new = Config.model_validate(tomllib.loads(text))
    TerminalManager(new.terminal)  # Validate actual runtime prerequisites before any replacement.
    # Bot identities, network/authentication and all queue settings stay unchanged.
    for name in old.principals.keys() - set(principals):
        assert old.principals[name] == new.principals[name]
    for field in (
        "data_dir",
        "credentials_file",
        "host",
        "port",
        "allow_remote",
        "tls_cert",
        "tls_key",
        "allowed_hosts",
        "allowed_origins",
        "messaging",
    ):
        assert getattr(old, field) == getattr(new, field)
    private_directory(backup_dir)
    backup = backup_dir / ("config.before-" + uuid.uuid4().hex + ".toml")
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IMODE(info.st_mode))
    with os.fdopen(fd, "wb") as target:
        target.write(raw)
        target.flush()
        os.fsync(target.fileno())
    backup_parent = os.open(backup_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(backup_parent)
    finally:
        os.close(backup_parent)
    fd, temporary = tempfile.mkstemp(prefix=".development-access-", dir=path.parent)
    try:
        os.fchmod(fd, stat.S_IMODE(info.st_mode))
        with os.fdopen(fd, "wb") as target:
            target.write(text.encode())
            target.flush()
            os.fsync(target.fileno())
        if hashlib.sha256(path.read_bytes()).hexdigest() != before:
            raise ValueError("Concurrent configuration change; original retained")
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {
        "config_before_sha256": before,
        "config_after_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "backup": str(backup),
        "mode": oct(stat.S_IMODE(path.stat().st_mode)),
        "principals": principals,
        "full_terminal": full_terminal,
        "restart_required": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--backup-dir", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--search-path", action="append", default=[])
    parser.add_argument("--full-terminal", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            configure(
                args.config,
                args.backup_dir,
                args.root,
                args.search_path,
                full_terminal=args.full_terminal,
                expected_sha256=args.expected_sha256,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
