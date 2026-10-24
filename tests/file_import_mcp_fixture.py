"""Isolated MCP contract fixture; not ThreadDesk application/import implementation."""

import base64
import os
import sys
from pathlib import Path

from file_transfer_fixture import DiskReceiver
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

from kirabridge.bridge_core.models import BridgeError
from kirabridge.file_transfer.models import Manifest

root = Path(os.environ["THREADDESK_HOME"])
receiver = DiskReceiver(root / "fixture-files")
server = FastMCP("FileImportContractFixture")
server._mcp_server.version = "contract-fixture-v1"


@server.tool()
def list_threads():
    return {"threads": []}


@server.tool()
def get_thread(id: str):
    return {"id": id}


@server.tool()
def thread_manage(operation_id: str):
    return {"operation_id": operation_id}


@server.tool()
async def file_import_capabilities():
    return await receiver.capabilities()


@server.tool()
async def file_import_begin(operation_id: str, manifest: dict):
    return await receiver.begin(operation_id, Manifest.model_validate(manifest))


@server.tool()
async def file_import_status(operation_id: str):
    try:
        return await receiver.status(operation_id)
    except BridgeError as exc:
        return CallToolResult(
            isError=True,
            content=[TextContent(type="text", text="Checkpoint absent")],
            structuredContent={"code": exc.code.removeprefix("transfer_")},
        )


@server.tool()
async def file_import_chunk(operation_id: str, offset: int, data_base64: str, sha256: str):
    data = base64.b64decode(data_base64, validate=True)
    if len(data) > 65536:
        raise ValueError("Fixture chunk limit")
    return await receiver.chunk(operation_id, offset, data, sha256)


@server.tool()
async def file_import_commit(operation_id: str):
    result = await receiver.commit(operation_id)
    marker = root / "lost-commit-once"
    if "--lose-commit-once" in sys.argv and not marker.exists():
        marker.write_text("committed before process exit")
        os._exit(71)  # Deliberately lose the response after durable storage in this fixture.
    return result


@server.tool()
async def file_import_receipt(operation_id: str):
    return await receiver.receipt(operation_id)


if __name__ == "__main__":
    server.run(transport="stdio")
