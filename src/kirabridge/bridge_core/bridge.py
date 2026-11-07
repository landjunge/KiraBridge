from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from kirabridge import API_VERSION, LOCAL_APPROVAL_URL, __version__
from kirabridge.agent_manager import AgentManager
from kirabridge.autonext.models import AutoNextControl
from kirabridge.bridge_core.config import Config
from kirabridge.bridge_core.models import (
    AgentInput,
    BridgeError,
    ClipboardRead,
    ClipboardWrite,
    ConnectionCheckInput,
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
    ThreadDeskDynamicInput,
    ThreadDeskKnowledgeInput,
    ThreadDeskManageInput,
    ThreadDeskReadInput,
    WorkflowStopInput,
    WriteInput,
)
from kirabridge.clipboard_manager import ClipboardManager
from kirabridge.directory_ranges import DirectoryInput
from kirabridge.file_transfer.models import InventoryInput, PrepareInput, TransferInput
from kirabridge.filesystem_manager import FilesystemManager, PathScope
from kirabridge.image_manager import ImageManager
from kirabridge.keyboard_action_manager import ACTION_INPUTS, KeyboardActionManager
from kirabridge.keyboard_control import CONTROL_INPUTS, KeyboardControl
from kirabridge.keyboard_manager import KEYBOARD_INPUTS, KeyboardManager
from kirabridge.keyboard_profile_manager import PROFILE_INPUTS, KeyboardProfileManager
from kirabridge.keyboard_sequence import SEQUENCE_INPUTS, KeyboardSequence
from kirabridge.message_manager import MessageManager
from kirabridge.message_manager.receiver import MessageReceiver
from kirabridge.permissions import (
    LEVELS,
    direct_terminal_required,
    level_for,
    state_exclusions,
    visible_execution,
)
from kirabridge.platform_adapters.macos.status import PlatformStatusInput
from kirabridge.platform_adapters.macos.system_identity import installed_native_contract
from kirabridge.platform_adapters.macos.system_models import SYSTEM_INPUTS
from kirabridge.platform_adapters.macos.system_transport import SystemModules
from kirabridge.process_manager import ProcessManager
from kirabridge.process_output_store import OutputRangeInput, ProcessOutputStore
from kirabridge.queue_management.models import QueueControl
from kirabridge.security_manager import SecurityManager
from kirabridge.session_manager import (
    SessionInput,
    SessionManager,
    SessionOpen,
    SessionRead,
    SessionSelect,
)
from kirabridge.system_operations import SYSTEM_LEAVES, SYSTEM_READ_OPERATIONS
from kirabridge.system_reports import REPORT_TYPES, SystemReportInput
from kirabridge.task_manager.manager import TaskManager
from kirabridge.task_manager.store import Store
from kirabridge.terminal_manager import TerminalManager
from kirabridge.visible_terminal import VisibleTerminal, VisibleTerminalInput
from kirabridge.windows_keyboard import WINDOWS_KEYBOARD_INPUTS, WindowsKeyboardManager
from kirabridge.windows_windows import WINDOWS_WINDOW_INPUTS, WindowsWindowManager

INPUTS = {
    "autonext.control": AutoNextControl,
    **WINDOWS_KEYBOARD_INPUTS,
    **WINDOWS_WINDOW_INPUTS,
    **SYSTEM_INPUTS,
    **KEYBOARD_INPUTS,
    **CONTROL_INPUTS,
    **SEQUENCE_INPUTS,
    **ACTION_INPUTS,
    **PROFILE_INPUTS,
    "process.output": OutputRangeInput,
    "system.report": SystemReportInput,
    "platform.status": PlatformStatusInput,
    "queue.control": QueueControl,
    "files.prepare": PrepareInput,
    "files.transfer": TransferInput,
    "files.inventory": InventoryInput,
    "files.status": TransferInput,
    "files.pause": TransferInput,
    "files.abort": TransferInput,
    "connection.check": ConnectionCheckInput,
    "session.open": SessionOpen,
    "session.input": SessionInput,
    "session.catalog": EmptyInput,
    "session.read": SessionRead,
    "session.focus": SessionSelect,
    "session.close": SessionSelect,
    "terminal.execute": TerminalInput,
    "terminal.visible": VisibleTerminalInput,
    "file.read": ReadInput,
    "file.image": ImageInput,
    "file.list": DirectoryInput,
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
    "threaddesk.dynamic": ThreadDeskDynamicInput,
    "threaddesk.read": ThreadDeskReadInput,
    "threaddesk.manage": ThreadDeskManageInput,
    "threaddesk.knowledge": ThreadDeskKnowledgeInput,
    "observations.read": ObservationReadInput,
    "workflow.stop": WorkflowStopInput,
    "agent.status": EmptyInput,
    "policy.inspect": EmptyInput,
    "admin.execute": TerminalInput,
}


