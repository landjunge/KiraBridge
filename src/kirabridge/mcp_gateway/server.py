from __future__ import annotations

from collections.abc import Callable
from typing import Any

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
        "Acceptance is a receipt, not execution. Query task_get and task_events for evidence. "
        "Use message_send/message_receive for addressed peer communication. "
        "Automatic message receivers use separate managed sessions, not existing interactive ones; "
        "check message_channel_status and message_get for actual evidence. "
        "Use team_* tools for shared role-based teams, addressed communication and delegated work. "
        "Team results are shared only with team members; private tasks stay private. "
        "ChatGPT is an external participant and is never automatically awakened by a team role.",
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
        Use file.read/file.image via task_request for actual content; no cat/Python workaround.
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
    def operation_catalog(ctx: Context) -> dict[str, Any]:
        """Permitted version-1 operations and exact argument JSON schemas."""

        def action():
            policy = bridge.security.principal(identity(ctx))
            return {
                "api_version": "1",
                "approval_mode": policy.approval_mode,
                "operations": {
                    name: {
                        "arguments": model.model_json_schema(),
                        "approval_required": policy.approval_mode == "manual",
                    }
                    for name, model in INPUTS.items()
                    if name in policy.capabilities
                },
            }

        return safe(action)

    @server.tool(annotations=write)
    def task_submit(request: TaskRequest, ctx: Context, approval: str = "") -> dict[str, Any]:
        """Queue a task; automatic mode needs no token, manual mode requires an exact-task grant.

        Repeating its idempotency key never executes it twice.
        """
        return safe(lambda: bridge.submit(identity(ctx), request, approval))

    @server.tool(annotations=read)
    def task_get(task_id: str, ctx: Context) -> dict[str, Any]:
        """Read own task and evidence; completed file.image also returns bounded MCP image content.

        The PNG is a saved snapshot, not a fresh read. Other tasks retain their JSON format.
        """
        return safe(lambda: image_task_result(bridge.task(identity(ctx), task_id)))

    @server.tool(annotations=read)
    def task_diagnose(task_id: str, ctx: Context) -> dict[str, Any]:
        """Compact owner-only failure/preflight/runtime view of existing task and audit evidence.

        No contents, prompts, arguments or implicit retries. Historical unknowns stay unknown.
        """
        from kirabridge.diagnostics import task_report

        return safe(lambda: task_report(bridge, identity(ctx), task_id))

    @server.tool(annotations=write)
    def task_request(request: TaskRequest, ctx: Context) -> dict[str, Any]:
        """Queue permitted work automatically, or request approval if this identity is manual.

        Check approval_required: false means no browser click is needed; poll task_get.
        Only when true, give the operator local_approval_url to approve in their Mac browser.
        Do not ask them to copy task IDs between chats. A queued receipt is not proof of execution.
        """

        def action():
            principal = identity(ctx)
            task = bridge.prepare(principal, request)
            return {
                **task,
                "local_approval_url": LOCAL_APPROVAL_URL,
                "approval_required": task["state"] == "created",
                "approval_mode": config.principals[principal].approval_mode,
            }

        return safe(action)

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

    @server.tool(annotations=write)
    def message_send(message: MessageSend, ctx: Context) -> dict[str, Any]:
        """Send an addressed durable message; sender is your authenticated identity.

        Kinds: question, answer, work, result, note. Reuse the idempotency_key only for the
        exact same message. dispatch=true invokes the configured separate managed receiver;
        existing interactive sessions are not attached. Questions/work request one response
        by default. Answers/results never request another response. No shell interpolation.
        """
        return safe(lambda: bridge.messages.send(identity(ctx), message))

    @server.tool(annotations=read)
    def message_get(message_id: str, ctx: Context) -> dict[str, Any]:
        """Read your message, delivery receipt, acknowledgement and worker evidence."""
        return safe(lambda: bridge.messages.get(identity(ctx), message_id))

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
                "session_scope": "separate_managed_session",
                "existing_session_attached": False,
                "jobs": {row["state"]: row["count"] for row in states},
                "limits": config.messaging.model_dump(exclude={"receivers"}),
            }

        return safe(action)

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
