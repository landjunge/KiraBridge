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


def _parameters(argv, decision):
    """Read actual bounded CLI options, never the prompt or environment."""
    try:
        if argv.count("--model") != 1:
            raise ValueError("One model setting required")
        model = argv[argv.index("--model") + 1]
        if decision["cli"] == "grok":
            if argv.count("--effort") != 1:
                raise ValueError("One effort setting required")
            effort = argv[argv.index("--effort") + 1]
        else:
            values = [
                arg.split("=", 1)[1] for arg in argv if arg.startswith("model_reasoning_effort=")
            ]
            if len(values) != 1:
                raise ValueError("One effort setting required")
            effort = json.loads(values[0])
    except (ValueError, IndexError):
        raise RoutingError("CLI arguments contain no unambiguous model/effort") from None
    if model != decision["model"] or effort != decision["effort"]:
        raise RoutingError("Actual CLI arguments differ from selected model/effort")
    return {"cli": decision["cli"], "model": model, "effort": effort}


def _start_observation(parameters, evidence):
    observed = (
        isinstance(evidence, dict)
        and evidence.get("spawn_observed") is True
        and type(evidence.get("pid")) is int
        and evidence["pid"] > 0
    )
    return {
        "scope": "local_cli_arguments_and_process_only",
        "spawn_observed": observed,
        "pid": evidence["pid"] if observed else None,
        "spawned_at": evidence.get("spawned_at") if observed else None,
        "confirmed_parameters": parameters if observed else None,
        "matches_selection": True if observed else None,
    }


def _write_private(path, data):
    # Never follow or replace a pre-existing output file; task admission is exclusive.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _capture(state, task_id, output, errors, result):
    first_error = None
    for suffix, data, limit, field in (
        (".stdout", output, 1048576, "output_path"),
        (".stderr", errors, 65536, "stderr_path"),
    ):
        if data is None:
            continue
        if isinstance(data, str):
            data = data.encode()
        if len(data) > limit:
            result["output_truncated"] = True
        path = state / (task_id + suffix)
        try:
            _write_private(path, data[:limit])
            result[field] = str(path)
        except OSError as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error


def launch(source, runtime, task, *, execute=False, probe=True, runner=run_bounded):
    decision = before_delegation(source, runtime, task, probe=probe)
    argv, stdin = command_for(decision, task)
    parameters = _parameters(argv, decision)
    if not execute:
        return {
            **decision,
            "state": "planned",
            "starts_model": False,
            "selected_parameters": parameters,
        }
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
        json.dump(
            {
                **decision,
                "selected_parameters": parameters,
                "state": "admitted",
                "automatic_retry": False,
            },
            stream,
        )
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
    result = {**decision, "selected_parameters": parameters, "automatic_retry": False}
    stage = "lease"
    try:
        if not task.read_only:
            lease_fd = os.open(lease, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(lease_fd)
            locked = True
        stage = "preflight"
        # Re-read authoritative revision at the effect boundary; no stale decision launch.
        matrix, binding = source.load()
        from .router import fingerprint

        if binding != decision["thread_desk"] or fingerprint(matrix) != decision["matrix_sha256"]:
            raise RoutingError("ThreadDesk changed during preflight; new decision required")
        stage = "runner"
        child = runner(
            argv,
            input=stdin,
            cwd=task.cwd,
            timeout=task.timeout_seconds,
            env=subscription_environment(),
        )
        # Exit 0 is transport completion, not accepted work or verified model identity.
        # Preserve observed child exit before any subsequent evidence-file IO.
        result.update(
            state="process_completed" if child.returncode == 0 else "process_failed",
            exit_code=child.returncode,
            native_exit_code=child.returncode,
            output_truncated=getattr(child, "output_truncated", False),
        )
        if hasattr(child, "process_evidence"):
            result["process_evidence"] = child.process_evidence
        result["start_observation"] = _start_observation(
            parameters, getattr(child, "process_evidence", None)
        )
        stage = "output_persist"
        _capture(state, task.task_id, child.stdout or b"", getattr(child, "stderr", b""), result)
        stage = "metadata_parse"
        if child.returncode == 0:
            result.update(native_metadata(decision["cli"], child.stdout, decision["model"]))
    except RoutingError as exc:
        result.update(state="blocked", error=str(exc))
    except (OSError, subprocess.SubprocessError) as exc:
        if isinstance(exc, FileExistsError) and stage == "lease":
            result.update(state="blocked", error="Workspace already leased by this launcher")
        else:
            evidence = getattr(exc, "process_evidence", {})
            if evidence:
                result["process_evidence"] = evidence
                result["start_observation"] = _start_observation(parameters, evidence)
                if evidence.get("native_exit_code") is not None:
                    result["native_exit_code"] = evidence["native_exit_code"]
                result["output_truncated"] = evidence.get("output_truncated", False)
            result.update(
                state="unknown",
                error="Own process outcome uncertain; no automatic retry",
                transport_error={
                    "category": "timeout"
                    if isinstance(exc, subprocess.TimeoutExpired)
                    else "process_transport",
                    "exception_type": evidence.get("exception_type", type(exc).__name__),
                    "stage": evidence.get("stage", stage),
                    "source": "controlled_cli_runner",
                    "native_effect_status": "unknown",
                },
            )
            # No argv or arbitrary exception text; secondary capture IO must not
            # replace the primary error or a known native exit status.
            try:
                _capture(
                    state,
                    task.task_id,
                    getattr(exc, "output", None),
                    getattr(exc, "stderr", None),
                    result,
                )
            except OSError as capture:
                result["transport_error"]["capture_error_type"] = type(capture).__name__
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
