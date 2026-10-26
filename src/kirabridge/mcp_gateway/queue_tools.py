"""Owner-scoped queue tooling, separate from terminal and receiver implementations."""

from typing import Any

from mcp.server.fastmcp import Context

from kirabridge.bridge_core.models import TaskRequest
from kirabridge.queue_management.models import QueueControl


def register_queue_tools(server, queues, identity, task_request, safe, read, write):
    @server.tool(annotations=read)
    def queue_catalog(ctx: Context) -> dict[str, Any]:
        """All queues accessible to this identity, with exact-snapshot clear revisions.

        No message delivery, acknowledgement, terminal input or hidden execution occurs.
        Remote provider queues and separate adapter stores are explicitly outside this store.
        """
        return safe(lambda: queues.catalog(identity(ctx)))

    @server.tool(annotations=read)
    def queue_entries(
        queue_id: str, ctx: Context, after: int = 0, limit: int = 50, active_only: bool = True
    ) -> dict[str, Any]:
        """Paginate own summaries; queue_entry provides complete content/evidence.

        Continue while has_more, even on empty pages.

        Active delivery and execution state are distinct. Removing a delivery never
        proves a running/unknown command stopped; immutable history stays readable.
        """
        return safe(lambda: queues.entries(identity(ctx), queue_id, after, limit, active_only))

    @server.tool(annotations=read)
    def queue_entry(
        queue_id: str,
        item_id: str,
        ctx: Context,
        content_offset: int = 0,
        max_chars: int = 16384,
        expected_revision: str | None = None,
    ) -> dict[str, Any]:
        """Read full own entry as lossless JSON chunks with SHA-256 and revision.

        Concatenate detail_json_chunk in content-offset order; pin expected_revision
        after the first page. Continue while has_more_content; no silent truncation.
        Reading never acknowledges/delivers a message or sends terminal input.
        """
        return safe(
            lambda: queues.read_entry(
                identity(ctx), queue_id, item_id, content_offset, max_chars, expected_revision
            )
        )

    @server.tool(annotations=write)
    async def queue_control(
        request: QueueControl, task_id: str, idempotency_key: str, ctx: Context
    ) -> dict[str, Any]:
        """Queue exact cancel/clear/restore/retire/withdraw using existing rights and approvals.

        clear requires catalog snapshot revision; individual actions require entry revision.
        Running/unknown work is never falsely stopped. Retiring an uncertain handoff
        normally requires a fresh positively idle assigned target. With explicit
        acknowledge_execution_unknown=true, retire instead requires fresh complete native
        evidence that the persisted ORIGINAL window and both original PIDs are absent.
        Any existing/reused PID, ambiguous binding or observation error refuses retirement.
        This releases only the original reservation; execution remains unknown.
        No resend, input, signal or process kill.
        withdraw requires acknowledge_execution_unknown=true and an individual unknown
        task/message/handoff. It hides the active entry without ending execution or
        releasing handoff reservations; historical state/evidence remain unchanged.
        Restore only never-started held deliveries. History/audit remain intact.
        """
        return await task_request(
            TaskRequest(
                task_id=task_id,
                idempotency_key=idempotency_key,
                operation="queue.control",
                arguments=request.model_dump(),
            ),
            ctx,
        )

    @server.tool(annotations=write)
    async def queue_stop(
        task_id: str, stop_task_id: str, idempotency_key: str, ctx: Context
    ) -> dict[str, Any]:
        """Explicitly stop ONLY an owned managed process using existing process.terminate rights.

        This cannot kill a foreign/visible agent by PID. Fetch stop task and original
        task/process evidence: a stop request alone is not confirmed termination.
        Unknown visible handoffs require evidence reconciliation, not blind Ctrl-C.
        """
        return await task_request(
            TaskRequest(
                task_id=stop_task_id,
                idempotency_key=idempotency_key,
                operation="process.terminate",
                arguments={"task_id": task_id},
            ),
            ctx,
        )
