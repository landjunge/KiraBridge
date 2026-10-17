from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from kirabridge import LOCAL_APPROVAL_URL
from kirabridge.bridge_core.bridge import INPUTS, Bridge
from kirabridge.bridge_core.models import BridgeError, TaskRequest


def create_server(bridge: Bridge, *, transport: str = "stdio", principal: str = "local") -> FastMCP:
    config = bridge.config
    server = FastMCP(
        "KiraBridge",
        instructions="API v1. Every task needs a locally issued exact-task approval. "
        "Send the operator to local_approval_url on their Mac; requests appear there "
        "automatically. Do not ask them to copy task IDs between chats. "
        "Acceptance is a receipt, not execution. Query task_get and task_events for evidence.",
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
            return {"error": {"code": exc.code, "message": str(exc)}}
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
    def operation_catalog(ctx: Context) -> dict[str, Any]:
        """Permitted version-1 operations and exact argument JSON schemas."""

        def action():
            policy = bridge.security.principal(identity(ctx))
            return {
                "api_version": "1",
                "operations": {
                    name: {"arguments": model.model_json_schema(), "approval_required": True}
                    for name, model in INPUTS.items()
                    if name in policy.capabilities
                },
            }

        return safe(action)

    @server.tool(annotations=write)
    def task_submit(request: TaskRequest, approval: str, ctx: Context) -> dict[str, Any]:
        """Persist an exact approved task; repeating its idempotency key never executes it twice."""
        return safe(lambda: bridge.submit(identity(ctx), request, approval))

    @server.tool(annotations=read)
    def task_get(task_id: str, ctx: Context) -> dict[str, Any]:
        """Read your task, receipt, timestamps, result and evidence-backed state."""
        return safe(lambda: bridge.task(identity(ctx), task_id))

    @server.tool(annotations=write)
    def task_request(request: TaskRequest, ctx: Context) -> dict[str, Any]:
        """Request local approval. This stores a pending request and executes nothing.

        Give the operator local_approval_url to approve in their Mac browser, then poll task_get.
        Requests appear automatically; do not ask them to copy task IDs between chats.
        Never claim execution while the task remains created (awaiting approval).
        """

        def action():
            task = bridge.prepare(identity(ctx), request)
            return {
                **task,
                "local_approval_url": LOCAL_APPROVAL_URL,
                "approval_required": task["state"] == "created",
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
        """Cancel your queued task. Active process termination needs a separate approved task."""
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
        task_id: str, idempotency_key: str, approval: str, ctx: Context, max_bytes: int = 65536
    ) -> dict[str, Any]:
        """Queue one explicitly approved clipboard read. Fetch its result with task_get."""
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
        task_id: str, idempotency_key: str, approval: str, text: str, ctx: Context
    ) -> dict[str, Any]:
        """Queue an approved text write with content digest and immediate readback confirmation."""
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

    return server
