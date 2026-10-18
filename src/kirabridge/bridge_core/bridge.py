from __future__ import annotations

import asyncio
from typing import Any

from pydantic import ValidationError

from kirabridge import API_VERSION, LOCAL_APPROVAL_URL, __version__
from kirabridge.agent_manager import AgentManager
from kirabridge.bridge_core.config import Config
from kirabridge.bridge_core.models import (
    AgentInput,
    BridgeError,
    ClipboardRead,
    ClipboardWrite,
    EmptyInput,
    HandoffAnswerInput,
    HandoffDecisionInput,
    HandoffInboxInput,
    HandoffIssueInput,
    HandoffReference,
    HandoffStartInput,
    ImageInput,
    MoveInput,
    ObservationReadInput,
    PathInput,
    ProcessInput,
    ReadInput,
    State,
    TaskRequest,
    TerminalInput,
    ThreadDeskKnowledgeInput,
    ThreadDeskManageInput,
    ThreadDeskReadInput,
    WriteInput,
)
from kirabridge.clipboard_manager import ClipboardManager
from kirabridge.filesystem_manager import FilesystemManager, PathScope
from kirabridge.image_manager import ImageManager
from kirabridge.message_manager import MessageManager
from kirabridge.message_manager.receiver import MessageReceiver
from kirabridge.process_manager import ProcessManager
from kirabridge.security_manager import SecurityManager
from kirabridge.task_manager.manager import TaskManager
from kirabridge.task_manager.store import Store
from kirabridge.terminal_manager import TerminalManager

INPUTS = {
    "terminal.execute": TerminalInput,
    "file.read": ReadInput,
    "file.image": ImageInput,
    "file.list": PathInput,
    "file.write": WriteInput,
    "file.mkdir": PathInput,
    "file.move": MoveInput,
    "file.delete": PathInput,
    "clipboard.read": ClipboardRead,
    "clipboard.write": ClipboardWrite,
    "clipboard.info": EmptyInput,
    "process.list": EmptyInput,
    "process.inspect": ProcessInput,
    "process.terminate": ProcessInput,
    "agent.execute": AgentInput,
    "handoff.issue": HandoffIssueInput,
    "handoff.start": HandoffStartInput,
    "handoff.answer": HandoffAnswerInput,
    "handoff.status": HandoffReference,
    "handoff.inbox": HandoffInboxInput,
    "handoff.reconcile": HandoffReference,
    "handoff.decide": HandoffDecisionInput,
    "threaddesk.read": ThreadDeskReadInput,
    "threaddesk.manage": ThreadDeskManageInput,
    "threaddesk.knowledge": ThreadDeskKnowledgeInput,
    "observations.read": ObservationReadInput,
    "agent.status": EmptyInput,
    "policy.inspect": EmptyInput,
    "admin.execute": TerminalInput,
}


