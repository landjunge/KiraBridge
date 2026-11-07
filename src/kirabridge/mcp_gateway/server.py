from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from kirabridge import LOCAL_APPROVAL_URL, __version__
from kirabridge.bridge_core.bridge import INPUTS, Bridge
from kirabridge.bridge_core.models import BridgeError, TaskRequest
from kirabridge.image_manager import image_task_result
from kirabridge.keyboard_control import KeyboardControlInput
from kirabridge.keyboard_sequence import KeyboardSequenceInput
from kirabridge.keyboard_system import KeyboardSystemKeyInput
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


def inline_task_timeout(operation: str) -> float:
    """Bound result observation without changing the durable execution deadline."""
    from kirabridge.desktop_input import DESKTOP_EFFECT_OPERATIONS

    if operation in DESKTOP_EFFECT_OPERATIONS or operation.startswith(
        ("keyboard.", "windows.keyboard.", "windows.window.", "windows.app.", "windows.console.")
    ):
        return 13  # The existing desktop transaction has a twelve-second deadline.
    if operation in {"session.catalog", "session.read"}:
        from kirabridge.terminal_queries import TERMINAL_QUERY_SECONDS

        return TERMINAL_QUERY_SECONDS + 1
    if operation in {
        "agent.execute",
        "terminal.execute",
        "terminal.visible",
        "admin.execute",
        "system.report",
        "session.input",
        "files.transfer",
        "handoff.start",
    }:
        return 1
    return 2