class Bridge:
    def __init__(self, config: Config, *, routing_guard=None, handoff_peer=None):
        self.config = config
        from kirabridge.readiness import runtime_snapshot

        self.runtime = runtime_snapshot(config)
        self.store = Store(config.state_path / "bridge.sqlite3")
        from kirabridge.operations_service import config_snapshot

        config_snapshot(config)
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

        self.handoffs = HandoffManager(self, peer=handoff_peer)
        self.security = SecurityManager(config, self.store)
        from kirabridge.file_transfer.authorization import TransferAuthorization
        from kirabridge.file_transfer.repository import TransferRepository
        from kirabridge.file_transfer.service import FileTransferService
        from kirabridge.file_transfer.sources import SourceRegistry
        from kirabridge.file_transfer.threaddesk import ThreadDeskFileReceiver
        from kirabridge.output_history import OutputHistory

        self.file_sources = SourceRegistry()
        self.file_authorization = TransferAuthorization(
            config.file_transfer, self.security.principal
        )
        self.file_repository = TransferRepository(
            self.store.db, self.store.transaction, self.store.audit
        )
        self.file_transfers = FileTransferService(
            config.state_path / "file-transfer-snapshots",
            config.file_transfer,
            self.file_sources,
            self.file_authorization,
            self.file_repository,
            ThreadDeskFileReceiver(self.threaddesk),
        )
        self.outputs = OutputHistory(config.output_history, self.store)
        self.store.result_codec = self.outputs
        self.process_outputs = ProcessOutputStore(config.state_path / "process-output", self.store)
        self.terminal = TerminalManager(config.terminal, output_store=self.process_outputs)
        self.filesystem = FilesystemManager()
        self.images = ImageManager()
        self.clipboard = ClipboardManager()
        self.processes = ProcessManager(self.terminal)
        if config.team.routing is not None:
            from kirabridge.capability_routing.native import native_routed_manager

            self.agents = native_routed_manager(self, routing_guard)
        else:
            self.agents = AgentManager(config, self.terminal)
        from kirabridge.configured_workflow import configured_workflow_control

        self.workflow_control = configured_workflow_control(self)
        self.tasks = TaskManager(
            config,
            self.store,
            self.security,
            self.execute,
            preflight=lambda task: task_preflight(self, task),
            runtime=runtime_ref(self.runtime),
        )
        from kirabridge.session_ports import SessionPorts
        from kirabridge.terminal_queries import TerminalQueries

        self.sessions = SessionManager(
            SessionPorts(
                authorization=self.security,
                input_release=self.tasks.input_policy,
                audit=self.outputs,
                environment=self.terminal.environment,
                agent_registry=lambda: (config.agents, config.visible_handoffs.bindings),
                clipboard_lock=self.clipboard.lock,
                visible_required=lambda name: direct_terminal_required(config, name),
                readiness=lambda principal, result: self.visible_handoffs.observe_readiness(
                    principal, result
                ),
            )
        )
        self.visible_terminal = VisibleTerminal(
            config, self.security, self.sessions, self.terminal.environment
        )
        self.terminal_queries = TerminalQueries(
            self.security, self.sessions, self.store, config.read_concurrency
        )
        from kirabridge.completion_manager import CompletionManager

        self.completions = CompletionManager(self.store, self.security)
        self.messages = MessageManager(config, self.store, self.security)
        from kirabridge.visible_handoff import VisibleHandoffs

        self.visible_handoffs = VisibleHandoffs(
            config, self.store, self.security, self.sessions, self.messages
        )
        from kirabridge.platform_adapters.macos import MacOSProvider

        self.system_modules = SystemModules(
            authorize=self.security.authorize, **installed_native_contract(Path(__file__))
        )
        from kirabridge.desktop_input import DesktopInput

        self.desktop_input = DesktopInput(
            self.sessions.lock, timeout=self.system_modules.transport.timeout
        )
        self.windows_keyboard = WindowsKeyboardManager(self.security.authorize, self.desktop_input)
        self.windows_windows = WindowsWindowManager(self.security.authorize, self.desktop_input)
        self.keyboard_profiles = KeyboardProfileManager(
            config.state_path, self.security.authorize, self.desktop_input
        )
        self.keyboard = KeyboardManager(
            transport=self.system_modules.transport,
            desktop_input=self.desktop_input,
            authorize=self.security.authorize,
        )
        self.keyboard_control = KeyboardControl(self.keyboard)
        self.keyboard_sequence = KeyboardSequence(self.keyboard_control)
        self.keyboard_actions = KeyboardActionManager(
            keyboard=self.keyboard,
            profiles=self.keyboard_profiles,
            desktop_input=self.desktop_input,
            authorize=self.security.authorize,
        )
        self.sessions.terminal_app.system_transport = self.system_modules.transport
        self.macos = MacOSProvider(
            terminal_app=self.sessions.terminal_app,
            clipboard=self.clipboard,
            files=self.filesystem,
            processes=self.processes,
            system_modules=self.system_modules,
            system_reports=self.terminal,
        )
        from kirabridge.native_queries import NativeQueries

        self.native_queries = NativeQueries(
            self.security, self.macos, self.system_modules, config.read_concurrency
        )
        self.sessions.terminal_app.platform_guard = lambda: self.macos.require("terminal.native")
        self.agents.visible_handoffs = self.visible_handoffs

        def maintain():
            self.messages.voice_policy.expire()
            self.outputs.prune()

        self.tasks.maintenance = maintain
        self.message_receiver = MessageReceiver(self)
        from kirabridge.team_manager import TeamManager
        from kirabridge.team_manager.dispatcher import TeamDispatcher

        self.teams = TeamManager(self)
        self.messages.voice_policy.teams = self.teams
        self.team_dispatcher = TeamDispatcher(self)
        from kirabridge.autonext.manager import AutoNextManager

        if config.autonext.coordinator_mode:
            from kirabridge.autonext.coordinator import CoordinatedAutoNext

            self.autonext = CoordinatedAutoNext(self)
        else:
            self.autonext = AutoNextManager(self)
        self.agents.worktree_guard = lambda task, args: self.autonext.authorize_execution(
            {**task, "args": args.model_dump()}
        )
        from kirabridge.queue_management import QueueManager

        self.queues = QueueManager(
            self.store, self.security, self.tasks, self.messages, self.visible_handoffs, self.teams
        )

    def validate(self, request: TaskRequest) -> None:
        if request.operation in WINDOWS_KEYBOARD_INPUTS and self.windows_keyboard.host != "win32":
            raise BridgeError("unsupported_platform", "Windows keyboard requires Windows")
        if request.operation in WINDOWS_WINDOW_INPUTS and self.windows_windows.host != "win32":
            raise BridgeError("unsupported_platform", "Windows window tasks require Windows")
        model = INPUTS.get(request.operation)
        if not model:
            raise BridgeError("unknown_operation", "Operation is not supported")
        try:
            model.model_validate(request.arguments)
        except ValidationError:
            raise BridgeError(
                "invalid_arguments",
                "For Return without text use session_enter with the observed cursor and agent PID"
                if request.operation == "session.input" and not request.arguments.get("text")
                else "Arguments do not match the operation schema",
            ) from None

    def submit(
        self,
        principal: str,
        request: TaskRequest,
        approval: str = "",
        *,
        completion_target: str | None = None,
    ) -> dict:
        try:
            self.validate(request)
            return self.tasks.enqueue(
                principal, request, approval, completion_target=completion_target
            )
        except BridgeError as exc:
            self.rejection(principal, request, exc)
            raise

    def prepare(
        self, principal: str, request: TaskRequest, *, completion_target: str | None = None
    ) -> dict:
        try:
            self.validate(request)
            return self.tasks.enqueue(
                principal, request, "", pending=True, completion_target=completion_target
            )
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
        from kirabridge.discovery import snapshot
        from kirabridge.permissions import automatic_for, permission_summary
        from kirabridge.terminal_access import terminal_access

        result = {
            "name": "KiraBridge",
            "discovery": snapshot(self, principal),
            "version": __version__,
            "api_version": API_VERSION,
            "dispatcher_active": bool(self.tasks.workers)
            and all(not worker.done() for worker in self.tasks.workers),
            "chatgpt_integration": "unverified",
            "task_submission": {
                "events_subscription_required": False,
                "preferred_tools": ["action_request", "action_submit"],
                "result_tools": ["task_get", "task_events", "read_query"],
                "legacy_connector_schema": "If a cached task_* connector requires "
                "completion_subscription, the root value empty string is accepted "
                "as no subscription; use fresh action_* schemas after metadata refresh.",
            },
            "completion_channel": {
                "receive_tool": "completion_receive",
                "ack_tool": "completion_ack",
                "default_target": "default",
                "mode": "durable_inbox_with_waiting_consumer",
                "unsolicited_chatgpt_wakeup": "unavailable_on_current_transport",
            },
            "local_approval_url": LOCAL_APPROVAL_URL,
            "approval_mode": policy.approval_mode,
            "permission_level": level_for(policy),
            "permission_label": LEVELS[level_for(policy)],
            "permission_detail": permission_summary(self.config, principal),
            "approval_required": not automatic_for(policy, "terminal.execute"),
            "approval_required_scope": (
                "default execution; inspect each operation permission_decision"
            ),
            "effective_approval_mode": "automatic"
            if automatic_for(policy, "terminal.execute")
            else "per_operation",
            "session_input_policy": self.config.session_input_policy.model_dump(),
            "terminal_access": terminal_access(self.config, principal),
            "automatic_operations": policy.automatic_operations,
            "voice_messaging": self.config.voice_messaging.model_dump(),
            "visible_handoffs": self.config.visible_handoffs.model_dump(),
            **self.messages.voice_channel.profile(principal),
            "health_scope": "dispatcher and authentication; use bridge_readiness for prerequisites",
            "runtime": self.runtime,
            "operations": {
                "protocol": 1,
                "maintenance": self.store.maintenance_state(),
                "accepting_new_work": self.store.maintenance_state() is None,
            },
            "desktop_last_observation": self.sessions.desktop.last,
            "output_history": self.outputs.status(),
            "diagnostics_storage": self.diagnostics.status(),
            "message_peers": policy.message_peers,
            "message_receiver_active": bool(
                self.message_receiver.worker and not self.message_receiver.worker.done()
            ),
            "autonext": self.autonext.inspect(),
            "message_receiver_scope": "bridge_dispatcher_for_configured_receivers",
        }
        if sys.platform.startswith("linux"):
            from kirabridge.platform_adapters import LinuxAdapter

            result["server"] = LinuxAdapter().server_facts()
        return result

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

        self.security.principal(principal, "task.read")
        if (
            self.store.db.execute(
                "SELECT 1 FROM tasks WHERE id=? AND principal=?", (task_id, principal)
            ).fetchone()
            is None
        ):
            raise BridgeError("not_found", "Task not found")
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
        operation = self.platform_operation(task["operation"], task["args"], task["principal"])
        if operation is not None:
            return await self.macos.execute(
                operation,
                lambda: self._execute_operation(task, running, progress),
                revalidate=lambda: self.security.authorize(
                    task["principal"], task["operation"], text=task["args"].get("text")
                ),
            )
        return await self._execute_operation(task, running, progress)

    def platform_operation(self, operation, arguments=None, principal=None):
        """Select the existing native provider without changing tmux/portable routes."""
        if self.macos.host_platform != "darwin":
            return None
        if operation in {"session.catalog", "platform.status", "clipboard.info"}:
            return None  # The terminal catalogue can contain tmux as well.
        if operation in {"terminal.execute", "admin.execute"}:
            if visible_execution(
                self.config,
                principal,
                operation,
                background=bool((arguments or {}).get("background", False)),
            ) or (
                operation == "admin.execute" and direct_terminal_required(self.config, principal)
            ):
                return "terminal.visible"
            return None
        if operation.startswith("session.") and operation != "session.open":
            if not str((arguments or {}).get("pane_id", "")).startswith("terminal:"):
                return None
        return operation if operation in self.macos.descriptors else None

    async def platform_status(self, principal, *, check_helpers=False):
        from kirabridge.permissions import decision

        self.security.authorize(principal, "platform.status")
        if self.windows_keyboard.host == "win32" or self.windows_windows.host == "win32":
            return {
                "schema_version": 1,
                "provider_id": "windows.sendinput.v1",
                "platform": "win32",
                "operations": [
                    row
                    for row in self.windows_keyboard.catalog(
                        lambda op: decision(self.config, principal, op)
                    )
                    + self.windows_windows.catalog(lambda op: decision(self.config, principal, op))
                    if row["available"] and row["policy"]["authorized"]
                ],
                "interactive_desktop_observed": False,
                "scope": "Windows desktop preview metadata; inspect exact targets before effects",
                "unsupported_features": [
                    "macOS system keys and profiles",
                    "public file-root tools",
                    "managed process execution",
                    "agent terminal automation",
                ],
            }
        if self.macos.host_platform != "darwin":
            from kirabridge.platform_adapters import LinuxAdapter

            facts = LinuxAdapter().server_facts()
            return {
                "schema_version": 1,
                "provider_id": "linux.server.systemd-user",
                "platform": self.macos.host_platform,
                "server": facts,
                "operations": [],
                "interactive_desktop_observed": False,
                "gui_parity": False,
                "scope": "Linux server MCP, authentication and health; no desktop session",
                "unsupported_features": [
                    "macOS GUI and Terminal.app",
                    "native keyboard and system keys",
                    "desktop session control",
                    "full clipboard and GUI parity",
                ],
            }
        # Explicit no-prompt checks run only for status, never tools/list.
        await asyncio.to_thread(self.macos.permission_probe.refresh_core)
        result = {
            **self.macos.snapshot(),
            "operations": [
                row
                for row in self.macos.operation_catalog(
                    lambda op: decision(self.config, principal, op)
                )
                if row["operation"] in INPUTS and row["policy"]["authorized"]
            ],
            "scope": "technical availability and OS observations; no execution grant",
        }
        if check_helpers:
            from kirabridge.platform_adapters.macos.helper_permissions import (
                inspect_helper_permissions,
            )

            # A transient diagnostic process cannot authorize another worker.
            # Keep its identity out of PermissionProbe and discovery revisions.
            result["helper_diagnostics"] = await inspect_helper_permissions()
        return result

    async def _execute_operation(self, task: dict, running, progress) -> dict[str, Any]:
        operation, arguments, principal = task["operation"], task["args"], task["principal"]
        args = INPUTS[operation].model_validate(arguments)
        self.security.authorize(principal, operation, text=arguments.get("text"))
        policy = self.security.principal(principal, operation)
        roots = policy.roots + (
            policy.read_roots if operation in {"file.read", "file.image", "file.list"} else []
        )
        scope = PathScope(roots, excluded=state_exclusions(self.config, policy))
        if operation in WINDOWS_KEYBOARD_INPUTS:
            return await self.windows_keyboard.execute(task, args, running, progress)
        if operation in WINDOWS_WINDOW_INPUTS:
            return await self.windows_windows.execute(task, args, running, progress)
        if operation == "platform.status":
            await running({"evidence_type": "platform_status_query"})
            return await self.platform_status(principal, check_helpers=args.check_helpers)
        if operation == "system.report":
            self.macos.require(operation)
            roots = policy.terminal_roots or policy.roots
            if not roots:
                raise BridgeError("path_denied", "A permitted working directory is required")
            report = TerminalInput(
                argv=[
                    "/usr/sbin/system_profiler",
                    "-json",
                    "-detailLevel",
                    args.detail,
                    REPORT_TYPES[args.report],
                ],
                cwd=roots[0],
                timeout=args.timeout,
                max_output=args.max_output,
                background=True,
            )
            result = await self.terminal.execute(
                task["id"],
                principal,
                report,
                roots,
                ["/usr/sbin/system_profiler"],
                running,
                allow_any_executable=False,
            )
            return {
                **result,
                "report": args.report,
                "format": "json",
                "success": result["exit_code"] == 0
                and not result["timed_out"]
                and not result["terminated"],
                "full_output": {
                    "operation": "process.output",
                    "task_id": task["id"],
                    "streams": ["stdout", "stderr"],
                },
                "scope": (
                    "Fixed public system_profiler report; complete owned byte streams "
                    "remain separately pageable"
                ),
            }
        if operation in SEQUENCE_INPUTS:
            return await self.keyboard_sequence.execute(task, args, running, progress)
        if operation in CONTROL_INPUTS:
            return await self.keyboard_control.execute(task, args, running, progress)
        if operation in ACTION_INPUTS:
            return await self.keyboard_actions.execute(task, args, running, progress)
        if operation in PROFILE_INPUTS:
            return await self.keyboard_profiles.execute(task, args, running)
        if operation in KEYBOARD_INPUTS:
            return await self.keyboard.execute(task, args, running, progress)
        if operation in SYSTEM_LEAVES:
            if operation == "apps.launch":
                # Launching a bundle does not bypass the caller's filesystem roots.
                with scope.directory(args.app_path):
                    pass
            from kirabridge.desktop_input import DESKTOP_EFFECT_OPERATIONS

            async def execute_native(turn=None):
                await running(
                    {
                        "evidence_type": "native_system_operation",
                        "operation": operation,
                        "effect_attempted": operation not in SYSTEM_READ_OPERATIONS,
                        "automatic_retry": False,
                    }
                )
                if turn is not None:
                    turn.mark_attempted()
                return await self.system_modules.execute(
                    operation,
                    args.model_dump(exclude_none=True),
                    principal=principal,
                    task_id=task["id"],
                )

            if operation in DESKTOP_EFFECT_OPERATIONS:
                async with self.desktop_input.transaction() as turn:
                    return await execute_native(turn)
            return await execute_native()
        if operation == "process.output":
            self.store.get(args.task_id, principal)
            await running({"evidence_type": "owned_process_output_read"})
            return self.terminal.read_output(principal, **args.model_dump())
        if operation == "queue.control":
            # Rejections before any mutation remain definite failures, not unknown effects.
            result = await self.queues.control(
                principal, args, approved=True, control_task_id=task["id"]
            )
            await running({"phase": "queue_control_recorded", "history_preserved": True})
            return result
        if operation == "files.prepare":
            return await self.file_transfers.prepare(task, args, running)
        if operation == "files.transfer":
            return await self.file_transfers.transfer(task, args, running)
        if operation == "files.abort":
            return await self.file_transfers.abort(task, args, running)
        if operation == "files.pause":
            await running({"phase": "pause_requested", "transfer_id": args.transfer_id})
            return self.file_repository.pause(principal, args.transfer_id)
        if operation in {"files.inventory", "files.status"}:
            self.file_authorization.check(principal, "files.inspect")
            await running({"phase": "file_status_query"})
            if operation == "files.status":
                return self.file_repository.public(
                    self.file_repository.get(principal, args.transfer_id)
                )
            return {
                "transfers": [
                    self.file_repository.public(row)
                    for row in self.file_repository.list(principal, args.after, args.limit)
                ]
            }
        if operation == "connection.check":
            await running({"evidence_type": "connection_check_received"})
            return await self.check_connection(principal, args.device, args.mode)
        if operation == "session.catalog":
            await running({"evidence_type": "terminal_catalog_query"})
            return await self.terminal_queries.execute(
                principal, operation, arguments, task_id=task["id"]
            )
        if operation == "session.read":
            await running({"evidence_type": "terminal_read_query", "pane_id": args.pane_id})
            return await self.terminal_queries.execute(
                principal, operation, arguments, task_id=task["id"]
            )
        if operation == "session.focus":
            await running({"evidence_type": "terminal_focus", "pane_id": args.pane_id})
            return await self.sessions.focus(principal, args.pane_id, args.expected_pid)
        if operation == "session.close":
            await running({"evidence_type": "terminal_close", "pane_id": args.pane_id})
            return await self.sessions.close_tab(principal, args.pane_id, args.expected_pid)
        if visible_execution(
            self.config,
            principal,
            operation,
            background=bool(getattr(args, "background", False)),
        ):
            visible_args = VisibleTerminalInput.model_validate(arguments)
            return await self.visible_terminal.execute(
                task, visible_args, running, progress=progress
            )
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
        if operation == "session.input":
            if args.key is not None:
                from kirabridge.session_return import execute

                return await execute(self, task, args, running, progress)
            selected = await self.sessions.selected(principal, args.pane_id, args.expected_pid)
            target, selected_binding = self.sessions.explicit_agent_binding(selected)
            if target:
                from kirabridge.session_input_router import execute

                return await execute(self, task, args, target, selected_binding, running, progress)

            async def session_input_attempted():
                await running(
                    {
                        "evidence_type": "session_input_dispatch",
                        "terminal_input_attempted": True,
                        "pane_id": args.pane_id,
                        "expected_pid": args.expected_pid,
                        "automatic_retry": False,
                    }
                )

            return await self.sessions.send(
                principal, args, task_id=task["id"], before_transport=session_input_attempted
            )
        if operation == "session.open":
            await running({"evidence_type": "session_open_dispatch"})

            async def session_window_created(receipt):
                await progress(
                    {
                        "evidence_type": "session_window_created",
                        "creation_receipt": receipt,
                        "automatic_retry": False,
                    }
                )

            return await self.sessions.open(
                principal, args, task_id=task["id"], on_created=session_window_created
            )
        if operation == "agent.execute":
            self.teams.authorize_execution(task)
            # Only a sealed team assignment may select its configured dedicated worker.
            # Direct agent requests retain the existing visible route.
            work = self.store.db.execute(
                "SELECT assignee FROM team_work WHERE core_task_id=?", (task["id"],)
            ).fetchone()
            worker = self.config.team.workers.get(work["assignee"]) if work else None
            managed = bool(worker and worker.execution_scope == "separate_managed_session")
            return await self.agents.execute(
                task, args, policy, running, progress, separate_managed=managed
            )
        if operation == "autonext.control":
            self.autonext.validate_control(principal, args)
            await running({"evidence_type": "autonext_control", "action": args.action})
            return self.autonext.control(principal, args)
        if operation.startswith("handoff."):
            return await self.handoffs.execute(task, args, policy, running, progress)
        if operation == "workflow.stop":
            await running({"evidence_type": "local_operation_entered", "operation": operation})
            if self.workflow_control is None:
                from kirabridge.workflow_control_adapter import owned_stop

                return await owned_stop(
                    self,
                    principal,
                    args.handoff_id,
                    args.revision,
                    args.stop_id,
                    task_id=task["id"],
                    barrier={
                        "status": "UNKNOWN",
                        "further_dispatch_blocked": False,
                        "abort_confirmed": False,
                    },
                    control_error="workflow_control_disabled",
                )
            return await self.workflow_control.stop(
                principal, args.handoff_id, args.revision, args.stop_id, task_id=task["id"]
            )
        if operation == "threaddesk.dynamic":
            from kirabridge.threaddesk_dynamic import execute as dynamic_execute

            return await dynamic_execute(self, task, args, running)
        if operation.startswith("threaddesk."):
            return await self.threaddesk.execute(task, args, running)
        if operation == "observations.read":
            from kirabridge.observation_export import export_workflow_observations

            await running({"evidence_type": "local_operation_entered", "operation": operation})
            return await asyncio.to_thread(
                export_workflow_observations, self, principal, **args.model_dump()
            )

        if operation == "admin.execute":
            if direct_terminal_required(self.config, principal):
                return await self.visible_terminal.execute(
                    task,
                    VisibleTerminalInput.model_validate(arguments),
                    running,
                    progress=progress,
                    privileged=True,
                )
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

    async def check_connection(self, principal, device, mode):
        self.security.principal(principal, "bridge.health")
        terminals = {"status": "not_granted", "sessions": []}
        if "session.inspect" in self.config.principals[principal].capabilities:
            terminals = await self.sessions.catalog(principal)
        evidence = {
            "device": device,
            "mode": mode,
            "device_mode_source": "caller_report",
            "transport_receipt": True,
            "terminal_transport": terminals.get("status"),
            "terminal_count": len(terminals.get("sessions", [])),
        }
        with self.store.transaction():
            self.store.audit("connection.checked", principal, None, evidence)
        return {
            "principal": principal,
            **evidence,
            "dispatcher_active": bool(self.tasks.workers),
            "permission_scope": "same_for_all_devices_and_modes",
        }

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
            await self.team_dispatcher.start()
            await self.autonext.start()
        except BaseException:
            for stop in (
                self.autonext.stop,
                self.team_dispatcher.stop,
                self.message_receiver.stop,
                self.tasks.stop,
            ):
                await asyncio.gather(stop(), return_exceptions=True)
            raise
        return self

    async def __aexit__(self, *exc):
        try:
            try:
                await self.autonext.stop()
            finally:
                try:
                    await self.team_dispatcher.stop()
                finally:
                    await self.message_receiver.stop()
        finally:
            await self.tasks.stop()
            await self.system_modules.close()
            await self.threaddesk.close()
            self.store.close()
