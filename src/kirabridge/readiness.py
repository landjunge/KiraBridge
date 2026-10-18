"""Read-only prerequisites for one authenticated identity, never a workflow certificate."""

from __future__ import annotations

import hashlib
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field

from kirabridge import __version__
from kirabridge.bridge_core.config import Config
from kirabridge.bridge_core.models import BridgeError, Input, digest
from kirabridge.filesystem_manager import PathScope
from kirabridge.terminal_manager import check_executable


class ReadinessInput(Input):
    read_paths: list[str] = Field(default_factory=list, max_length=16)
    executables: list[str] = Field(default_factory=list, max_length=16)


def runtime_snapshot(config: Config) -> dict:
    # Capture once on daemon construction; editing the installed tree does not change
    # this assertion about the source tree observed at startup.
    root = Path(__file__).parent
    manifest = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*.py"))
    }
    return {
        "version": __version__,
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "config_path": config._source_path,
        "config_sha256": config._source_sha256,
        "effective_config_sha256": digest(config.model_dump()),
        "source_tree_sha256": digest(manifest),
        "source_file_count": len(manifest),
        "source_package_path": str(root),
        "source_scope": "package Python files observed at startup; no remote attestation",
    }


def _probe(action) -> dict:
    try:
        action()
        return {"ok": True, "code": "available"}
    except BridgeError as exc:
        return {"ok": False, "code": exc.code}
    except FileNotFoundError:
        return {"ok": False, "code": "path_missing"}
    except OSError:
        return {"ok": False, "code": "path_unavailable"}


def _file(scope: PathScope, path: str) -> None:
    # Same descriptor/no-follow boundary as file.read; inspect regularity/access,
    # without returning contents or writing an audit/task/queue entry.
    with scope.parent(path) as (parent, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise BridgeError("file_type", "Only regular files can be read")
        finally:
            os.close(fd)


def _directory(scope: PathScope, path: str) -> None:
    with scope.directory(path):
        pass


def readiness(bridge, principal: str, requirements: ReadinessInput) -> dict:
    policy = bridge.security.principal(principal, "bridge.health")
    scope = PathScope(policy.roots + policy.read_roots, excluded=[str(bridge.config.state_path)])

    def file(path):
        bridge.security.principal(principal, "file.read")
        _file(scope, path)

    def directory(path):
        if not {"file.read", "file.list"}.intersection(policy.capabilities):
            raise BridgeError("forbidden", "File capability not granted")
        _directory(scope, path)

    def executable(path):
        bridge.security.principal(principal, "terminal.execute")
        check_executable(path, policy.executables)

    paths = [{"path": p, **_probe(lambda p=p: file(p))} for p in requirements.read_paths]
    programs = [{"path": p, **_probe(lambda p=p: executable(p))} for p in requirements.executables]
    roots = [
        {"path": p, **_probe(lambda p=p: directory(p))}
        for p in dict.fromkeys(policy.roots + policy.read_roots)
    ]
    health = bridge.health(principal)
    requested = bool(paths or programs)
    return {
        "principal": principal,
        "runtime": bridge.runtime,
        "dispatcher_active": health["dispatcher_active"],
        "approval_mode": policy.approval_mode,
        "roots": policy.roots,
        "read_roots": policy.read_roots,
        "allowed_executables": policy.executables,
        "root_checks": roots,
        "read_path_checks": paths,
        "executable_checks": programs,
        "requested_prerequisites_ready": (
            health["dispatcher_active"] and all(x["ok"] for x in paths + programs)
        )
        if requested
        else None,
        "scope": "Only requested prerequisites at this instant; no process is started, no file "
        "content is returned. No complete workflow, tunnel, ChatGPT, or future success claim. "
        "automatic approval does not extend roots or executable permissions.",
        "remediation": "path_denied: use file.read inside configured roots/read_roots; "
        "missing roots/config drift: local operator must correct policy and reload safely. "
        "executable_denied: use file tools for file access; no interpreter workaround.",
    }
