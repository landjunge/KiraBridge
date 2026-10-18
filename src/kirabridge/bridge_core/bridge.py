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
    MoveInput,
    PathInput,
    ProcessInput,
    ReadInput,
    State,
    TaskRequest,
    TerminalInput,
    WriteInput,
)
from kirabridge.clipboard_manager import ClipboardManager
from kirabridge.filesystem_manager import FilesystemManager, PathScope
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
}


class Bridge:
    def __init__(self, config: Config):
        self.config = config
        from kirabridge.readiness import runtime_snapshot

        self.runtime = runtime_snapshot(config)
        self.store = Store(config.state_path / "bridge.sqlite3")
        self.security = SecurityManager(config, self.store)
        self.terminal = TerminalManager()
        self.filesystem = FilesystemManager()
        self.clipboard = ClipboardManager()
        self.processes = ProcessManager(self.terminal)
        self.agents = AgentManager(config, self.terminal)
        self.tasks = TaskManager(config, self.store, self.security, self.execute)
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
        self.validate(request)
        return self.tasks.enqueue(principal, request, approval)

    def prepare(self, principal: str, request: TaskRequest) -> dict:
        self.validate(request)
        return self.tasks.enqueue(principal, request, "", pending=True)

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
            policy.read_roots if operation in {"file.read", "file.list"} else []
        )
        scope = PathScope(roots, excluded=[str(self.config.state_path)])
        if operation == "terminal.execute":
            result = await self.terminal.execute(
                task["id"], principal, args, policy.roots, policy.executables, running
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
        if operation.startswith("file."):
            scope.split(args.path)
            if operation == "file.move":
                scope.split(args.destination)
            await running({"evidence_type": "local_operation_entered", "operation": operation})
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

    async def __aenter__(self):
        await self.tasks.start()
        try:
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
            self.store.close()
