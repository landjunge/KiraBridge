from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from kirabridge import LOCAL_APPROVAL_URL
from kirabridge.bridge_core.bridge import INPUTS, Bridge
from kirabridge.bridge_core.models import BridgeError, TaskRequest
from kirabridge.image_manager import image_task_result
from kirabridge.message_manager import MessageSend
from kirabridge.readiness import ReadinessInput, readiness
from kirabridge.team_manager.models import (
    TeamCreate,
    TeamMessageSend,
    TeamRoleSet,
    TeamWorkClaim,
    TeamWorkComplete,
    TeamWorkCreate,
    TeamWorkReprocess,
)


def create_server(bridge: Bridge, *, transport: str = "stdio", principal: str = "local") -> FastMCP:
    config = bridge.config
    server = FastMCP(
        "KiraBridge",
        instructions="API v1. Check bridge_health or operation_catalog for approval_mode. "
        "Use task_request: automatic mode queues permitted work without a browser click. "
        "Only when approval_required is true, send the operator to local_approval_url. "
        "Do not ask for approval when approval_required is false. "
        "Do not ask them to copy task IDs between chats. "
        "Acceptance is a receipt, not execution. For completion, set completion_target and keep "
        "a completion_receive consumer active; ack only after processing. "
        "This return channel cannot wake an inactive ChatGPT chat. "
        "Query task_get and task_events for additional evidence. "
        "Use message_send/message_receive for addressed peer communication. "
        "Automatic message receivers use separate managed sessions, not existing interactive ones; "
        "check message_channel_status and message_get for actual evidence. "
        "For visible macOS terminals use session_catalog/session_read and session_open. "
        "Send input only to an exact pane_id and expected_pid using operation session.input.",
        stateless_http=True,
        json_response=True,
        log_level="CRITICAL",
        max_request_body_size=config.max_task_bytes + 65536,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[f"{host}:*" for host in config.allowed_hosts] + config.allowed_hosts,
            allowed_origins=config.allowed_origins,
        ),
    )

    def identity(ctx: Context) -> str:
        if transport == "stdio":
            bridge.security.principal(principal)
            return principal
        request = ctx.request_context.request
        if request is None:
            raise BridgeError("unauthorized", "Authenticated HTTP context required")
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            raise BridgeError("unauthorized", "Authentication required")
        return bridge.security.authenticate(header[7:])

    def safe(action: Callable):
        try:
            return action()
        except BridgeError as exc:
            result = {"error": {"code": exc.code, "message": str(exc)}}
            if hasattr(exc, "diagnostic"):
                result["diagnostic"] = exc.diagnostic
            return result
        except ValidationError:
            return {"error": {"code": "invalid_arguments", "message": "Invalid tool arguments"}}
        except Exception:
            return {
                "error": {"code": "internal_error", "message": "Request could not be completed"}
            }

    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    write = ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True
    )

    @server.tool(annotations=read)
    def bridge_health(ctx: Context) -> dict[str, Any]:
        """Version and dispatcher health. Never claims ChatGPT integration."""
        return safe(lambda: bridge.health(identity(ctx)))

    @server.tool(annotations=read)
    async def connection_check(
        device: Literal["browser", "mobile", "desktop"],
        mode: Literal["text", "live", "voice"],
        ctx: Context,
    ) -> dict[str, Any]:
        """Check this actual ChatGPT/Kira or Grok connection, also from mobile, Live or voice.

        Call from the current conversation and state the device/mode actually in use.
        Authentication determines your identity. Device/mode are caller reports;
        this tool proves its own receipt, daemon response and available terminal transport.
        All modes use the same permissions, messages and terminal tools.
        """
        return await bridge.check_connection(identity(ctx), device, mode)

    @server.tool(annotations=read)
    def bridge_readiness(
        ctx: Context,
        read_paths: list[str] | None = None,
        executables: list[str] | None = None,
        operations: list[str] | None = None,
        workflow_id: str | None = None,
        working_directories: list[str] | None = None,
        image_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Check this identity's requested file/program prerequisites and loaded daemon snapshot.

        Does not read file contents, execute programs, submit tasks, or certify a workflow.
        image_paths checks descriptor access, not PNG validity or client image display.
        Use read_query for direct bounded text reads; file.image still uses task_request.
        """
        return safe(
            lambda: readiness(
                bridge,
                identity(ctx),
                ReadinessInput(
                    read_paths=read_paths or [],
                    image_paths=image_paths or [],
                    executables=executables or [],
                    operations=operations or [],
                    workflow_id=workflow_id,
                    working_directories=working_directories or [],
                ),
            )
        )

    @server.tool(annotations=read)
    def policy_inspect(ctx: Context) -> dict[str, Any]:
        """Loaded policy and config/source drift, without credentials or raw config."""
        from kirabridge.development_status import permissions_snapshot

        def action():
            name = identity(ctx)
            bridge.security.principal(name, "policy.inspect")
            return permissions_snapshot(bridge, name)

        return safe(action)

    @server.tool(annotations=read)
    async def agent_status(ctx: Context) -> dict[str, Any]:
        """Own managed work and bounded process observation; no interactive session attachment."""
        from kirabridge.development_status import agent_status as inspect

        try:
            name = identity(ctx)
            bridge.security.principal(name, "agent.status")
            return await inspect(bridge, name)
        except BridgeError as exc:
            return {"error": {"code": exc.code, "message": str(exc)}}

    @server.tool(annotations=read)
    def read_query(query: dict[str, Any], ctx: Context) -> dict[str, Any]:
        """Direct authorized read without tasks, approvals or Events subscriptions.

        query.operation: file.read (path, max_bytes<=65536, offset or tail),
        file.list (path; at most 100 entries), terminal.output (owned task_id,
        max_bytes<=65536). Uses existing capabilities and file roots. No shell,
        Desktop Commander or external interactive-session attachment.
        """
        from kirabridge.read_query import ReadQuery
        from kirabridge.read_query import read_query as read_direct

        return safe(lambda: read_direct(bridge, identity(ctx), ReadQuery.model_validate(query)))

    @server.tool(annotations=read)
    async def session_catalog(ctx: Context) -> dict[str, Any]:
        """List existing Terminal.app tabs and tmux panes with exact input/read handles."""
        return await bridge.sessions.catalog(identity(ctx))

    @server.tool(annotations=read)
    async def session_read(pane_id: str, expected_pid: int, ctx: Context) -> dict[str, Any]:
        """Read bounded output from a Terminal.app tab or tmux pane selected by catalog handle."""
        try:
            name = identity(ctx)
            result = await bridge.sessions.read(name, pane_id, expected_pid)
            from kirabridge.bridge_core.models import digest

            key = (name, pane_id, expected_pid)
            fingerprint = digest(result["text"])
            if bridge.sessions.observed_outputs.get(key) != fingerprint:
                if len(bridge.sessions.observed_outputs) >= 128:
                    bridge.sessions.observed_outputs.pop(
                        next(iter(bridge.sessions.observed_outputs))
                    )
                bridge.sessions.observed_outputs[key] = fingerprint
                with bridge.store.transaction():
                    bridge.store.audit(
                        "terminal.output",
                        name,
                        None,
                        {
                            "pane_id": pane_id,
                            "expected_pid": expected_pid,
                            "text": result["text"],
                            "content_sha256": fingerprint,
                        },
                    )
            return result
        except BridgeError as exc:
            return {"error": {"code": exc.code, "message": str(exc)}}

    @server.tool(annotations=read)
    def operation_catalog(ctx: Context) -> dict[str, Any]:
        """Permitted version-1 operations and exact argument JSON schemas."""

        def action():
            from kirabridge.permissions import LEVELS, automatic_for, level_for

            policy = bridge.security.principal(identity(ctx))
            return {
                "api_version": "1",
                "approval_mode": policy.approval_mode,
                "permission_level": level_for(policy),
                "permission_label": LEVELS[level_for(policy)],
                "operations": {
                    name: {
                        "arguments": model.model_json_schema(),
                        "approval_required": not automatic_for(policy, name),
                    }
                    for name, model in INPUTS.items()
                    if name in policy.capabilities
                },
            }

        return safe(action)

    @server.tool(annotations=write)
    async def task_submit(
        request: TaskRequest, ctx: Context, approval: str = "", completion_target: str | None = None
    ) -> dict[str, Any]:
        """Queue a task; automatic mode needs no token, manual mode requires an exact-task grant.

        Repeating its idempotency key never executes it twice.
        For the Grok app, waits briefly and returns conversation_return with the
        actual result. If continue_required is true, call task_get with this same ID.
        """
        result = safe(
            lambda: bridge.submit(
                identity(ctx), request, approval, completion_target=completion_target
            )
        )
        from kirabridge.grok_connector.conversation import result_for_conversation

        return await result_for_conversation(bridge, identity(ctx), result)

    @server.tool(annotations=read)
    async def task_get(task_id: str, ctx: Context) -> dict[str, Any]:
        """Read own task and evidence; completed file.image also returns bounded MCP image content.

        The PNG is a saved snapshot, not a fresh read. Other tasks retain their JSON format.
        For the Grok app, waits for ongoing work and returns conversation_return.
        Keep waiting on this same task when continue_required is true; never resubmit it.
        """
        from kirabridge.grok_connector.conversation import enabled_for, result_for_conversation

        name = identity(ctx)
        result = safe(lambda: bridge.task(name, task_id))
        if enabled_for(bridge, name):
            result = await result_for_conversation(bridge, name, result)
        return safe(lambda: image_task_result(result))

    @server.tool(annotations=read)
    def task_diagnose(task_id: str, ctx: Context) -> dict[str, Any]:
        """Compact owner-only failure/preflight/runtime view of existing task and audit evidence.

        No contents, prompts, arguments or implicit retries. Historical unknowns stay unknown.
        """
        from kirabridge.diagnostics import task_report

        return safe(lambda: task_report(bridge, identity(ctx), task_id))

    @server.tool(annotations=write)
    async def task_request(
        request: TaskRequest, ctx: Context, completion_target: str | None = None
    ) -> dict[str, Any]:
        """Queue permitted work automatically, or request approval if this identity is manual.

        No Events subscription is required. completion_target is optional.
        Set a stable unique completion_target for the requesting assistant session.
        The return route is committed with the task before dispatch. Use completion_receive
        through a waiting consumer for the final notice, then completion_ack after processing.
        This does not wake an inactive ChatGPT chat. task_get remains diagnostic.
        Check approval_required: false means no browser click is needed.
        Only when true, give the operator local_approval_url to approve in their Mac browser.
        Do not ask them to copy task IDs between chats. A queued receipt is not proof of execution.
        For the Grok app, waits briefly and includes conversation_return. Speak its
        actual result when final is true. If continue_required, call task_get with
        this same task ID before finishing the conversation. This does not attest audio playback.
        """

        def action():
            principal = identity(ctx)
            task = bridge.prepare(principal, request, completion_target=completion_target)
            return {
                **task,
                "local_approval_url": LOCAL_APPROVAL_URL,
                "approval_required": task["state"] == "created",
                "approval_mode": config.principals[principal].approval_mode,
                "completion_channel": {
                    "target": (
                        bridge.store.db.execute(
                            "SELECT target FROM completion_routes WHERE task_id=?", (task["id"],)
                        ).fetchone()
                        or ["default"]
                    )[0],
                    "receive_tool": "completion_receive",
                    "ack_tool": "completion_ack",
                    "assistant_wakeup": "not_provided_by_current_transport",
                },
            }

        from kirabridge.grok_connector.conversation import result_for_conversation

        return await result_for_conversation(bridge, identity(ctx), safe(action))

    @server.tool(annotations=write)
    async def session_open(
        cwd: str,
        task_id: str,
        idempotency_key: str,
        ctx: Context,
        argv: list[str] | None = None,
    ) -> dict[str, Any]:
        """Open a new visible Terminal.app window in cwd, preserving existing tabs.

        Optional argv runs a program in the new window. Read task_get for the resulting
        pane_id and expected_pid; session_read reads output, session.input sends input.
        Reuse task_id and idempotency_key for retries of this same request.
        """
        return await task_request(
            TaskRequest(
                task_id=task_id,
                idempotency_key=idempotency_key,
                operation="session.open",
                arguments={"cwd": cwd, "argv": argv or []},
            ),
            ctx,
        )

    @server.tool(annotations=read)
    def task_events(task_id: str, ctx: Context, after: int = 0) -> dict[str, Any]:
        """Read up to 1000 task events after a cursor, only for your own task."""
        return safe(lambda: bridge.events(identity(ctx), task_id, after))

    @server.tool(annotations=read)
    def task_list(
        ctx: Context, after: int = 0, limit: int = 100, state: str | None = None
    ) -> dict[str, Any]:
        """List your task summaries with a persistent cursor and optional state filter."""
        return safe(lambda: bridge.list_tasks(identity(ctx), after, limit, state))

    @server.tool(annotations=write)
    def task_cancel(task_id: str, ctx: Context) -> dict[str, Any]:
        """Cancel your queued task. Active process termination needs a separate authorized task."""
        return safe(lambda: bridge.tasks.cancel_queued(identity(ctx), task_id))

    @server.tool(annotations=read)
    def agent_inventory(ctx: Context) -> dict[str, Any]:
        """Configured agent identities; executable presence never proves a daemon or active task."""

        def action():
            policy = bridge.security.principal(identity(ctx), "agent.inspect")
            return bridge.agents.inventory(policy.agents)

        return safe(action)

    @server.tool(annotations=write)
    def clipboard_read(
        task_id: str, idempotency_key: str, ctx: Context, approval: str = "", max_bytes: int = 65536
    ) -> dict[str, Any]:
        """Queue one clipboard read under the configured approval mode; fetch with task_get."""
        return safe(
            lambda: bridge.submit(
                identity(ctx),
                TaskRequest(
                    task_id=task_id,
                    idempotency_key=idempotency_key,
                    operation="clipboard.read",
                    arguments={"max_bytes": max_bytes},
                ),
                approval,
            )
        )

    @server.tool(annotations=write)
    def clipboard_write(
        task_id: str, idempotency_key: str, text: str, ctx: Context, approval: str = ""
    ) -> dict[str, Any]:
        """Queue a text write under the configured approval mode, with immediate readback proof."""
        return safe(
            lambda: bridge.submit(
                identity(ctx),
                TaskRequest(
                    task_id=task_id,
                    idempotency_key=idempotency_key,
                    operation="clipboard.write",
                    arguments={"text": text},
                ),
                approval,
            )
        )

    @server.tool(annotations=read)
    def clipboard_info(ctx: Context) -> dict[str, Any]:
        """Describe clipboard capabilities without reading clipboard content."""

        def action():
            bridge.security.principal(identity(ctx), "clipboard.info")
            return bridge.clipboard.info()

        return safe(action)

    delivery = ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
    )

    @server.tool(annotations=delivery)
    async def completion_receive(
        ctx: Context,
        target: str = "default",
        limit: int = 20,
        wait_seconds: float = 20,
    ) -> dict[str, Any]:
        """Wait for own durable completion notices, including already finished tasks.

        Run a persistent consumer that rearms this bounded wait; no task-status polling.
        Receipts/IDs remain stable until completion_ack after consumer processing.
        A tool response is client delivery, never proof of unsolicited assistant/chat wake-up.
        """
        try:
            return await bridge.completions.wait(identity(ctx), target, limit, wait_seconds)
        except BridgeError as exc:
            return {"error": {"code": exc.code, "message": str(exc)}}

    @server.tool(annotations=delivery)
    def completion_ack(notice_id: str, receipt: str, ctx: Context) -> dict[str, Any]:
        """Acknowledge own processed completion by stable ID and matching receipt.

        Repeating this exact acknowledgement is safe. Does not attest ChatGPT chat delivery.
        """
        return safe(lambda: bridge.completions.ack(identity(ctx), notice_id, receipt))

    @server.tool(annotations=write)
    async def message_send(
        message: MessageSend, ctx: Context, completion_target: str | None = None
    ) -> dict[str, Any]:
        """Send an addressed durable message; sender is your authenticated identity.

        For dispatched agent work, completion_target routes final completion_receive notices
        to the requesting assistant's stable target, even on failure or without an auto reply.
        Kinds: question, answer, work, result, note. Reuse the idempotency_key only for the
        exact same message. dispatch=true invokes the configured separate managed receiver;
        existing interactive sessions are not attached. Questions/work request one response
        by default. Answers/results never request another response. No shell interpolation.
        Returned answers stay in the sender's client inbox; they do not automatically
        start another background receiver. Grok app calls wait briefly and include
        conversation_return and reply_message. Acknowledge the reply only after processing it.
        """
        result = safe(
            lambda: bridge.messages.send(
                identity(ctx), message, completion_target=completion_target
            )
        )
        from kirabridge.grok_connector.conversation import message_for_conversation

        return await message_for_conversation(bridge, identity(ctx), result)

    @server.tool(annotations=read)
    async def message_get(message_id: str, ctx: Context) -> dict[str, Any]:
        """Read your message, delivery receipt, acknowledgement and worker evidence.

        For the Grok app, waits briefly for its addressed agent's answer. If
        conversation_return.continue_required, keep waiting on this same message ID.
        """
        from kirabridge.grok_connector.conversation import message_for_conversation

        result = safe(lambda: bridge.messages.get(identity(ctx), message_id))
        return await message_for_conversation(bridge, identity(ctx), result)

    @server.tool(annotations=delivery)
    async def message_receive(
        ctx: Context,
        after: int = 0,
        limit: int = 20,
        conversation_id: str | None = None,
        wait_seconds: float = 0,
    ) -> dict[str, Any]:
        """Receive your unacknowledged messages in sequence; long polling is bounded to 20s.

        Reconnect with after=0 to recover unacknowledged messages, retaining IDs/receipts.
        Receipt proves delivery to this client, not completion of an agent task.
        """
        try:
            return await bridge.messages.wait(
                identity(ctx), after, limit, conversation_id, wait_seconds
            )
        except BridgeError as exc:
            return {"error": {"code": exc.code, "message": str(exc)}}
        except Exception:
            return {"error": {"code": "internal_error", "message": "Message receive failed"}}

    @server.tool(annotations=delivery)
    def message_ack(message_id: str, receipt: str, ctx: Context) -> dict[str, Any]:
        """Idempotently acknowledge an incoming message using its delivery receipt."""
        return safe(lambda: bridge.messages.ack(identity(ctx), message_id, receipt))

    @server.tool(annotations=read)
    def conversation_get(
        conversation_id: str,
        ctx: Context,
        after: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Read a conversation you participate in, including replies and processing evidence."""
        return safe(
            lambda: bridge.messages.conversation(identity(ctx), conversation_id, after, limit)
        )

    @server.tool(annotations=read)
    def message_events(message_id: str, ctx: Context, after: int = 0) -> dict[str, Any]:
        """Read ordered delivery/acknowledgement/processing events for your own message."""
        return safe(lambda: bridge.messages.events(identity(ctx), message_id, after))

    @server.tool(annotations=read)
    def message_channel_status(ctx: Context) -> dict[str, Any]:
        """Report peers and the separate receiver's state; never claim active UI access."""

        def action():
            principal = identity(ctx)
            policy = bridge.security.principal(principal, "message.read")
            states = bridge.store.db.execute(
                "SELECT j.state,count(*) AS count FROM message_jobs j JOIN messages m "
                "ON m.id=j.message_id WHERE m.recipient=? GROUP BY j.state",
                (principal,),
            ).fetchall()
            return {
                "api_version": "1",
                "principal": principal,
                "peers": policy.message_peers,
                "approval_mode": policy.approval_mode,
                "receiver_configured": principal in config.messaging.receivers,
                "receiver_active": bool(
                    principal in config.messaging.receivers
                    and bridge.message_receiver.worker
                    and not bridge.message_receiver.worker.done()
                ),
                "receiver_status_scope": "authenticated_principal_inbox",
                "dispatcher_active": bool(
                    bridge.message_receiver.worker and not bridge.message_receiver.worker.done()
                ),
                "peer_receivers": {
                    peer: {
                        "receiver_configured": peer in config.messaging.receivers,
                        "receiver_active": bool(
                            peer in config.messaging.receivers
                            and bridge.message_receiver.worker
                            and not bridge.message_receiver.worker.done()
                        ),
                    }
                    for peer in policy.message_peers
                },
                "session_scope": "separate_managed_session",
                "existing_session_attached": False,
                "interactive_session_access": {
                    "mode": "on_demand_exact_target",
                    "catalog_tool": "session_catalog",
                    "read_tool": "session_read",
                    "open_tool": "session_open",
                    "input_operation": "session.input",
                },
                "jobs": {row["state"]: row["count"] for row in states},
                "limits": config.messaging.model_dump(exclude={"receivers"}),
            }

        return safe(action)

    # Fresh names provide a clean contract for clients retaining the historical
    # task_* schema. Authentication, authorization and idempotency stay identical.
    server.add_tool(
        task_request,
        name="action_request",
        annotations=write,
        description=(
            "Execute any authorized catalog operation; no Events subscription required. "
            "Poll task_get for evidence. Same idempotent task_request implementation."
        ),
    )
    server.add_tool(
        task_submit,
        name="action_submit",
        annotations=write,
        description=(
            "Submit any authorized operation; no Events subscription required. "
            "Automatic identities need no approval token. Poll task_get."
        ),
    )

    @server.tool(annotations=write)
    def team_create(request: TeamCreate, ctx: Context) -> dict[str, Any]:
        """Create an operator-enabled team; authenticated creator remains owner."""
        return safe(lambda: bridge.teams.create(identity(ctx), request))

    @server.tool(annotations=read)
    def team_list(ctx: Context) -> dict[str, Any]:
        """List teams this authenticated identity belongs to; no private task disclosure."""
        return safe(lambda: bridge.teams.list(identity(ctx)))

    @server.tool(annotations=read)
    def team_get(team_id: str, ctx: Context) -> dict[str, Any]:
        """Read team members, actual roles and configuration revision."""
        return safe(lambda: bridge.teams.get(identity(ctx), team_id))

    @server.tool(annotations=read)
    def team_context(team_id: str, ctx: Context) -> dict[str, Any]:
        """Bounded current team context, recent results and this member's pending messages."""
        return safe(lambda: bridge.teams.context(identity(ctx), team_id))

    @server.tool(annotations=write)
    def team_set_role(request: TeamRoleSet, ctx: Context) -> dict[str, Any]:
        """Owner/coordinator changes a role with revision CAS; coordinator switch is atomic."""
        return safe(lambda: bridge.teams.set_role(identity(ctx), request))

    @server.tool(annotations=write)
    def team_message_send(request: TeamMessageSend, ctx: Context) -> dict[str, Any]:
        """Send addressed team data; sender comes from authenticated identity, never a field."""
        return safe(lambda: bridge.teams.send(identity(ctx), request))

    @server.tool(annotations=read)
    def team_messages(
        team_id: str, ctx: Context, after: int = 0, limit: int = 50
    ) -> dict[str, Any]:
        """Read bounded intentional team messages; does not expose private mailboxes."""
        return safe(lambda: bridge.teams.messages(identity(ctx), team_id, after, limit))

    @server.tool(annotations=write)
    def team_message_ack(team_id: str, message_id: str, ctx: Context) -> dict[str, Any]:
        """Only the actual addressed recipient acknowledges receipt; not execution proof."""
        return safe(lambda: bridge.teams.ack(identity(ctx), team_id, message_id))

    @server.tool(annotations=write)
    def team_work_create(request: TeamWorkCreate, ctx: Context) -> dict[str, Any]:
        """Assign work to an enabled teammate; own ancestry and idempotency prevent loops."""
        return safe(lambda: bridge.teams.delegate(identity(ctx), request))

    @server.tool(annotations=read)
    def team_work_get(team_id: str, work_id: str, ctx: Context) -> dict[str, Any]:
        """Read one team assignment, native evidence and shared result; unknown stays unknown."""
        return safe(lambda: bridge.teams.work_get(identity(ctx), team_id, work_id))

    @server.tool(annotations=read)
    def team_work_list(
        team_id: str, ctx: Context, after: int = 0, limit: int = 50
    ) -> dict[str, Any]:
        """Read a team's bounded assignment board, including finished work."""
        return safe(lambda: bridge.teams.work_list(identity(ctx), team_id, after, limit))

    @server.tool(annotations=write)
    def team_work_claim(request: TeamWorkClaim, ctx: Context) -> dict[str, Any]:
        """External/manual assignee accepts its own work; cannot claim another agent's identity."""
        return safe(lambda: bridge.teams.work_claim(identity(ctx), request))

    @server.tool(annotations=write)
    def team_work_complete(request: TeamWorkComplete, ctx: Context) -> dict[str, Any]:
        """External assignee reports its own result; evidence explicitly remains assignee_report."""
        return safe(lambda: bridge.teams.work_complete(identity(ctx), request))

    @server.tool(annotations=write)
    def team_work_reprocess(request: TeamWorkReprocess, ctx: Context) -> dict[str, Any]:
        """Owner/coordinator processes a pinned completed result; never reruns its model."""
        return safe(lambda: bridge.teams.work_reprocess(identity(ctx), request))

    @server.tool(annotations=read)
    def team_events(team_id: str, ctx: Context, after: int = 0, limit: int = 50) -> dict[str, Any]:
        """Read ordered team role/delegation/delivery events, without secret/raw error logs."""
        return safe(lambda: bridge.teams.events(identity(ctx), team_id, after, limit))

    return server