def create_server(bridge: Bridge, *, transport: str = "stdio", principal: str = "local") -> FastMCP:
    config = bridge.config
    server = FastMCP(
        "KiraBridge",
        instructions="Direct ChatGPT terminal commands use terminal_control (terminal.visible); "
        "terminal.execute for chatgpt also uses a confirmed visible shell. "
        "If no suitable idle window exists, open a separate visible window "
        "under the same task grant. "
        "Never type into busy/unconfirmed windows or fall back to a hidden session. "
        "This direct-control rule does not prescribe Codex/Grok internal workflows. "
        "ThreadDesk is a separate access path. Refresh tools/list and operation_catalog after "
        "connection, version or session changes; compare discovery.revision. API v1. "
        "Check per-operation permission_decision; approval_mode is legacy policy metadata. "
        "Use task_request: automatic mode admits permitted work without a browser click. "
        "Use keyboard_sequence for requested genuine individual keystrokes; "
        "use keyboard_control text for literal text. Keep adaptive steps separate. "
        "If a cached Apps catalog lacks keyboard_sequence, submit the same steps through "
        "action_request request.operation=keyboard.sequence; never split known text or a "
        "known key sequence into one cloud call per character. "
        "Use read_queries to combine independent reads in one roundtrip. "
        "Use read_tools or read_query operation=tool.batch for mixed read-only tools. "
        "Use read_query native.read for automatic apps/windows/accessibility reads without "
        "tasks; accessibility.inspect max_depth>0 returns a bounded descendant tree in one read. "
        "Prefer result_format=structured for batches: all structured values and errors "
        "remain, only duplicate JSON text is omitted. Full remains available. "
        "For known arguments submit directly; do not prefetch health or the full catalog "
        "before every action. Request operation_catalog operations=[...] for needed schemas. "
        "A completed inline result needs no task_get/events/completion poll. "
        "For pending work use read_query operation=task.observe with the same task_id, "
        "wait_seconds<=18 and events_after to receive status and evidence together. "
        "Choose an application by name or an exact PID/start pair, or omit the selector "
        "for the fresh foreground application. Target inspection is automatic. "
        "No Events subscription is needed. Read task_get for execution evidence; "
        "posting keys does not prove that the application processed them. "
        "New visible delivery has one immediate attempt; a blocked target returns a clear error. "
        "Only when approval_required is true, send the operator to local_approval_url. "
        "Do not ask for approval when approval_required is false. "
        "Do not ask them to copy task IDs between chats. "
        "Acceptance is a receipt, not execution. For completion, set completion_target and keep "
        "a completion_receive consumer active; ack only after processing. "
        "This return channel cannot wake an inactive ChatGPT chat. "
        "Query task_get and task_events for additional evidence. "
        "Use message_send/message_receive for addressed peer communication. "
        "Use team_* tools for shared role-based teams, addressed communication and delegated work. "
        "For an explicitly configured native AutoNext coordinator, coordinator_status reads "
        "its owner-scoped phases; completion_receive/ack consumes its durable terminal notices. "
        "Only pinned grants and successful checks advance work; reading or acknowledging "
        "a notice grants no execution rights. "
        "Team results are shared only with team members; private tasks stay private. "
        "ChatGPT is an external participant and is never automatically awakened by a team role. "
        "Agent handoffs require assigned existing visible terminals, with no background fallback; "
        "check message_channel_status and message_get for actual evidence. "
        "For visible macOS terminals use session_catalog/session_read and session_open. "
        "Send input only to an exact pane_id and expected_pid using operation session.input. "
        "session.input sends literal text and slash commands; submit=false pastes without Return. "
        "Use agent.execute or message_send(kind=work) for addressed agent assignments. "
        "session_input_policy is an optional confirmation buffer, not a terminal enable switch. "
        "agent_status includes existing interactive_terminal_sessions. Cached clients can use "
        "task_request operations session.catalog (empty arguments) and session.read "
        "(pane_id, expected_pid, optional max_bytes, optional since) wait and return the "
        "resolved text. next_cursor plus since reads only newer output in appended; "
        "follow is full, append, unchanged, or reset. text remains the current screen. "
        "read_query accepts the same session.read fields. A read does not focus or type. "
        "Eve = Grok Voice; Grok Build = Grok Terminal; Kira = ChatGPT Voice; "
        "Codex = ChatGPT Terminal. Eve relays only Daniel's dictation unchanged, "
        "without additions. Explicit requests need no special voice token. "
        "terminal-to-terminal messages are immediate. Voice-to-voice messages use "
        "the shared participant-only append-only conversation.",
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

    server._mcp_server.version = __version__

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

    @server.tool(annotations=read)
    async def macos_status(ctx: Context, check_helpers: bool = False) -> dict[str, Any]:
        """Inspect native capabilities and public no-prompt Core permission checks.

        Core checks never authorize osascript, Clipboard helpers or the desktop app.
        Unknown helper permissions still require the existing native target guards.
        check_helpers adds bounded no-prompt diagnostics from one transient helper;
        its observations never authorize future helpers or change OS permissions.
        """
        from kirabridge.discovery import snapshot

        name = identity(ctx)
        try:
            before = snapshot(bridge, name)["revision"]
            result = await bridge.platform_status(name, check_helpers=check_helpers)
            if snapshot(bridge, name)["revision"] != before:
                await ctx.session.send_tool_list_changed()
            return result
        except BridgeError as exc:
            return {"error": {"code": exc.code, "message": str(exc)}}

    write = ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True
    )

    @server.tool(annotations=read)
    async def bridge_health(ctx: Context, observe_terminals: bool = False) -> dict[str, Any]:
        """Lightweight live daemon health; cached terminal observations are not input proof.

        Set observe_terminals=true for an explicit bounded fresh terminal catalogue.
        Routine polling must not consume the foreground terminal-read lane.
        Never claims ChatGPT integration.
        """
        from kirabridge.discovery import live

        name = identity(ctx)
        try:
            if observe_terminals:
                discovery = await live(bridge, name)
                return {**bridge.health(name), "discovery": discovery}
            return bridge.health(name)
        except BridgeError as exc:
            return {"error": {"code": exc.code, "message": str(exc)}}

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
        """Managed work and exact existing terminal handles; discovery never sends input."""
        from kirabridge.development_status import agent_status as inspect

        try:
            name = identity(ctx)
            bridge.security.principal(name, "agent.status")
            return await inspect(bridge, name)
        except BridgeError as exc:
            return {"error": {"code": exc.code, "message": str(exc)}}

    @server.tool(annotations=read)
    async def read_query(query: dict[str, Any], ctx: Context) -> dict[str, Any]:
        """Direct authorized read without tasks or Events subscriptions.

        Native JSON reads use {operation:"native.read", native_operation, arguments,
        max_bytes<=524288}. Exact supported operations: apps.list, apps.inspect,
        windows.list, windows.inspect, accessibility.status, accessibility.inspect.
        Uses the same typed arguments and fresh native guards; automatic rights
        required, otherwise submit the native operation through task_request.
        No tasks/notices, input, capture or permission requests. Result is in result.
        accessibility.inspect with max_depth>0 reads a bounded descendant tree:
        max_nodes<=512, tree_budget_ms<=5000, max_tree_bytes capped by max_bytes.
        Set max_bytes=262144 for a larger tree (default is 32768); read.batch
        still limits the combined requested budgets to 256 KiB.
        Tree completeness is explicit; snapshots are not atomic. Retain returned
        node tokens, worker identity and revisions for later guarded actions.

        Cached clients may use operation=read.batch with queries=[...] or
        operation=tool.batch with calls=[{tool,arguments},...] for mixed existing
        read-only tools. Both accept 1–8 reads; nested batches and writes rejected.
        For tool.batch, result_format=structured avoids redundant child JSON text;
        full (default) preserves original MCP envelopes. Neither removes data fields.
        task.observe accepts existing task_id, wait_seconds<=18 and events_after:
        waits without execution/retry and returns task plus events in one response.

        query.operation: file.read (path, max_bytes<=65536, offset or tail,
        encoding=utf-8|base64, expected_identity). For complete/binary logs use
        data_base64, verify content_sha256, then follow next_offset until eof.
        Pin the first identity; file_changed requires a stable authorized export.
        Page budgets do not limit total file size. Text is a display preview;
        text_lossless=false never means the original data_base64 bytes were lost.
        file.list (path; at most 100 entries), terminal.output (owned task_id,
        max_bytes<=65536). session.catalog lists existing terminal handles;
        session.read requires exact pane_id and expected_pid, max_bytes<=65536.
        Optional since is the previous next_cursor. appended is only the new text.
        Session reads require session.inspect and the shared permission decision.
        When approval is required, submit the same operation using task_request.
        No shell input or process attachment.
        platform.status accepts check_helpers=true for explicit no-prompt helper
        diagnostics. These transient observations never authorize later workers.
        """
        from kirabridge.read_query import ReadQuery, read_query_async

        try:
            if query.get("operation") == "tool.batch":
                from kirabridge.read_tool_batch import read_tool_batch

                if not {"operation", "calls"} <= set(query) or set(query) - {
                    "operation",
                    "calls",
                    "result_format",
                }:
                    return {"error": {"code": "invalid_arguments"}}
                return await read_tool_batch(
                    server,
                    bridge,
                    identity(ctx),
                    query["calls"],
                    result_format=query.get("result_format", "full"),
                )
            if query.get("operation") == "read.batch":
                from kirabridge.read_queries import ReadQueries
                from kirabridge.read_queries import read_queries as execute_reads

                if set(query) != {"operation", "queries"}:
                    return {"error": {"code": "invalid_arguments"}}
                return await execute_reads(
                    bridge, identity(ctx), ReadQueries(queries=query["queries"])
                )
            return await read_query_async(bridge, identity(ctx), ReadQuery.model_validate(query))
        except BridgeError as exc:
            return {"error": {"code": exc.code, "message": str(exc)}}
        except ValidationError:
            return {"error": {"code": "invalid_arguments", "message": "Invalid read query"}}

    @server.tool(annotations=read)
    async def read_tools(
        calls: list[dict[str, Any]],
        ctx: Context,
        result_format: Literal["full", "structured"] = "full",
    ) -> dict[str, Any]:
        """Combine 1–8 independent existing read-only tools in one cloud roundtrip.

        Each call is {tool,arguments}. Exact allowed names and all argument schemas
        are validated before the first read. Normal tool authorization remains
        fresh per call. No writes, nested batches, retries or atomic snapshots.
        Allowed: bridge_health, clipboard_info, operation_catalog, task_get,
        task_events, task_diagnose, task_list, policy_inspect, bridge_readiness,
        agent_inventory, macos_status, session_catalog, session_read,
        whiteboard_read, read_query (one non-batch query).
        JSON text results only: use the original tool for images. The cooperative
        deadline is 12s and the result budget 2 MiB; partial results are explicit.
        Cached clients can use read_query operation=tool.batch with these calls.
        Prefer result_format=structured to omit only equivalent child JSON text;
        all structured fields, errors and metadata remain. Full is backwards compatible.
        """
        from kirabridge.read_tool_batch import read_tool_batch

        try:
            return await read_tool_batch(
                server, bridge, identity(ctx), calls, result_format=result_format
            )
        except BridgeError as exc:
            return {"error": {"code": exc.code, "message": str(exc)}}

    @server.tool(annotations=read)
    async def read_queries(queries: list[dict[str, Any]], ctx: Context) -> dict[str, Any]:
        """Perform 1–8 independent authorized reads in one roundtrip.

        Same query objects, permissions and ranges as read_query. Reads execute
        serially and independently; results are not an atomic snapshot. No writes,
        input, clipboard use, tasks or automatic retries. Combined byte budget
        <=256 KiB, directory pages <=100. The batch has a 12 second cooperative
        deadline; a synchronous file read may overrun it, but no further read
        starts after expiry.
        """
        from kirabridge.read_queries import ReadQueries
        from kirabridge.read_queries import read_queries as execute_reads

        try:
            request = ReadQueries(queries=queries)
            return await execute_reads(bridge, identity(ctx), request)
        except ValidationError:
            return {"error": {"code": "invalid_arguments", "message": "Invalid read batch"}}

    @server.tool(annotations=read)
    async def session_catalog(ctx: Context) -> dict[str, Any]:
        """List existing Terminal.app tabs and tmux panes with exact input/read handles."""
        try:
            return await bridge.terminal_queries.execute(identity(ctx), "session.catalog", {})
        except BridgeError as exc:
            return {"error": {"code": exc.code, "message": str(exc)}}

    @server.tool(annotations=read)
    async def session_read(
        pane_id: str, expected_pid: int, ctx: Context, since: str = ""
    ) -> dict[str, Any]:
        """Read one terminal without focusing it. Pass since=next_cursor for newer output only."""
        try:
            arguments = {"pane_id": pane_id, "expected_pid": expected_pid}
            if since:
                arguments["since"] = since
            return await bridge.terminal_queries.execute(identity(ctx), "session.read", arguments)
        except BridgeError as exc:
            return {"error": {"code": exc.code, "message": str(exc)}}

    @server.tool(annotations=read)
    def visible_handoff_status(handoff_id: str, ctx: Context) -> dict[str, Any]:
        """Read/reconcile visible input, Return and authenticated acknowledgement; never resend."""

        def action():
            principal = identity(ctx)
            result = bridge.visible_handoffs.reconcile(principal, handoff_id)
            if result["state"] == "completed":
                try:
                    result["receiver_reconciliation"] = (
                        bridge.message_receiver.reconcile_completed_handoff(principal, handoff_id)
                    )
                except BridgeError as exc:
                    if exc.code != "forbidden":
                        raise
                    # Handoff readers without mailbox access retain their read.
                    result["receiver_reconciliation"] = {
                        "reconciled": False,
                        "reason": "message_read_unavailable",
                    }
            return result

        return safe(action)

    @server.tool(annotations=read)
    async def threaddesk_dynamic_catalog(ctx: Context) -> dict[str, Any]:
        """Discover the configured ThreadDesk tools allowed by current operator policy."""
        from kirabridge.threaddesk_dynamic import catalog

        try:
            return await catalog(bridge, identity(ctx))
        except BridgeError as exc:
            return {"error": {"code": exc.code, "message": str(exc)}}

    @server.tool(annotations=read)
    def whiteboard_read(
        ctx: Context, thread_id: str | None = None, entry_id: str | None = None
    ) -> dict[str, Any]:
        """Read one ThreadDesk whiteboard, or one entry, without switching threads.

        Uses only the configured ThreadDesk workspace files. Does not append,
        execute whiteboard text, or change the active thread. Omit thread_id to
        read the active thread. Pass the repair thread id to read that board.
        """
        from kirabridge.whiteboard_read import read_whiteboard

        def action():
            bridge.security.principal(identity(ctx), "threaddesk.read")
            workspace = bridge.config.threaddesk.workspace
            if not workspace:
                raise BridgeError("threaddesk_workspace", "Whiteboard workspace is not configured")
            return read_whiteboard(workspace, thread_id, entry_id)

        return safe(action)

    @server.tool(annotations=write)
    def whiteboard_append(
        thread_id: str,
        entry_type: str,
        content: str,
        actor: str,
        actor_type: str,
        ctx: Context,
        external_key: str | None = None,
    ) -> dict[str, Any]:
        """Append one entry to an explicitly selected whiteboard.

        Existing files are not rewritten. Repeat the same external_key to
        receive the original entry id again. The result is untrusted data.
        """
        from kirabridge.whiteboard_read import append_whiteboard

        def action():
            bridge.security.principal(identity(ctx), "threaddesk.manage")
            workspace = bridge.config.threaddesk.workspace
            if not workspace:
                raise BridgeError("threaddesk_workspace", "Whiteboard workspace is not configured")
            return append_whiteboard(
                workspace,
                thread_id,
                actor=actor,
                actor_type=actor_type,
                entry_type=entry_type,
                content=content,
                external_key=external_key,
            )

        return safe(action)

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)
    )
    async def threaddesk_dynamic_call(
        name: str, arguments: dict[str, Any], ctx: Context, operation_id: str | None = None
    ) -> dict[str, Any]:
        """Call a fresh authorized ThreadDesk tool; mutations require a stable operation_id."""
        from kirabridge.threaddesk_dynamic import call as dynamic_call

        try:
            return await dynamic_call(bridge, identity(ctx), name, arguments, operation_id)
        except BridgeError as exc:
            return {"error": {"code": exc.code, "message": str(exc)}}

    @server.tool(annotations=read)
    async def operation_catalog(
        ctx: Context,
        observe_terminals: bool = False,
        operations: list[str] | None = None,
    ) -> dict[str, Any]:
        """Permitted version-1 operations and exact argument JSON schemas.

        Schema discovery does not inspect terminal sessions by default. Set
        observe_terminals=true for an explicit fresh terminal catalogue. The
        default discovery labels prior terminal observations as cached/not_probed;
        observations never authorize input or replace fresh target validation.
        Set operations to 1–32 exact operation names to obtain only the argument
        schemas needed for this action; omit it for the complete permitted catalog.
        """

        def action():
            from kirabridge.operations import OPERATIONS
            from kirabridge.permissions import LEVELS, decision, level_for, permission_summary
            from kirabridge.terminal_access import terminal_access
            from kirabridge.terminal_queries import TERMINAL_QUERY_SECONDS
            from kirabridge.windows_setup_verification import verification_catalog

            policy = bridge.security.principal(identity(ctx))
            setup_reads = verification_catalog(bridge, identity(ctx))
            if operations is not None and (
                not 1 <= len(operations) <= 32
                or len(set(operations)) != len(operations)
                or any(name not in INPUTS and name not in setup_reads for name in operations)
            ):
                raise BridgeError("invalid_arguments", "Select 1–32 distinct known operations")
            platform_rows = {
                row["operation"]: row
                for row in bridge.macos.operation_catalog(
                    lambda op: decision(bridge.config, identity(ctx), op)
                )
            }
            platform_rows.update(
                {
                    row["operation"]: row
                    for row in bridge.windows_keyboard.catalog(
                        lambda op: decision(bridge.config, identity(ctx), op)
                    )
                }
            )
            platform_rows.update(
                {
                    row["operation"]: row
                    for row in bridge.windows_windows.catalog(
                        lambda op: decision(bridge.config, identity(ctx), op)
                    )
                }
            )
            # Host platform is a process-lifetime fact. Do not reconstruct the
            # full native capability snapshot for every operation in this request.
            native_host = bridge.macos.host_platform == "darwin"
            result = {
                "api_version": "1",
                "approval_mode": policy.approval_mode,
                "permission_level": level_for(policy),
                "permission_label": LEVELS[level_for(policy)],
                "permission_detail": permission_summary(bridge.config, identity(ctx)),
                "session_input_policy": bridge.config.session_input_policy.model_dump(),
                "terminal_access": terminal_access(bridge.config, identity(ctx)),
                "automatic_operations": policy.automatic_operations,
                "voice_messaging": bridge.config.voice_messaging.model_dump(),
                "visible_handoffs": {
                    **bridge.config.visible_handoffs.model_dump(),
                    "payload_contract": "unchanged_body_only",
                    "maximum_visible_prompt_characters": 16384,
                    "reply_sources": {
                        "authenticated_mailbox": True,
                        "bound_local_codex_rollout": (
                            "requires independent process/thread/file/cursor proof"
                        ),
                    },
                    "automatic_prompt_additions": False,
                },
                **bridge.messages.voice_channel.profile(identity(ctx)),
                "operations": {
                    name: {
                        **OPERATIONS[name].describe(),
                        "execution_budget_seconds": TERMINAL_QUERY_SECONDS
                        if name in {"session.catalog", "session.read"}
                        else None,
                        "arguments": model.model_json_schema(),
                        "approval_required": decision(bridge.config, identity(ctx), name)[
                            "approval_required"
                        ],
                        "permission_decision": decision(bridge.config, identity(ctx), name),
                        **({"platform": platform_rows[name]} if name in platform_rows else {}),
                    }
                    for name, model in INPUTS.items()
                    if (operations is None or name in operations)
                    and decision(bridge.config, identity(ctx), name)["authorized"]
                    and (
                        name not in platform_rows
                        or name
                        in {
                            "session.catalog",
                            "session.read",
                            "session.input",
                            "session.focus",
                            "session.close",
                            "clipboard.info",
                        }
                        or not native_host
                        or platform_rows[name]["eligible_for_submission"]
                    )
                },
            }
            result["operations"].update(
                {
                    name: entry
                    for name, entry in setup_reads.items()
                    if operations is None or name in operations
                }
            )
            return result

        from kirabridge.discovery import live, snapshot

        result = safe(action)
        if "error" not in result:
            if operations is not None:
                result["selection"] = {
                    "requested": operations,
                    "returned": list(result["operations"]),
                    "scope": (
                        "requested permitted eligible operations; omitted entries may be "
                        "unauthorized or unavailable"
                    ),
                }
            result["discovery"] = (
                await live(bridge, identity(ctx))
                if observe_terminals
                else snapshot(bridge, identity(ctx))
            )
        return result

    @server.tool(annotations=write)
    async def task_submit(
        request: TaskRequest, ctx: Context, approval: str = "", completion_target: str | None = None
    ) -> dict[str, Any]:
        """Submit a task; automatic mode needs no token, manual mode requires an exact-task grant.

        Repeating its idempotency key never executes it twice. New native work is
        admitted once; a busy or changed target fails without a waiting backlog.
        session.input follows the principal's automatic_operations and optional buffer policy.
        A standing session.input grant needs no marker or manual approval.
        Short work returns its finished result when available within the bounded
        response budget. Pending work keeps the same ID; never resubmit it.
        task.read is required and checked before admission, so the owned result
        can be returned without leaking internal task fields.
        For the Grok app, waits briefly and returns conversation_return with the
        actual result. If continue_required is true, call task_get with this same ID.
        """
        import asyncio

        from kirabridge.grok_connector.conversation import enabled_for, result_for_conversation
        from kirabridge.task_observation import MAX_WAIT_SECONDS, observe_submitted_task

        loop = asyncio.get_running_loop()
        deadline = loop.time() + MAX_WAIT_SECONDS
        name = identity(ctx)

        def submit_readable():
            bridge.security.principal(name, "task.read")
            return bridge.submit(name, request, approval, completion_target=completion_target)

        result = safe(submit_readable)
        try:
            result = await observe_submitted_task(
                bridge,
                name,
                result,
                wait_seconds=0
                if enabled_for(bridge, name)
                else inline_task_timeout(request.operation),
                deadline=deadline,
            )
            return await result_for_conversation(
                bridge, name, result, wait_seconds=max(0, deadline - loop.time())
            )
        except BridgeError as exc:
            return {
                "id": result.get("id"),
                "error": {"code": exc.code, "message": str(exc)},
                "observation_failed": True,
                "automatic_retry": False,
            }

    @server.tool(annotations=read)
    async def task_get(task_id: str, ctx: Context) -> dict[str, Any]:
        """Read own task and evidence; completed image/capture tasks include MCP images.

        The PNG is a saved snapshot, not a fresh read. Other tasks retain their JSON format.
        ChatGPT briefly waits for this same task; it never starts or retries work.
        For the Grok app, waits for ongoing work and returns conversation_return.
        Keep waiting on this same task when continue_required is true; never resubmit it.
        """
        from kirabridge.grok_connector.conversation import enabled_for, result_for_conversation

        name = identity(ctx)
        if enabled_for(bridge, name):
            result = safe(lambda: bridge.task(name, task_id))
            result = await result_for_conversation(bridge, name, result)
        elif name == "chatgpt" or config.principals[name].client_type == "chatgpt":
            from kirabridge.task_observation import observe_task_result

            try:
                result = await observe_task_result(bridge, name, task_id, wait_seconds=2)
            except BridgeError as exc:
                return {"error": {"code": exc.code, "message": str(exc)}}
            except ValidationError:
                return {"error": {"code": "invalid_arguments", "message": "Invalid tool arguments"}}
            except Exception:
                return {
                    "error": {"code": "internal_error", "message": "Request could not be completed"}
                }
        else:
            result = safe(lambda: bridge.task(name, task_id))
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
        """Admit permitted work automatically, or request approval if this identity is manual.

        No Events subscription is required. completion_target is optional.
        Set a stable unique completion_target for the requesting assistant session.
        The return route is committed with the task before dispatch. Use completion_receive
        through a waiting consumer for the final notice, then completion_ack after processing.
        This does not wake an inactive ChatGPT chat. task_get remains diagnostic.
        Check approval_required: false means no browser click is needed.
        Only when true, give the operator local_approval_url to approve in their Mac browser.
        Do not ask them to copy task IDs between chats. A queued receipt is not proof of execution.
        New native work is attempted once; blocked targets fail clearly without a waiting backlog.
        Short work returns its finished result in this response when available.
        Cached clients without keyboard_sequence can submit operation=keyboard.sequence
        and args.steps here: ordered real key events in one request, not one call per key.
        An observation timeout never cancels work; inspect the same task ID.
        task.read is checked before admission, so a result can be read safely.
        For the Grok app, waits briefly and includes conversation_return. Speak its
        actual result when final is true. If continue_required, call task_get with
        this same task ID before finishing the conversation. This does not attest audio playback.
        """

        import asyncio

        from kirabridge.grok_connector.conversation import enabled_for, result_for_conversation
        from kirabridge.task_observation import MAX_WAIT_SECONDS, observe_submitted_task

        loop = asyncio.get_running_loop()
        deadline = loop.time() + MAX_WAIT_SECONDS
        principal = identity(ctx)

        def prepare_readable():
            bridge.security.principal(principal, "task.read")
            return bridge.prepare(principal, request, completion_target=completion_target)

        task = safe(prepare_readable)
        try:
            task = await observe_submitted_task(
                bridge,
                principal,
                task,
                wait_seconds=0
                if enabled_for(bridge, principal)
                else inline_task_timeout(request.operation),
                deadline=deadline,
            )
        except BridgeError as exc:
            return {
                "id": task.get("id"),
                "error": {"code": exc.code, "message": str(exc)},
                "observation_failed": True,
                "automatic_retry": False,
            }
        if isinstance(task, dict) and task.get("id") and task.get("state"):
            task = {
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
                    "source_id": task["id"],
                },
            }

        try:
            return await result_for_conversation(
                bridge, principal, task, wait_seconds=max(0, deadline - loop.time())
            )
        except BridgeError as exc:
            return {
                "id": task.get("id"),
                "error": {"code": exc.code, "message": str(exc)},
                "observation_failed": True,
                "automatic_retry": False,
            }

    @server.tool(annotations=write)
    async def keyboard_control(
        request: KeyboardControlInput,
        task_id: str,
        idempotency_key: str,
        ctx: Context,
        completion_target: str | None = None,
    ) -> dict[str, Any]:
        """Type text, press a key or send a chord directly, with automatic target inspection.

        No profile or Events subscription is needed. Scope auto recognizes configured
        macOS shortcuts, app forces program input, system selects system keys/actions.
        Use action names from keyboard_system_inventory for volume, brightness, media,
        Mission Control and Spaces. For literal text send the whole paragraph including
        line breaks in one text request without clipboard. For explicitly requested
        individual key events use keyboard_sequence, never substitute text insertion.
        Keep separate requests when the next key depends on the previous result.
        Repeat identical keys 1–20 times in one task. Keep dependent calls serial.
        Select an app by name, an exact PID/start pair, or the current foreground app.
        Text is literal and submit defaults to false. Chords require explicit modifiers.
        Existing identity permissions apply. Reuse the same task_id and idempotency_key
        for this same request; inspect task_get for completion and native evidence.
        Fast operations return completion inline; inspect the same task if still pending.
        A native posting receipt does not confirm application processing.
        """
        return await task_request(
            TaskRequest(
                task_id=task_id,
                idempotency_key=idempotency_key,
                operation="keyboard.control",
                arguments=request.model_dump(),
            ),
            ctx,
            completion_target,
        )

    @server.tool(annotations=write)
    async def keyboard_sequence(
        request: KeyboardSequenceInput,
        task_id: str,
        idempotency_key: str,
        ctx: Context,
        completion_target: str | None = None,
    ) -> dict[str, Any]:
        """Post ordered real key-down/key-up events in ONE request, without text insertion.

        Each step is one key/chord (optional repeat). Maximum 32 physical key pairs;
        one application, one desktop transaction, fresh native target per step.
        No clipboard, Unicode text insertion, parallel posts or automatic retry.
        Stops on changed foreground/generation, denied permissions or uncertain output.
        Inspect this SAME task after pending/partial/unknown; never replay with a new ID.
        Native receipts confirm posting, not application processing. For decisions that
        depend on each result, keep separate requests instead of predeclaring a sequence.
        """
        return await task_request(
            TaskRequest(
                task_id=task_id,
                idempotency_key=idempotency_key,
                operation="keyboard.sequence",
                arguments=request.model_dump(),
            ),
            ctx,
            completion_target,
        )

    @server.tool(annotations=read)
    async def keyboard_system_inventory(
        task_id: str,
        idempotency_key: str,
        ctx: Context,
        completion_target: str | None = None,
    ) -> dict[str, Any]:
        """Inspect macOS special keys, configured shortcuts and native worker permissions.

        Reads current device observations without posting keys or requesting OS consent.
        An available event route is not proof of an installed device or an executed effect.
        """
        return await task_request(
            TaskRequest(
                task_id=task_id,
                idempotency_key=idempotency_key,
                operation="keyboard.system_inventory",
                arguments={},
            ),
            ctx,
            completion_target,
        )

    @server.tool(annotations=write)
    async def keyboard_system_key(
        request: KeyboardSystemKeyInput,
        task_id: str,
        idempotency_key: str,
        ctx: Context,
        completion_target: str | None = None,
    ) -> dict[str, Any]:
        """Send one explicit system-scope keyboard action to a fresh foreground generation.

        Use keyboard_control with scope=system for automatic foreground resolution.
        Reuse the same task and idempotency key after a lost response; never resend effects.
        """
        return await task_request(
            TaskRequest(
                task_id=task_id,
                idempotency_key=idempotency_key,
                operation="keyboard.system_key",
                arguments=request.model_dump(),
            ),
            ctx,
            completion_target,
        )

    @server.tool(annotations=write)
    async def session_enter(
        task_id: str,
        idempotency_key: str,
        pane_id: str,
        expected_pid: int,
        expected_cursor: str,
        ctx: Context,
        expected_agent_pid: int | None = None,
        approval: str = "",
        completion_target: str | None = None,
    ) -> dict[str, Any]:
        """Send one Return without pasting, bound to a fresh session_read cursor.

        Pass next_cursor and the observed agent PID from that read. This confirms
        only a supported draft/menu and never approves an unknown permission dialog.
        Empty session.input text is not a Return instruction.
        """
        return await task_submit(
            TaskRequest(
                task_id=task_id,
                idempotency_key=idempotency_key,
                operation="session.input",
                arguments={
                    "pane_id": pane_id,
                    "expected_pid": expected_pid,
                    "key": "enter",
                    "expected_cursor": expected_cursor,
                    "expected_agent_pid": expected_agent_pid,
                },
            ),
            ctx,
            approval,
            completion_target,
        )

    @server.tool(annotations=write)
    async def session_open(
        cwd: str,
        task_id: str,
        idempotency_key: str,
        ctx: Context,
        argv: list[str] | None = None,
        window_authorization: str = "",
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
                arguments={
                    "cwd": cwd,
                    "argv": argv or [],
                    "window_authorization": window_authorization,
                },
            ),
            ctx,
        )

    @server.tool(annotations=write)
    async def terminal_control(
        argv: list[str],
        cwd: str,
        task_id: str,
        idempotency_key: str,
        ctx: Context,
        pane_id: str | None = None,
        expected_pid: int | None = None,
        create_if_needed: bool = True,
        timeout: float = 60,
    ) -> dict[str, Any]:
        """Direct work in a confirmed visible shell, with no hidden replacement.

        Reuses one suitable empty existing Terminal.app shell or opens a separate visible
        window under the same exact-task/standing grant. Busy agents are preserved.
        Optional pane_id/expected_pid binds an explicit current target. Inspect task_get
        for actual visible command completion; an uncertain outcome must never be replayed.
        Codex/Grok internal execution and ThreadDesk are separate access paths.
        """
        return await task_request(
            TaskRequest(
                task_id=task_id,
                idempotency_key=idempotency_key,
                operation="terminal.visible",
                arguments={
                    "argv": argv,
                    "cwd": cwd,
                    "pane_id": pane_id,
                    "expected_pid": expected_pid,
                    "create_if_needed": create_if_needed,
                    "timeout": timeout,
                },
            ),
            ctx,
        )

    from kirabridge.mcp_gateway.queue_tools import register_queue_tools

    register_queue_tools(server, bridge.queues, identity, task_request, safe, read, write)

    from kirabridge.mcp_gateway.file_tools import register_file_tools

    register_file_tools(
        server,
        bridge.file_transfers,
        identity,
        task_request,
        bridge.security.authorize,
        safe,
        read,
        write,
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
    async def agent_inventory(ctx: Context) -> dict[str, Any]:
        """Configured agent identities; executable presence never proves a daemon or active task."""

        from kirabridge.discovery import inventory

        try:
            return await inventory(bridge, identity(ctx))
        except BridgeError as exc:
            return {"error": {"code": exc.code, "message": str(exc)}}

    @server.tool(annotations=write)
    async def clipboard_read(
        task_id: str, idempotency_key: str, ctx: Context, approval: str = "", max_bytes: int = 65536
    ) -> dict[str, Any]:
        """Read the clipboard under normal approval, returning short work inline.

        Pending work retains the same task ID; never repeat an uncertain request.
        """
        try:
            request = TaskRequest(
                task_id=task_id,
                idempotency_key=idempotency_key,
                operation="clipboard.read",
                arguments={"max_bytes": max_bytes},
            )
        except ValidationError:
            return {"error": {"code": "invalid_arguments", "message": "Invalid tool arguments"}}
        return await task_submit(request, ctx, approval)

    @server.tool(annotations=write)
    async def clipboard_write(
        task_id: str, idempotency_key: str, text: str, ctx: Context, approval: str = ""
    ) -> dict[str, Any]:
        """Write clipboard text under normal approval, returning short work inline.

        The executor retains its readback proof; an observation timeout never retries.
        """
        try:
            request = TaskRequest(
                task_id=task_id,
                idempotency_key=idempotency_key,
                operation="clipboard.write",
                arguments={"text": text},
            )
        except ValidationError:
            return {"error": {"code": "invalid_arguments", "message": "Invalid tool arguments"}}
        return await task_submit(request, ctx, approval)

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

    @server.tool(annotations=read)
    def coordinator_status(ctx: Context) -> dict[str, Any]:
        """Read your configured coordinator's bounded phases without starting work.

        Requires team.read and the configured owner. Returns only the current
        pinned grant, work IDs/states and completion channel; no prompts/results.
        Use completion_receive on that target and completion_ack after processing
        for durable accepted/stopped notices. Cached clients can use read_query
        operation=coordinator.status. Receipt delivery does not wake an inactive chat.
        """
        from kirabridge.autonext.status import coordinator_status as project_status

        return safe(lambda: project_status(bridge, identity(ctx)))

    @server.tool(annotations=delivery)
    async def completion_receive(
        ctx: Context,
        target: str = "default",
        limit: int = 20,
        wait_seconds: float = 20,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        """Wait for own durable completion notices, including already finished tasks.

        Pass source_id (the task id) to read that notice even when older unacked
        notices still sit in the same target. Omit it to keep the oldest-first inbox.
        Run a persistent consumer that rearms this bounded wait; no task-status polling.
        Receipts/IDs remain stable until completion_ack after consumer processing.
        A tool response is client delivery, never proof of unsolicited assistant/chat wake-up.
        """
        try:
            return await bridge.completions.wait(
                identity(ctx), target, limit, wait_seconds, source_id
            )
        except BridgeError as exc:
            return {"error": {"code": exc.code, "message": str(exc)}}

    @server.tool(annotations=delivery)
    def completion_ack(notice_id: str, receipt: str, ctx: Context) -> dict[str, Any]:
        """Acknowledge own processed completion by stable ID and matching receipt.

        Repeating this exact acknowledgement is safe. Does not attest ChatGPT chat delivery.
        """
        return safe(lambda: bridge.completions.ack(identity(ctx), notice_id, receipt))

    @server.tool(annotations=write)
    async def message_release(message_id: str, token: str, ctx: Context) -> dict[str, Any]:
        """Release your exact waiting voice message with Daniel's later go-go-go token.

        The original recipient, content and deadline remain fixed; expired messages stay expired.
        """
        result = safe(
            lambda: bridge.messages.voice_policy.release(identity(ctx), message_id, token)
        )
        from kirabridge.grok_connector.conversation import message_for_conversation

        return await message_for_conversation(bridge, identity(ctx), result)

    @server.tool(annotations=write)
    async def message_send(
        message: MessageSend, ctx: Context, completion_target: str | None = None
    ) -> dict[str, Any]:
        """Send an addressed durable message; sender is your authenticated identity.

        Kira, Eve and terminal senders need no special approval marker.
        Normal capabilities and peer permissions still apply. Old buffers do not
        auto-release. Eve/Kira exchanges use eve-kira-shared.

        For dispatched agent work, completion_target routes final completion_receive notices
        to the requesting assistant's stable target, even on failure or without an auto reply.
        Kinds: question, answer, work, result, note. Reuse the idempotency_key only for the
        exact same message. Work/questions to CLI agents use their assigned visible terminal
        even with dispatch=false. One bounded visible attempt is observed before returning;
        busy/missing/changed targets fail without a waiting backlog or hidden fallback.
        For guidance to an already-working cooperating agent, use a NEW note with
        dispatch=false and request_reply=false on its agreed conversation_id.
        The recipient must poll message_receive and deduplicate IDs before applying/ACK;
        this inbox route does not wake or automatically steer the active session.
        Questions/work request one response
        by default. Answers/results never request another response. No shell interpolation.
        Returned answers stay in the sender's client inbox; they do not automatically
        start another background receiver. Grok app calls wait briefly and include
        conversation_return and reply_message. Acknowledge the reply only after processing it.
        """
        try:
            result = await bridge.message_receiver.send(
                identity(ctx), message, completion_target=completion_target
            )
        except BridgeError as exc:
            result = {"error": {"code": exc.code, "message": str(exc)}}
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
                "ON m.id=j.message_id WHERE m.recipient=? "
                "AND NOT EXISTS (SELECT 1 FROM queue_holds h "
                "WHERE h.queue_id='messages' AND h.item_id=m.id) GROUP BY j.state",
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
                "session_scope": "existing_visible_terminal"
                if config.visible_handoffs.enabled
                else "separate_managed_session",
                "visible_handoffs": config.visible_handoffs.model_dump(),
                "binding_runtime_status": "not_probed",
                "existing_session_attached": False,
                "attachment_meaning": "no_persistent_agent_protocol_attachment; "
                "exact_existing_UI_target_revalidated_on_each_action",
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
        """Send addressed team data; sender is authenticated, never supplied.

        Kira and Eve need no special approval marker; normal team permissions apply.
        Historical buffers never release automatically.
        Eve/Kira exchanges go into their private shared conversation, outside the team log.
        """
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

    @server.tool(annotations=read)
    def bridge_epoch(ctx: Context) -> dict[str, Any]:
        """Fresh passive schema epoch; explicit bridge_health retains full status."""
        from kirabridge.discovery import epoch

        def action():
            name = identity(ctx)
            bridge.security.principal(name, "bridge.health")
            return {
                "version": __version__,
                "dispatcher_active": bool(bridge.tasks.workers)
                and all(not worker.done() for worker in bridge.tasks.workers),
                "discovery": epoch(bridge, name),
            }

        return safe(action)

    @server._mcp_server.list_tools()
    async def current_tools():
        from kirabridge.discovery import epoch as discovery_epoch

        # Listing schemas is side-effect free: invalid/buffered calls must not
        # cause terminal probes merely because the SDK fetches its tool schemas.
        name = identity(server.get_context())
        epoch = discovery_epoch(bridge, name)
        metadata = {
            "version": epoch["version"],
            "instance_id": epoch["instance_id"],
            "revision": epoch["revision"],
            "principal": name,
            "platform_revision": epoch["platform_revision"],
        }
        from kirabridge.permissions import decision

        rows = {
            row["operation"].replace(".", "_"): row
            for row in bridge.macos.operation_catalog(lambda op: decision(config, name, op))
        }
        if "session_input" in rows:
            rows["session_enter"] = rows["session_input"]
        native_host = bridge.macos.host_platform == "darwin"
        return [
            tool.model_copy(update={"meta": {**(tool.meta or {}), "kirabridge": metadata}})
            for tool in await server.list_tools()
            if tool.name not in rows
            or tool.name in {"session_catalog", "session_read", "clipboard_info"}
            or not native_host
            or rows[tool.name]["eligible_for_submission"]
        ]

    from kirabridge.mcp_gateway.timing import instrument_server

    instrument_server(server._mcp_server, "daemon")
    return server
