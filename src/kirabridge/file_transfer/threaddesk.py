"""Versioned file sink over the existing operator-authorized ThreadDesk MCP owner."""

import base64
import json

from kirabridge.bridge_core.models import BridgeError, UncertainExecution, digest
from kirabridge.file_transfer.models import PROTOCOL

TOOLS = frozenset(
    {
        "file_import_capabilities",
        "file_import_begin",
        "file_import_status",
        "file_import_chunk",
        "file_import_commit",
        "file_import_receipt",
    }
)


class ThreadDeskFileReceiver:
    def __init__(self, manager, *, destination_ref=None, legacy=False):
        self.manager = manager
        self._destination_ref, self._legacy = destination_ref, legacy
        self.native = False
        self.availability = "not_probed"

    @property
    def identity(self):
        settings = self.manager.settings
        fields = [settings.command, settings.args, settings.workspace, settings.storage]
        if self._legacy:
            if settings.source_root is not None:
                raise BridgeError(
                    "transfer_destination_changed", "Legacy source is no longer bound"
                )
        else:
            fields.append(settings.source_root)
        observed = digest(fields)
        if self._destination_ref is not None and observed != self._destination_ref:
            raise BridgeError("transfer_destination_changed", "Bound destination settings changed")
        return observed

    def bind_destination(self, destination_ref):
        """Keep historical manifests immutable; each operation owns its protocol view."""
        if self._destination_ref is not None:
            if self.identity != destination_ref:
                raise BridgeError("transfer_destination_changed", "Prepared destination changed")
            return self
        if destination_ref == self.identity:
            return type(self)(self.manager, destination_ref=destination_ref)
        settings = self.manager.settings
        legacy = digest([settings.command, settings.args, settings.workspace, settings.storage])
        if settings.source_root is None and destination_ref == legacy:
            return type(self)(self.manager, destination_ref=destination_ref, legacy=True)
        raise BridgeError("transfer_destination_changed", "Prepared destination changed")

    async def native_call(self, action, operation_id, **fields):
        if self._legacy:
            raise BridgeError(
                "transfer_protocol_unavailable", "Legacy checkpoint requires file_import"
            )
        _ = self.identity  # Revalidate the pinned view before any asynchronous receiver access.
        # No write replay here, including after a timeout. Resume starts with status.
        manager = self.manager
        async with manager.lock:
            await manager.connect()
            _ = self.identity
            result = await manager.pool.call(
                "threaddesk",
                "library_receive_status" if action == "status" else "library_receive",
                {
                    "transfer_id": operation_id,
                    **({"action": action} if action != "status" else {}),
                    **fields,
                },
            )
            try:
                ok, value = manager.decode(result, mutation=False)
            except BridgeError:
                if action != "status":
                    raise UncertainExecution(
                        "transfer_storage_unconfirmed", "Write unconfirmed"
                    ) from None
                raise
            if not ok or not isinstance(value, dict):
                if result.isError:
                    raw = result.structuredContent or json.loads(
                        "\n".join(item.text for item in result.content if item.type == "text")
                    )
                    code = raw.get("code")
                    if code in {
                        "validation_error",
                        "transfer_missing",
                        "transfer_conflict",
                        "transfer_closed",
                        "offset_conflict",
                        "chunk_conflict",
                        "size_mismatch",
                        "transfer_incomplete",
                        "checksum_mismatch",
                        "receive_quota",
                        "unsafe_store",
                        "secret_content",
                        "secret_name",
                        "unsupported_format",
                        "integrity",
                        "not_found",
                    }:
                        raise BridgeError(
                            "transfer_receiver_" + code, "Receiver refused the operation"
                        )
                raise BridgeError("transfer_receiver_rejected", "Receiver refused the operation")
            if value.get("transfer_id") != operation_id or type(value.get("found")) is not bool:
                raise UncertainExecution("transfer_storage_unconfirmed", "Invalid receiver status")
            if not value["found"]:
                if action != "status":
                    raise UncertainExecution("transfer_storage_unconfirmed", "Write unconfirmed")
                raise BridgeError("transfer_not_found", "Receiver has no transfer checkpoint")
            return {
                **value,
                "protocol": PROTOCOL,
                "operation_id": operation_id,
                "receiver_contract": "threaddesk.library.receive.v1",
            }

    async def call(self, tool, arguments):
        _ = self.identity
        if self._legacy and tool not in TOOLS:
            raise BridgeError(
                "transfer_protocol_unavailable", "Legacy checkpoint requires file_import"
            )
        manager = self.manager
        async with manager.lock:
            await manager.connect()
            names = {item.name for item in await manager.pool.list_tools("threaddesk")}
            if not TOOLS.issubset(names):
                raise BridgeError(
                    "transfer_protocol_unavailable",
                    "ThreadDesk lacks the file-byte import contract",
                )
            _ = self.identity  # connect/list_tools may have yielded to a configuration change.
            result = await manager.pool.call("threaddesk", tool, arguments)
            ok, value = manager.decode(result, mutation=False)
            if not ok:
                if value.get("error", {}).get("code") == "not_found":
                    raise BridgeError("transfer_not_found", "Receiver has no operation checkpoint")
                raise BridgeError(
                    "transfer_receiver_rejected", "Receiver rejected the file operation"
                )
            if not isinstance(value, dict) or value.get("protocol") != PROTOCOL:
                raise BridgeError(
                    "transfer_protocol_mismatch", "Receiver returned an incompatible protocol"
                )
            return value

    async def capabilities(self):
        _ = self.identity
        if self._legacy:
            # Never rediscover native tools for an original file_import checkpoint.
            return await self.call("file_import_capabilities", {})
        async with self.manager.lock:
            await self.manager.connect()
            names = {item.name for item in await self.manager.pool.list_tools("threaddesk")}
            _ = self.identity
            self.native = {
                "library_receive",
                "library_receive_status",
                "library_search",
                "library_file_info",
            }.issubset(names)
        if self.native:
            try:
                await self.native_call("status", "kb_probe_" + self.identity)
            except BridgeError as exc:
                if exc.code != "transfer_not_found":
                    self.availability = "unavailable"
                    raise
            self.availability = "available"
            return {
                "protocol": PROTOCOL,
                "resumable": True,
                "durable_receipts": True,
                "max_chunk_bytes": 262144,
                "max_file_bytes": 268435456,
                "receiver_contract": "threaddesk.library.receive.v1",
            }
        return await self.call("file_import_capabilities", {})

    async def begin(self, operation_id, manifest):
        if self.native:
            return await self.native_call(
                "begin",
                operation_id,
                filename=manifest.name,
                thread_id=manifest.project_id,
                size=manifest.size,
                sha256=manifest.sha256,
            )
        return await self.call(
            "file_import_begin",
            {"operation_id": operation_id, "manifest": manifest.model_dump(mode="json")},
        )

    async def status(self, operation_id):
        if self.native:
            return await self.native_call("status", operation_id)
        return await self.call("file_import_status", {"operation_id": operation_id})

    async def chunk(self, operation_id, offset, data, sha256):
        if self.native:
            return await self.native_call(
                "append",
                operation_id,
                offset=offset,
                data_base64=base64.b64encode(data).decode("ascii"),
            )
        return await self.call(
            "file_import_chunk",
            {
                "operation_id": operation_id,
                "offset": offset,
                "data_base64": base64.b64encode(data).decode("ascii"),
                "sha256": sha256,
            },
        )

    async def commit(self, operation_id):
        if self.native:
            return await self.native_call("commit", operation_id)
        return await self.call("file_import_commit", {"operation_id": operation_id})

    async def receipt(self, operation_id):
        if self.native:
            return await self.native_call("status", operation_id)
        return await self.call("file_import_receipt", {"operation_id": operation_id})

    async def abort(self, operation_id):
        if not self.native:
            raise BridgeError("transfer_protocol_unavailable", "Legacy receiver cannot abort")
        return await self.native_call("abort", operation_id)
