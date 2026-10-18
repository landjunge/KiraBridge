"""Explicit owned CLI stop-only assembly; not a provider-cost enforcement claim."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from kirabridge.bridge_core.models import BridgeError, UncertainExecution, digest

_BINDING = ContextVar("owned_workflow_process_binding", default=None)


def stop_observation(store, metadata):
    """Existing audit evidence survives a late save of stale turn metadata.

    This reports an observed committed barrier, not a fresh lock acquisition or
    process exit. A later PENDING/unknown observation cannot negate EFFECTIVE.
    """
    result = {
        "basis": "existing_stop_audit_observation",
        "status": "not_observed",
        "coverage": "unknown",
    }
    try:
        row = store.db.execute(
            "SELECT seq,at,kind,principal,task_id,previous,hash,substr(metadata,1,4097) metadata "
            "FROM audit WHERE kind='workflow.stop' AND principal=? "
            "AND json_extract(metadata,'$.binding_ref')=? "
            "ORDER BY (json_extract(metadata,'$.further_dispatch_blocked')=1) DESC,"
            "seq DESC LIMIT 1",
            (metadata["principal"], metadata["id"]),
        ).fetchone()
        if row is None or len(row["metadata"]) > 4096:
            return result
        record = json.loads(row["metadata"])
        original = {key: row[key] for key in ("at", "kind", "principal", "task_id", "previous")}
        original["metadata"] = record
        if (
            digest(original) != row["hash"]
            or record.get("status") not in {"EFFECTIVE", "PENDING", "UNKNOWN"}
            or type(record.get("further_dispatch_blocked")) is not bool
            or (record["status"] == "EFFECTIVE") != record["further_dispatch_blocked"]
        ):
            return result
        result.update(
            status=record["status"],
            further_dispatch_blocked=record["further_dispatch_blocked"],
            audit_seq=row["seq"],
            audit_hash=row["hash"],
            process_exit_current="unknown",
            external_effect="unknown",
        )
        if record.get("control_mode") == "stop_only":
            result["control_mode"] = "stop_only"
    except (sqlite3.Error, ValueError, TypeError):
        return result
    return result


@dataclass(frozen=True)
class _Binding:
    controller: object
    principal: str
    task_id: str
    identity: object
    owner_task: object


async def _finish_thread(function, *args):
    """Do not abandon a thread holding a file lock when the coroutine is cancelled."""
    pending = asyncio.create_task(asyncio.to_thread(function, *args))
    cancelled = False
    while not pending.done():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError:
            cancelled = True
    value = pending.result()
    if cancelled:
        raise asyncio.CancelledError
    return value


@asynccontextmanager
async def process_dispatch(task_id, principal):
    binding = _BINDING.get()
    if binding is None:
        yield
        return
    if (
        binding.principal != principal
        or binding.task_id != task_id
        or binding.owner_task is not asyncio.current_task()
    ):
        raise BridgeError("workflow_process_owner", "Dispatch does not match the owned turn")
    manager = binding.controller.control.process_start(binding.identity)
    entry = asyncio.create_task(asyncio.to_thread(manager.__enter__))
    try:
        admission = await asyncio.shield(entry)
    except BaseException as exc:
        # to_thread cannot be cancelled; wait for its bounded acquisition, then
        # release a context which may have entered after caller cancellation.
        try:
            while not entry.done():
                try:
                    await asyncio.shield(entry)
                except asyncio.CancelledError:
                    pass
            entry.result()
        except BaseException:
            pass
        else:
            try:
                await _finish_thread(manager.__exit__, type(exc), exc, exc.__traceback__)
            except BaseException:
                pass
        raise
    try:
        if admission.get("start_allowed") is not True:
            raise BridgeError(
                "workflow_start_blocked", "Owned turn is stopped or already attempted"
            )
        yield
    except BaseException as exc:
        try:
            await _finish_thread(manager.__exit__, type(exc), exc, exc.__traceback__)
        except BaseException:
            raise UncertainExecution(
                "workflow_start_unknown", "Owned spawn/barrier outcome unknown"
            ) from None
        raise
    else:
        try:
            await _finish_thread(manager.__exit__, None, None, None)
        except BaseException:
            raise UncertainExecution(
                "workflow_start_unknown", "Owned spawn/barrier outcome unknown"
            ) from None


class WorkflowControlAdapter:
    """Construct only in the trusted host, never from task arguments or a caller flag.

    TollGate is optional. The operator must pin/install the reviewed source which
    includes process_start; absence is a closed prerequisite, not a fallback grant.
    """

    def __init__(self, bridge, control, *, project_id, actor_id, consumer_id):
        try:
            from tollgate.workflow_control import AttemptIdentity, WorkflowControl, WorkflowScope
        except ImportError:
            raise BridgeError(
                "workflow_control_unavailable", "Reviewed TollGate assembly missing"
            ) from None
        if (
            not isinstance(control, WorkflowControl)
            or not hasattr(control, "process_start")
            or control.registered_process_actors.get(actor_id) != consumer_id
        ):
            raise BridgeError(
                "workflow_control_unavailable", "Trusted process adapter not registered"
            )
        WorkflowScope(project_id, "validate")
        self.bridge, self.control = bridge, control
        self.project_id, self.actor_id, self.consumer_id = project_id, actor_id, consumer_id
        self.Scope, self.Identity = WorkflowScope, AttemptIdentity

    def scope(self, metadata):
        return self.Scope(self.project_id, metadata["id"])

    @contextmanager
    def bind_turn(self, task, metadata):
        principal = task["principal"]
        if metadata.get("control_mode", "standalone") not in {"standalone", "stop_only"}:
            raise BridgeError(
                "workflow_control_mode", "Bounded control cannot fall back to stop-only"
            )
        current = self.bridge.handoffs.get(principal, metadata["handoff_id"], metadata["revision"])
        if current.get("control_mode", "standalone") not in {"standalone", "stop_only"}:
            raise BridgeError(
                "workflow_control_mode", "Bounded control cannot fall back to stop-only"
            )
        actual = self.bridge.store.get(task["id"], principal)
        request_hash = self.bridge.store.db.execute(
            "SELECT request_hash FROM tasks WHERE id=? AND principal=?", (task["id"], principal)
        ).fetchone()[0]
        if (
            current["id"] != metadata["id"]
            or current["last_task_id"] != task["id"]
            or metadata["principal"] != principal
            or actual["receipt"] != task["receipt"]
            or actual["state"] not in {"accepted", "running"}
            or actual["operation"] != task["operation"]
            or actual["operation"] not in {"handoff.start", "handoff.answer"}
        ):
            raise BridgeError("workflow_process_owner", "No exact owned turn binding")
        identity = self.Identity(
            self.scope(metadata),
            current["original_task_id"],
            self.actor_id,
            self.consumer_id,
            "kbturn_" + digest([task["id"], task["receipt"], request_hash]),
            request_hash,
            parent_task_id=current["first_task_id"],
        )
        metadata["control_mode"] = "stop_only"
        with self.bridge.store.transaction():
            self.bridge.handoffs.save(
                metadata, task_id=task["id"], event="handoff.control_attached"
            )
        token = _BINDING.set(
            _Binding(self, principal, task["id"], identity, asyncio.current_task())
        )
        try:
            yield
        finally:
            _BINDING.reset(token)

    async def stop(self, principal, handoff_id, revision, stop_id, *, task_id=None):
        self.bridge.security.principal(principal, "task.cancel")
        self.bridge.security.principal(principal, "process.terminate")
        if type(stop_id) is not str or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", stop_id) is None:
            raise BridgeError("invalid_workflow_stop", "Use a bounded stop identifier")
        if task_id is not None:
            if type(task_id) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id) is None:
                raise BridgeError("invalid_workflow_stop", "Use an owned stop task identifier")
            stop_task = self.bridge.store.get(task_id, principal)
            if (
                stop_task["operation"] != "workflow.stop"
                or stop_task["state"] not in {"accepted", "running"}
                or any(
                    stop_task["args"].get(key) != value
                    for key, value in (
                        ("handoff_id", handoff_id),
                        ("revision", revision),
                        ("stop_id", stop_id),
                    )
                )
            ):
                raise BridgeError("invalid_workflow_stop", "No exact active owned stop task")
        metadata = self.bridge.handoffs.get(principal, handoff_id, revision)
        scope = self.scope(metadata)
        try:
            barrier = await asyncio.to_thread(self.control.stop, scope, stop_id)
        except Exception:
            barrier = {
                "status": "UNKNOWN",
                "further_dispatch_blocked": False,
                "abort_confirmed": False,
            }
        pending = self.bridge.store.db.execute(
            "SELECT id FROM tasks WHERE principal=? AND state IN ('created','queued') "
            "AND operation IN ('handoff.start','handoff.answer') "
            "AND json_extract(args,'$.handoff_id')=? AND json_extract(args,'$.revision')=? "
            "ORDER BY created,id LIMIT 101",
            (principal, handoff_id, revision),
        ).fetchall()
        cancelled, conflicts = 0, 0
        for row in pending[:100]:
            try:
                self.bridge.tasks.cancel_queued(principal, row[0])
                cancelled += 1
            except BridgeError:
                conflicts += 1
        processes, inspection_failures = [], 0
        owned_sessions = [
            (task_id, session)
            for task_id, session in self.bridge.terminal.sessions.items()
            if session.principal == principal
        ]
        for process_task_id, _session in owned_sessions[:256]:
            try:
                task = self.bridge.store.get(process_task_id, principal)
            except BridgeError:
                inspection_failures += 1
                continue
            args = task["args"]
            if (
                task["operation"] not in {"handoff.start", "handoff.answer"}
                or args.get("handoff_id") != handoff_id
                or args.get("revision") != revision
            ):
                continue
            try:
                receipt = await self.bridge.terminal.terminate(principal, process_task_id)
                processes.append(
                    {
                        "task_id": process_task_id,
                        "status": "exit_observed"
                        if receipt["exit_code"] is not None
                        else "termination_requested",
                    }
                )
            except Exception:
                processes.append({"task_id": process_task_id, "status": "unknown"})
        result = {
            "control_mode": "stop_only",
            "cost_kind": "unknown",
            "hard_cost_cap": False,
            "barrier": barrier,
            "queued": {"cancelled": cancelled, "raced": conflicts, "truncated": len(pending) > 100},
            "process": {
                "items": processes,
                "coverage": "owned_registered_processes_only",
                "status": "observed" if processes else "not_observed",
                "inspection_failures": inspection_failures,
                "truncated": len(owned_sessions) > 256,
            },
            "external_effect": "unknown",
            "project_completion_verified": False,
        }
        with self.bridge.store.transaction():
            evidence = {
                "binding_ref": metadata["id"],
                "control_mode": "stop_only",
                "project_id": scope.project_id,
                "workflow_id": scope.workflow_id,
                "control_ref": digest(
                    {"project_id": scope.project_id, "workflow_id": scope.workflow_id}
                ),
                "original_task_id": metadata["original_task_id"],
                "status": barrier["status"],
                "stop_state": barrier["status"],
                "further_dispatch_blocked": barrier["further_dispatch_blocked"],
                "owned_process_exits_observed": sum(
                    p["status"] == "exit_observed" for p in processes
                ),
                "cost_kind": "unknown",
                "hard_cost_cap": False,
            }
            if task_id is not None:
                evidence["bridge_task_id"] = task_id
            if type(barrier.get("barrier_seq")) is int and barrier["barrier_seq"] >= 0:
                evidence["barrier_seq"] = barrier["barrier_seq"]
            self.bridge.store.audit(
                "workflow.stop",
                principal,
                task_id,
                evidence,
            )
        return result
