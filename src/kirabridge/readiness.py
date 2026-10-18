"""Read-only prerequisites for one authenticated identity, never a workflow certificate."""

from __future__ import annotations

import hashlib
import os
import stat
import uuid
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
    operations: list[str] = Field(default_factory=list, max_length=16)
    workflow_id: str | None = Field(default=None, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")


def runtime_snapshot(config: Config) -> dict:
    # Capture once on daemon construction; editing the installed tree does not change
    # this assertion about the source tree observed at startup.
    root = Path(__file__).parent
    manifest = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*.py"))
    }
    return {
        "instance_id": uuid.uuid4().hex,
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

    def operation(name):
        from kirabridge.bridge_core.bridge import INPUTS

        if name not in INPUTS:
            raise BridgeError("unknown_operation", "Unknown operation")
        bridge.security.principal(principal, name)
        if name.startswith("threaddesk."):
            bridge.threaddesk.check_configuration()
        if name in {"clipboard.read", "clipboard.write"}:
            bridge.clipboard.platform.clipboard_command(write=name == "clipboard.write")

    paths = [{"path": p, **_probe(lambda p=p: file(p))} for p in requirements.read_paths]
    programs = [{"path": p, **_probe(lambda p=p: executable(p))} for p in requirements.executables]
    operations = [
        {"operation": p, **_probe(lambda p=p: operation(p))} for p in requirements.operations
    ]
    roots = [
        {"path": p, **_probe(lambda p=p: directory(p))}
        for p in dict.fromkeys(policy.roots + policy.read_roots)
    ]
    health = bridge.health(principal)
    requested = bool(paths or programs or operations)
    result = {
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
        "operation_checks": operations,
        "workflow_id": requirements.workflow_id,
        "requested_prerequisites_ready": (
            health["dispatcher_active"] and all(x["ok"] for x in paths + programs + operations)
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
    if requested and not result["requested_prerequisites_ready"]:
        from kirabridge.diagnostics import rejection_report

        failures = [x for x in paths + programs + operations if not x["ok"]]
        code = failures[0]["code"] if failures else "dispatcher_unavailable"
        result["diagnostic"] = rejection_report(
            bridge.runtime,
            "workflow.preflight",
            code,
            workflow_id=requirements.workflow_id,
        )
    if requirements.workflow_id:
        from kirabridge.diagnostics import AuditObserver, compact_checks

        observer = AuditObserver(bridge.config, principal, bridge.runtime, bridge.store)
        result["audit_recorded"] = observer(
            "workflow.preflight",
            {
                "workflow_id": requirements.workflow_id,
                "checks": compact_checks(paths + programs + operations),
                "outcome": "ready" if result["requested_prerequisites_ready"] else "not_ready",
            },
        )
        result["audit_storage"] = observer.status()
        if not result["audit_recorded"]:
            from kirabridge.diagnostics import rejection_report

            result["requested_prerequisites_ready"] = False
            result["diagnostic"] = rejection_report(
                bridge.runtime,
                "workflow.preflight",
                "diagnostic_recording_unavailable",
                workflow_id=requirements.workflow_id,
            )
    return result


def task_preflight(bridge, task: dict) -> dict:
    """Actual task prerequisites, before any content access or process start.

    The real manager still repeats its descriptor/permission checks at use time.
    No change to request hashes, grants, task states or historical idempotency.
    """
    from kirabridge.diagnostics import compact_checks, runtime_ref

    operation, args, principal = task["operation"], task["args"], task["principal"]
    policy = bridge.security.principal(principal, operation)
    roots = policy.roots + (policy.read_roots if operation in {"file.read", "file.list"} else [])
    scope = PathScope(roots, excluded=[str(bridge.config.state_path)])
    checks = []

    def check(kind, path, action):
        checks.append({"kind": kind, "path": path, **_probe(action)})

    if operation == "file.read":
        check("read_path", args["path"], lambda: _file(scope, args["path"]))
    elif operation == "file.list":
        check("directory", args["path"], lambda: _directory(scope, args["path"]))
    elif operation.startswith("file."):
        for path in [args["path"]] + ([args["destination"]] if operation == "file.move" else []):

            def parent(path=path):
                with scope.parent(path):
                    pass

            check("mutation_parent", path, parent)
    elif operation.startswith("threaddesk."):
        check("threaddesk_endpoint", "configured_threaddesk", bridge.threaddesk.check_configuration)
    elif operation in {"terminal.execute", "agent.execute"}:
        if operation == "terminal.execute":
            executable = args["argv"][0]
            check(
                "executable", executable, lambda: check_executable(executable, policy.executables)
            )
        check("cwd", args["cwd"], lambda: _directory(scope, args["cwd"]))
    return {
        "ready": all(c["ok"] for c in checks),
        "checks": compact_checks(checks),
        "operation": operation,
        "runtime": runtime_ref(bridge.runtime),
    }