class Bridge:
    def __init__(self, config: Config):
        self.config = config
        from kirabridge.readiness import runtime_snapshot

        self.runtime = runtime_snapshot(config)
        self.store = Store(config.state_path / "bridge.sqlite3")
        from kirabridge.diagnostics import AuditObserver, runtime_ref
        from kirabridge.readiness import task_preflight

        self.diagnostics = AuditObserver(config, "service", self.runtime, self.store)
        from kirabridge.threaddesk_manager import ThreadDeskManager

        self.threaddesk = ThreadDeskManager(
            config,
            self.diagnostics,
            lambda principal: AuditObserver(config, principal, self.runtime, self.store),
        )
        from kirabridge.handoff_manager import HandoffManager

        self.handoffs = HandoffManager(self)
        self.security = SecurityManager(config, self.store)
        self.terminal = TerminalManager(config.terminal)
        self.filesystem = FilesystemManager()
        self.images = ImageManager()
        self.clipboard = ClipboardManager()
        self.processes = ProcessManager(self.terminal)
        self.agents = AgentManager(config, self.terminal)
        self.tasks = TaskManager(
            config,
            self.store,
            self.security,
            self.execute,
            preflight=lambda task: task_preflight(self, task),
            runtime=runtime_ref(self.runtime),
        )
        self.messages = MessageManager(config, self.store, self.security)
        self.message_receiver = MessageReceiver(self)

    def validate(self, request: TaskRequest) -> None:
        model = INPUTS.get(request.operation)
        if not model:
            raise BridgeError("unknown_operation", "Operation is not supported")
        try:
            model.model_validate(request.arguments)
        except ValidationError:
            raise BridgeError(
                "invalid_arguments", "Arguments do not match the operation schema"
            ) from None

    def submit(self, principal: str, request: TaskRequest, approval: str = "") -> dict:
        try:
            self.validate(request)
            return self.tasks.enqueue(principal, request, approval)
        except BridgeError as exc:
            self.rejection(principal, request, exc)
            raise

    def prepare(self, principal: str, request: TaskRequest) -> dict:
        try:
            self.validate(request)
            return self.tasks.enqueue(principal, request, "", pending=True)
        except BridgeError as exc:
            self.rejection(principal, request, exc)
            raise

    def rejection(self, principal, request, exc):
        from kirabridge.diagnostics import AuditObserver, rejection_report, task_report

        try:
            self.security.principal(principal, "task.read")
            self.store.get(request.task_id, principal)
            report = task_report(self, principal, request.task_id)
            report["submission_error_code"] = exc.code
        except Exception:
            report = rejection_report(self.runtime, request.operation, exc.code, request.task_id)
        exc.diagnostic = report
        if principal in self.config.principals:
            AuditObserver(self.config, principal, self.runtime, self.store)(
                "request.rejected",
                {"operation": report["operation"], "error_code": exc.code},
                task_id=request.task_id,
            )

    def health(self, principal: str) -> dict:
        policy = self.security.principal(principal, "bridge.health")
        return {
            "name": "KiraBridge",
            "version": __version__,
            "api_version": API_VERSION,
            "dispatcher_active": bool(self.tasks.workers)
            and all(not worker.done() for worker in self.tasks.workers),
            "chatgpt_integration": "unverified",
            "local_approval_url": LOCAL_APPROVAL_URL,
            "approval_mode": policy.approval_mode,
            "approval_required": policy.approval_mode == "manual",
            "health_scope": "dispatcher and authentication; use bridge_readiness for prerequisites",
            "runtime": self.runtime,
            "diagnostics_storage": self.diagnostics.status(),
            "message_peers": policy.message_peers,
            "message_receiver_active": bool(
                self.message_receiver.worker and not self.message_receiver.worker.done()
            ),
        }

    def task(self, principal: str, task_id: str) -> dict:
        self.security.principal(principal, "task.read")
        task = self.store.get(task_id, principal)
        for key in ("lease_owner", "lease_until", "idem"):
            task.pop(key, None)
        if task["state"] in {State.FAILED, State.UNKNOWN, State.BLOCKED}:
            from kirabridge.diagnostics import task_report

            task["diagnostic"] = task_report(self, principal, task_id)
        return {"api_version": API_VERSION, **task}

    def events(self, principal: str, task_id: str, after: int = 0) -> dict:
        import json

        self.task(principal, task_id)
        rows = self.store.db.execute(
            "SELECT seq,at,state,evidence FROM events WHERE task_id=? AND seq>? "
            "ORDER BY seq LIMIT 1000",
            (task_id, after),
        )
        return {"events": [{**dict(row), "evidence": json.loads(row["evidence"])} for row in rows]}

    def list_tasks(
        self, principal: str, after: int = 0, limit: int = 100, state: str | None = None
    ) -> dict:
        self.security.principal(principal, "task.read")
        if not 0 <= after or not 1 <= limit <= 1000:
            raise BridgeError("invalid_cursor", "Use a nonnegative cursor and limit from 1 to 1000")
        if state is not None and state not in {value.value for value in State}:
            raise BridgeError("invalid_state", "Unknown task state filter")
        rows = self.store.db.execute(
            "SELECT rowid AS cursor,id,operation,agent,parent_id,state,created,updated,finished "
            "FROM tasks WHERE principal=? AND rowid>? AND (? IS NULL OR state=?) "
            "ORDER BY rowid LIMIT ?",
            (principal, after, state, state, limit),
        ).fetchall()
        return {
            "tasks": [dict(row) for row in rows],
            "next_cursor": rows[-1]["cursor"] if rows else after,
        }

    async def execute(self, task: dict, running, progress) -> dict[str, Any]:
        operation, arguments, principal = task["operation"], task["args"], task["principal"]
        args = INPUTS[operation].model_validate(arguments)
        policy = self.security.principal(principal, operation)
        roots = policy.roots + (
            policy.read_roots if operation in {"file.read", "file.image", "file.list"} else []
        )
        scope = PathScope(roots, excluded=[str(self.config.state_path)])
        if operation == "terminal.execute":
            result = await self.terminal.execute(
                task["id"],
                principal,
                args,
                policy.terminal_roots or policy.roots,
                policy.executables,
                running,
                allow_any_executable=policy.allow_any_executable,
            )
            return {
                **result,
                "success": result["exit_code"] == 0
                and not result["timed_out"]
                and not result["terminated"],
                "evidence": {
                    "pid": result["pid"],
                    "exit_code": result["exit_code"],
                    "timed_out": result["timed_out"],
                    "terminated": result["terminated"],
                },
            }
        if operation == "agent.execute":
            return await self.agents.execute(task, args, policy, running, progress)
        if operation.startswith("handoff."):
            return await self.handoffs.execute(task, args, policy, running, progress)
        if operation.startswith("threaddesk."):
            return await self.threaddesk.execute(task, args, running)
        if operation == "observations.read":
            from kirabridge.observation_export import export_workflow_observations

            await running({"evidence_type": "local_operation_entered", "operation": operation})
            return await asyncio.to_thread(
                export_workflow_observations, self, principal, **args.model_dump()
            )

        if operation == "admin.execute":
            from kirabridge.admin_manager import execute_admin

            return await execute_admin(self, task, args, policy, running)
        if operation in {"policy.inspect", "agent.status"}:
            from kirabridge.development_status import agent_status, permissions_snapshot

            await running({"evidence_type": "local_operation_entered", "operation": operation})
            if operation == "policy.inspect":
                return permissions_snapshot(self, principal)
            return await agent_status(self, principal)
        if operation.startswith("file."):
            scope.split(args.path)
            if operation == "file.move":
                scope.split(args.destination)
            await running({"evidence_type": "local_operation_entered", "operation": operation})
            if operation == "file.image":
                return await asyncio.to_thread(self.images.read, scope, args.path)
            method = getattr(self.filesystem, operation.split(".")[1])
            return await asyncio.to_thread(method, scope, **args.model_dump())
        if operation.startswith("clipboard."):
            await running({"evidence_type": "local_operation_entered", "operation": operation})
            if operation == "clipboard.read":
                return await self.clipboard.read(args.max_bytes)
            if operation == "clipboard.write":
                result = await self.clipboard.write(args.text)
                return {
                    **result,
                    "success": result["verified"],
                    "evidence": {
                        "write_readback_verified": result["verified"],
                        "content_sha256": result["content_sha256"],
                    },
                }
            return self.clipboard.info()
        if operation.startswith("process."):
            if operation != "process.list":
                self.store.get(args.task_id, principal)
            await running({"evidence_type": "local_operation_entered", "operation": operation})
            if operation == "process.list":
                return self.processes.list(principal)
            if operation == "process.inspect":
                return self.terminal.inspect(principal, args.task_id)
            return await self.terminal.terminate(principal, args.task_id)
        raise BridgeError("unknown_operation", "Operation is not supported")

    def record_runtime_load(self):
        previous = self.store.db.execute(
            "SELECT metadata FROM audit WHERE kind='diagnostic.runtime.loaded' "
            "ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        import json

        old = json.loads(previous[0])["runtime"] if previous else None
        self.diagnostics(
            "runtime.loaded",
            {
                "previous_runtime": old,
                "config_changed": old.get("config_sha256") != self.runtime["config_sha256"]
                if old
                else None,
                "source_changed": old.get("source_tree_sha256")
                != self.runtime["source_tree_sha256"]
                if old
                else None,
                "effective_config_changed": old.get("effective_config_sha256")
                != self.runtime["effective_config_sha256"]
                if old
                else None,
                "change_actor": "unknown; edits outside loader are not observed",
                "observer": "dispatcher",
                "external_tunnel": "unknown",
            },
        )

    async def __aenter__(self):
        await self.tasks.start()
        try:
            self.record_runtime_load()
            await self.message_receiver.start()
        except BaseException:
            await self.tasks.stop()
            raise
        return self

    async def __aexit__(self, *exc):
        try:
            await self.message_receiver.stop()
        finally:
            await self.tasks.stop()
            await self.threaddesk.close()
            self.store.close()
