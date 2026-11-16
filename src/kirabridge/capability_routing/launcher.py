"""Own new process only; exclusive admission and conservative result reconciliation."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from .evidence import native_metadata
from .hook import before_delegation, command_for, subscription_environment
from .process import run_bounded
from .router import RoutingError, fingerprint, select


class OutcomeUncertain(RoutingError):
    """The runner boundary was crossed; never label lost evidence as not started."""


def _identity(path):
    info = path.lstat()
    return info.st_dev, info.st_ino


def _write_new(path, payload):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _save_result(receipt, identity, result, *, staging_suffix=".tmp"):
    temp = receipt.with_suffix(staging_suffix)
    _write_new(temp, json.dumps(result, indent=2).encode())
    if _identity(receipt) != identity:
        raise RoutingError("Admission receipt owner changed")
    temp.replace(receipt)
    _sync_directory(receipt.parent)


def launch(source, runtime, task, *, execute=False, probe=True, runner=run_bounded):
    if execute and not probe:
        raise RoutingError("Execution requires current native version/authentication probes")
    decision = before_delegation(source, runtime, task, probe=probe)
    argv, stdin = command_for(decision, task)
    if not execute:
        return {**decision, "state": "planned", "starts_model": False}
    if decision["access_kind"] != "subscription":
        raise RoutingError("This launcher implements only the existing subscription routes")
    cwd = Path(task.cwd).resolve(strict=True)
    roots = [
        Path(root).resolve(strict=True)
        for root in runtime.allowed_roots
        if cwd.is_relative_to(Path(root).resolve(strict=True))
    ]
    if not roots:
        raise RoutingError("Task cwd no longer matches a granted root")
    workroot = min(roots, key=lambda root: len(root.parts))
    state = Path(runtime.state_dir)
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = state.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RoutingError("Existing admission directory must be private and owned")
    receipt = state / (task.task_id + ".json")
    lease = state / ("cwd-" + hashlib.sha256(str(workroot).encode()).hexdigest() + ".lock")
    result = {
        **decision,
        "automatic_retry": False,
        "state": "admitted",
        "effect_boundary_crossed": False,
        "process_exit_confirmed": False,
    }
    try:
        fd = os.open(receipt, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        raise RoutingError("Task ID already admitted; inspect its receipt, never replay") from None
    opened = os.fstat(fd)
    identity = (opened.st_dev, opened.st_ino)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(json.dumps(result).encode())
            stream.flush()
            os.fsync(stream.fileno())
        _sync_directory(state)
    except BaseException as error:
        result.update(
            state="blocked",
            error="Admission persistence failed; no process invoked",
            error_type=type(error).__name__,
        )
        try:
            _save_result(receipt, identity, result)
        except (OSError, RoutingError):
            pass  # O_EXCL original remains protected even if the update cannot be confirmed.
        if not isinstance(error, Exception):
            raise
        raise RoutingError(
            "Admission persistence failed; no process invoked; inspect original"
        ) from None
    lease_identity = None
    interrupted = None
    phase = "pre_process"
    try:
        if not task.read_only:
            try:
                lease_fd = os.open(
                    lease, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
                )
            except FileExistsError:
                raise RoutingError("Workspace already leased by this launcher") from None
            with os.fdopen(lease_fd, "wb"):
                lease_identity = _identity(lease)
        matrix, binding = source.load()
        if (
            binding != decision["thread_desk"]
            or fingerprint(matrix) != decision["matrix_sha256"]
            or fingerprint(runtime) != decision["runtime_sha256"]
        ):
            raise RoutingError("ThreadDesk/runtime changed during preflight; new decision required")
        select(matrix, runtime, task)  # Time can expire even while all pinned bytes remain equal.
        if Path(task.cwd).resolve(strict=True) != cwd:
            raise RoutingError("Task cwd changed after preflight")
        requested_exe = decision.get("requested_executable", decision["executable"])
        if str(Path(requested_exe).resolve(strict=True)) != decision["executable"]:
            raise RoutingError("Executable target changed after preflight")
        result["effect_boundary_crossed"] = (
            True  # Conservative boundary, not a provider-start claim.
        )
        child = runner(
            argv,
            input=stdin,
            cwd=str(cwd),
            timeout=task.timeout_seconds,
            env=subscription_environment(decision["cli"]),
        )
        phase = "result_persistence"
        owned_pid = getattr(child, "owned_process_pid", None)
        if type(owned_pid) is int and owned_pid > 0:
            result["owned_process_pid"] = owned_pid
        result["process_exit_confirmed"] = type(child.returncode) is int
        if not result["process_exit_confirmed"]:
            raise OutcomeUncertain("Runner did not confirm child exit")
        output = state / (task.task_id + ".stdout")
        errors = state / (task.task_id + ".stderr")
        _write_new(output, child.stdout or b"")
        _write_new(errors, getattr(child, "stderr", b"") or b"")
        result.update(
            state="process_completed" if child.returncode == 0 else "process_failed",
            exit_code=child.returncode,
            output_path=str(output),
            stderr_path=str(errors),
            output_truncated=getattr(child, "output_truncated", False),
        )
        if child.returncode == 0:
            phase = "native_metadata"
            result.update(native_metadata(decision["cli"], child.stdout, decision["model"]))
    except BaseException as error:
        if result["effect_boundary_crossed"]:
            result.update(
                state="unknown", error="Own process/result outcome uncertain; no automatic retry"
            )
            result["process_exit_confirmed"] |= (
                getattr(error, "owned_process_exit_confirmed", False) is True
            )
        else:
            result.update(state="blocked", error="Pre-process guard failed; no process invoked")
        result["error_type"] = type(error).__name__
        result["failure_phase"] = phase
        owned_pid = getattr(error, "owned_process_pid", None)
        if type(owned_pid) is int and owned_pid > 0:
            result["owned_process_pid"] = owned_pid
        if not isinstance(error, Exception):
            interrupted = error
    finally:
        if lease_identity and (
            not result["effect_boundary_crossed"] or result["process_exit_confirmed"]
        ):
            try:
                if _identity(lease) != lease_identity:
                    raise RoutingError("Lease owner changed")
                lease.unlink()
            except (OSError, RoutingError) as error:
                result.update(
                    state="unknown" if result["effect_boundary_crossed"] else "blocked",
                    lease_release_error=type(error).__name__,
                )
    try:
        _save_result(receipt, identity, result)
    except BaseException as error:
        result.update(
            state="unknown" if result["effect_boundary_crossed"] else "blocked",
            error="Final receipt persistence interrupted; inspect original evidence",
            error_type=type(error).__name__,
            failure_phase="final_receipt_persistence",
        )
        # One journal-only recovery, not a process retry. Preserve a partial .tmp
        # and use a separate exclusive stage so evidence is never overwritten.
        try:
            _save_result(receipt, identity, result, staging_suffix=".failure.tmp")
        except BaseException:
            if result["effect_boundary_crossed"]:
                raise OutcomeUncertain(
                    "Final receipt not confirmed after process boundary; no replay"
                ) from None
            raise RoutingError(
                "No process invoked; final receipt not confirmed; inspect original"
            ) from None
        if not isinstance(error, Exception):
            raise
        if result["effect_boundary_crossed"]:
            raise OutcomeUncertain(
                "Final persistence failed; UNKNOWN receipt saved; no replay"
            ) from None
        raise RoutingError("No process invoked; guard failure receipt saved") from None
    if interrupted:
        raise interrupted
    return result
