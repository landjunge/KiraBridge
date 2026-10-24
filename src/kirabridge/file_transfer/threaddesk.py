"""Versioned file sink over the existing operator-authorized ThreadDesk MCP owner."""

import base64

from kirabridge.bridge_core.models import BridgeError, digest
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
    def __init__(self, manager):
        self.manager = manager

    @property
    def identity(self):
        settings = self.manager.settings
        return digest([settings.command, settings.args, settings.workspace, settings.storage])

    async def call(self, tool, arguments):
        manager = self.manager
        async with manager.lock:
            await manager.connect()
            names = {item.name for item in await manager.pool.list_tools("threaddesk")}
            if not TOOLS.issubset(names):
                raise BridgeError(
                    "transfer_protocol_unavailable",
                    "ThreadDesk lacks the file-byte import contract",
                )
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
        return await self.call("file_import_capabilities", {})

    async def begin(self, operation_id, manifest):
        return await self.call(
            "file_import_begin",
            {"operation_id": operation_id, "manifest": manifest.model_dump(mode="json")},
        )

    async def status(self, operation_id):
        return await self.call("file_import_status", {"operation_id": operation_id})

    async def chunk(self, operation_id, offset, data, sha256):
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
        return await self.call("file_import_commit", {"operation_id": operation_id})

    async def receipt(self, operation_id):
        return await self.call("file_import_receipt", {"operation_id": operation_id})
