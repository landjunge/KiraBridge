"""One launchd contract for the linked ChatGPT tunnel; never edits account secrets."""

from __future__ import annotations

import hashlib
import os
import plistlib
import re
import stat
import uuid
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError
from kirabridge.private_files import write_private

LABEL = "com.kirabridge.chatgpt"
RESTART_INTERVAL = 30


def service_definition(config_path: Path, binary: str) -> dict:
    if not Path(binary).is_absolute() or not config_path.is_absolute():
        raise BridgeError("service_conflict", "ChatGPT service paths must be absolute")
    values = [binary, str(config_path.parent / "tunnel")]
    if any(any(ord(char) < 32 for char in value) for value in values):
        raise BridgeError("service_conflict", "ChatGPT service paths contain control characters")
    return {
        "Label": LABEL,
        "RunAtLoad": True,
        # tunnel-client can exit zero when its stdio child fails during boot.
        "KeepAlive": True,
        "ThrottleInterval": RESTART_INTERVAL,
        "Umask": 0o077,
        "ProgramArguments": [binary, "run", "--profile-dir", values[1], "--profile", "kirabridge"],
    }


def _read_owned(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise BridgeError("service_conflict", "Unsafe ChatGPT service file preserved")
        content = source.read(65537)
    if len(content) > 65536:
        raise BridgeError("service_conflict", "Oversized ChatGPT service file preserved")
    return content


def loaded_service_matches(output: str, definition: dict) -> bool:
    """Do not unload an unrelated job that happens to use our label."""
    program = re.search(r"(?m)^\s*program = (.+)$", output)
    arguments = re.search(r"(?m)^\s*arguments = \{\n(.*?)^\s*\}", output, re.S)
    return bool(
        program
        and program[1].strip() == definition["ProgramArguments"][0]
        and arguments
        and [line.strip() for line in arguments[1].splitlines() if line.strip()]
        == definition["ProgramArguments"]
    )


def loaded_recovery_matches(output: str) -> bool:
    """A current plist does not prove launchd reloaded a previous migration."""
    properties = re.search(r"(?m)^\s*properties = (.+)$", output)
    interval = re.search(r"(?m)^\s*minimum runtime = (\d+)\s*$", output)
    return bool(
        properties
        and "keepalive" in {item.strip() for item in properties[1].split("|")}
        and interval
        and int(interval[1]) == RESTART_INTERVAL
    )


def ensure_chatgpt_service(
    config_path: Path,
    binary: str,
    *,
    create: bool = False,
    loaded_output: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Create or migrate only our exact known definition; caller owns launchctl reload.

    The backup is byte-exact and remains beside the plist. No profile, credential,
    existing runtime or launchd job is changed here. Existing custom definitions
    are rejected before any write, including extra launchd execution options.
    """
    definition = service_definition(config_path, binary)
    path = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    result = {
        "path": str(path),
        "changed": False,
        "backup": None,
        "reload_required": loaded_output is not None and not loaded_recovery_matches(loaded_output),
    }
    if path.parent.is_symlink():
        raise BridgeError("service_conflict", "Symlink LaunchAgents directory preserved")
    if path.parent.exists():
        info = path.parent.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise BridgeError("service_conflict", "Unsafe LaunchAgents directory preserved")
    old = None
    try:
        old = _read_owned(path)
    except FileNotFoundError:
        if not create:
            return result
    except OSError as exc:
        raise BridgeError("service_conflict", "Unsafe ChatGPT service file preserved") from exc
    if old is not None:
        try:
            actual = plistlib.loads(old)
        except (ValueError, TypeError, plistlib.InvalidFileException) as exc:
            raise BridgeError("service_conflict", "Invalid ChatGPT service file preserved") from exc
        legacy = {k: v for k, v in definition.items() if k != "ThrottleInterval"}
        legacy["KeepAlive"] = {"SuccessfulExit": False}
        if actual not in (legacy, definition):
            raise BridgeError("service_conflict", "Custom ChatGPT service definition preserved")
        if loaded_output is not None and not loaded_service_matches(loaded_output, actual):
            raise BridgeError("service_conflict", "Loaded ChatGPT job differs; preserved")
        if actual == definition:
            return result
        digest = hashlib.sha256(old).hexdigest()
        backup = path.with_name(path.name + ".backup-" + digest[:16])
        if backup.exists() or backup.is_symlink():
            if _read_owned(backup) != old:
                raise BridgeError("service_conflict", "ChatGPT service backup differs; preserved")
        elif not dry_run:
            write_private(backup, old)
        result.update(backup=str(backup), previous_sha256=digest)
    elif loaded_output is not None:
        raise BridgeError("service_conflict", "Unrecorded loaded ChatGPT job preserved")
    if dry_run:
        return {**result, "changed": True, "reload_required": loaded_output is not None}
    path.parent.mkdir(parents=True, exist_ok=True)
    info = path.parent.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise BridgeError("service_conflict", "Unsafe LaunchAgents directory preserved")
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex)
    try:
        write_private(temporary, plistlib.dumps(definition))
        if old is None:
            # Exclusive link refuses a concurrently created service definition.
            os.link(temporary, path)
        else:
            if _read_owned(path) != old:
                raise BridgeError("service_conflict", "ChatGPT service changed during migration")
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        **result,
        "changed": True,
        "reload_required": loaded_output is not None,
        "installed_sha256": hashlib.sha256(plistlib.dumps(definition)).hexdigest(),
    }


def restore_chatgpt_service(update: dict) -> None:
    """Restore only this failed migration, never a database or account profile."""
    path = Path(update["path"])
    backup = update.get("backup")
    if not update.get("changed") or not backup:
        return
    if hashlib.sha256(_read_owned(path)).hexdigest() != update.get("installed_sha256"):
        raise BridgeError("service_conflict", "ChatGPT service changed after migration; preserved")
    data = _read_owned(Path(backup))
    if hashlib.sha256(data).hexdigest() != update.get("previous_sha256"):
        raise BridgeError("service_conflict", "ChatGPT rollback backup changed")
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex)
    try:
        write_private(temporary, data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
