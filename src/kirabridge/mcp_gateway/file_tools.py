"""MCP file-tool registration; knows only the file-transfer owner and narrow gateway ports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context
from pydantic import ValidationError

from kirabridge.bridge_core.models import BridgeError, TaskRequest
from kirabridge.file_transfer.models import OpenAIFile


def register_file_tools(server, service, identity, task_request, authorize, safe, read, write):
    @server.tool(annotations=write, meta={"openai/fileParams": ["file"]})
    async def file_transfer_prepare(
        file: OpenAIFile,
        project_id: str,
        task_id: str,
        idempotency_key: str,
        ctx: Context,
        folder: str = "",
        library_path: str | None = None,
        source_version: str | None = None,
        expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Snapshot a selected ChatGPT file's real bytes; no Library-wide browsing.

        Host-provided file params carry a temporary download capability. The source URL
        stays ephemeral and never enters tasks/audit. Existing grants still apply. A
        completed preparation is NOT an import: call file_transfer_start and require
        state=stored plus a validated durable ThreadDesk receipt.
        """
        try:
            name = identity(ctx)
            service.authorization.check(name, "files.prepare")
            source_id = service.sources.selected(name, idempotency_key, file, service.settings)
            return await task_request(
                TaskRequest(
                    task_id=task_id,
                    idempotency_key=idempotency_key,
                    operation="files.prepare",
                    arguments={
                        "source_id": source_id,
                        "project_id": project_id,
                        "folder": folder,
                        "library_path": library_path,
                        "source_version": source_version,
                        "expected_sha256": expected_sha256,
                    },
                ),
                ctx,
            )
        except (BridgeError, ValidationError) as exc:
            return {
                "error": {
                    "code": getattr(exc, "code", "invalid_arguments"),
                    "message": "File preparation unavailable; check source settings and grants",
                }
            }

    @server.tool(annotations=write)
    async def file_transfer_export(
        path: str,
        project_id: str,
        task_id: str,
        idempotency_key: str,
        ctx: Context,
        folder: str = "",
        library_path: str | None = None,
        source_version: str | None = None,
        expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Snapshot a local export under BOTH operator export roots and file.read grants.

        No Google Drive authorization or Library-wide access is inferred. Originals are
        never changed. This prepares bytes only; it does not claim ThreadDesk storage.
        """
        try:
            name = identity(ctx)
            policy_scope, export_roots = service.authorization.export_roots(name)
            policy_scope.split(path)
            if any(
                part in {".ssh", ".aws", ".gnupg", ".config", ".git"} for part in Path(path).parts
            ):
                raise BridgeError(
                    "transfer_source_denied",
                    "Credential/configuration directories are not export sources",
                )
            source_id = service.sources.export(name, idempotency_key, path, export_roots)
            return await task_request(
                TaskRequest(
                    task_id=task_id,
                    idempotency_key=idempotency_key,
                    operation="files.prepare",
                    arguments={
                        "source_id": source_id,
                        "project_id": project_id,
                        "folder": folder,
                        "library_path": library_path,
                        "source_version": source_version,
                        "expected_sha256": expected_sha256,
                    },
                ),
                ctx,
            )
        except BridgeError as exc:
            return {"error": {"code": exc.code, "message": "Export source is not authorized"}}

    @server.tool(annotations=write)
    async def file_transfer_start(
        transfer_id: str,
        task_id: str,
        idempotency_key: str,
        ctx: Context,
    ) -> dict[str, Any]:
        """Send prepared bytes to ThreadDesk, or explicitly resume after reconciling its checkpoint.

        A new resume request needs a new task ID/key and the SAME transfer_id. Unknown
        writes are never blindly replayed. Only result.state=stored with a matching,
        independently fetched durable receipt counts as successful import.
        """
        return await task_request(
            TaskRequest(
                task_id=task_id,
                idempotency_key=idempotency_key,
                operation="files.transfer",
                arguments={"transfer_id": transfer_id},
            ),
            ctx,
        )

    @server.tool(annotations=write)
    async def file_transfer_pause(
        transfer_id: str,
        task_id: str,
        idempotency_key: str,
        ctx: Context,
    ) -> dict[str, Any]:
        """Request a checkpoint pause; originals and acknowledged receiver bytes remain intact."""
        return await task_request(
            TaskRequest(
                task_id=task_id,
                idempotency_key=idempotency_key,
                operation="files.pause",
                arguments={"transfer_id": transfer_id},
            ),
            ctx,
        )

    def transfer_read_permission(name, operation):
        service.authorization.check(name, "files.inspect")
        if authorize(name, operation)["approval_required"]:
            raise BridgeError(
                "approval_required", "Submit this status query as an exact approved task"
            )

    @server.tool(annotations=read)
    def file_transfer_inventory(ctx: Context, after: str = "", limit: int = 100) -> dict[str, Any]:
        """This identity's prepared/active/stored transfers; not a census of the ChatGPT Library."""

        def action():
            from kirabridge.file_transfer.models import InventoryInput

            name = identity(ctx)
            transfer_read_permission(name, "files.inventory")
            args = InventoryInput(after=after, limit=limit)
            return {
                "transfers": [
                    service.repository.public(row)
                    for row in service.repository.list(name, args.after, args.limit)
                ],
                "scope": "explicitly selected/prepared sources; no historical Library enumeration",
                "sources": service.sources.inventory(name),
            }

        return safe(action)

    @server.tool(annotations=read)
    def file_transfer_status(transfer_id: str, ctx: Context) -> dict[str, Any]:
        """Read own safe byte progress, checkpoint errors and the last validated storage receipt."""

        def action():
            name = identity(ctx)
            transfer_read_permission(name, "files.status")
            return service.repository.public(service.repository.get(name, transfer_id))

        return safe(action)
