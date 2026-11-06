"""Own new process only; durable at-most-once admission, no session manipulation."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from .evidence import native_metadata
from .hook import before_delegation, command_for, subscription_environment
from .process import run_bounded
from .router import RoutingError


class OutcomeUncertain(RoutingError):
    """The effect boundary was crossed; never label a lost receipt as not started."""


def launch(source, runtime, task, *, execute=False, probe=True, runner=run_bounded):
    decision = before_delegation(source, runtime, task, probe=probe)
    argv, stdin = command_for(decision, task)
    if not execute:
        return {**decision, "state": "planned", "starts_model": False}
    if decision["access_kind"] != "subscription":
        raise RoutingError("This launcher implements only the existing subscription routes")
    state = Path(runtime.state_dir)
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    receipt = state / (task.task_id + ".json")
    # Claim before the process boundary; crash/timeout/unclear submission NEVER retries.
    try:
        fd = os.open(receipt, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise RoutingError("Task ID already admitted; inspect its receipt, never replay") from None
    with os.fdopen(fd, "w") as stream:
        json.dump({**decision, "state": "admitted", "automatic_retry": False}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    # Persist the directory entry as well as the receipt before any model effect.
    directory_fd = os.open(state, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    # Lock the outermost granted root: root/subdir must not become parallel writers.
    roots = [
        Path(root).resolve()
        for root in runtime.allowed_roots
        if Path(task.cwd).resolve().is_relative_to(Path(root).resolve())
    ]
    workroot = min(roots, key=lambda root: len(root.parts))
    lease = state / ("cwd-" + hashlib.sha256(str(workroot).encode()).hexdigest() + ".lock")
    locked = False
    result = {**decision, "automatic_retry": False}
    try:
        if not task.read_only:
            lease_fd = os.open(lease, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(lease_fd)
            locked = True
        # Re-read authoritative revision at the effect boundary; no stale decision launch.
        matrix, binding = source.load()
        from .router import fingerprint

        if binding != decision["thread_desk"] or fingerprint(matrix) != decision["matrix_sha256"]:
            raise RoutingError("ThreadDesk changed during preflight; new decision required")
        child = runner(
            argv,
            input=stdin,
            cwd=task.cwd,
            timeout=task.timeout_seconds,
            env=subscription_environment(),
        )
        # Exit 0 is transport completion, not accepted work or verified model identity.
        output = state / (task.task_id + ".stdout")
        output.write_bytes(child.stdout or b"")
        output.chmod(0o600)
        errors = state / (task.task_id + ".stderr")
        errors.write_bytes(getattr(child, "stderr", b"") or b"")
        errors.chmod(0o600)
        result.update(
            state="process_completed" if child.returncode == 0 else "process_failed",
            exit_code=child.returncode,
            output_path=str(output),
            stderr_path=str(errors),
            output_truncated=getattr(child, "output_truncated", False),
        )
        if child.returncode == 0:
            result.update(native_metadata(decision["cli"], child.stdout, decision["model"]))
    except FileExistsError:
        result.update(state="blocked", error="Workspace already leased by this launcher")
    except RoutingError as exc:
        result.update(state="blocked", error=str(exc))
    except (OSError, subprocess.SubprocessError) as exc:
        result.update(
            state="unknown",
            error="Own process outcome uncertain; no automatic retry",
            transport_error={
                "category": "timeout"
                if isinstance(exc, subprocess.TimeoutExpired)
                else "process_transport",
                "exception_type": type(exc).__name__,
                "source": "controlled_cli_runner",
                "native_effect_status": "unknown",
            },
        )
    finally:
        # Unknown may still have living child processes; preserve the lease.
        if locked and result.get("state") != "unknown":
            lease.unlink()
    try:
        temp = receipt.with_suffix(".tmp")
        temp.write_text(json.dumps(result, indent=2))
        temp.chmod(0o600)
        temp.replace(receipt)
    except OSError:
        raise OutcomeUncertain(
            "Final receipt could not be saved; inspect admitted task; no replay"
        ) from None
    return result
