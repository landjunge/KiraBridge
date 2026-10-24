"""Disk-backed contract fixture ONLY. This is not ThreadDesk product/import code."""

import hashlib
import json
import os
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError, UncertainExecution, digest
from kirabridge.file_transfer.models import PROTOCOL, Manifest


class DiskReceiver:
    identity = "a" * 64

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(exist_ok=True)
        self.offsets = []
        self.lose_ack_once = False
        self.bad_receipt = None

    def folder(self, operation):
        assert operation.startswith("kb_file_") and len(operation) == 72
        return self.root / operation

    async def capabilities(self):
        return {
            "protocol": PROTOCOL,
            "resumable": True,
            "durable_receipts": True,
            "max_chunk_bytes": 65536,
        }

    async def begin(self, operation, manifest):
        folder = self.folder(operation)
        folder.mkdir(exist_ok=True)
        metadata = folder / "manifest.json"
        if metadata.exists():
            assert json.loads(metadata.read_text()) == manifest.model_dump(mode="json")
        else:
            metadata.write_text(json.dumps(manifest.model_dump(mode="json")))
            (folder / "part").write_bytes(b"")
        return await self.status(operation)

    async def status(self, operation):
        folder = self.folder(operation)
        if not folder.exists():
            raise BridgeError("transfer_not_found", "No checkpoint")
        manifest = json.loads((folder / "manifest.json").read_text())
        path = folder / ("stored" if (folder / "stored").exists() else "part")
        data = path.read_bytes()
        return {
            "protocol": PROTOCOL,
            "operation_id": operation,
            "manifest_sha256": digest(manifest),
            "next_offset": len(data),
            "prefix_sha256": hashlib.sha256(data).hexdigest(),
        }

    async def chunk(self, operation, offset, data, sha256):
        path = self.folder(operation) / "part"
        assert path.stat().st_size == offset
        assert hashlib.sha256(data).hexdigest() == sha256
        with path.open("ab") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        self.offsets.append(offset)
        if self.lose_ack_once:
            self.lose_ack_once = False
            raise UncertainExecution("peer_unknown", "Fixture lost acknowledgement after writing")
        return {**await self.status(operation), "chunk_sha256": sha256}

    async def commit(self, operation):
        folder = self.folder(operation)
        manifest = Manifest.model_validate_json((folder / "manifest.json").read_text())
        if (folder / "part").exists():
            data = (folder / "part").read_bytes()
            assert (
                len(data) == manifest.size and hashlib.sha256(data).hexdigest() == manifest.sha256
            )
            os.replace(folder / "part", folder / "stored")
            fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        return {"protocol": PROTOCOL, "state": "commit_accepted"}

    async def receipt(self, operation):
        folder = self.folder(operation)
        manifest = Manifest.model_validate_json((folder / "manifest.json").read_text())
        # Independent read after commit, and usable by a newly created receiver instance.
        data = (folder / "stored").read_bytes()
        result = {
            "protocol": PROTOCOL,
            "operation_id": operation,
            "manifest_sha256": digest(manifest.model_dump(mode="json")),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "project_id": manifest.project_id,
            "folder": manifest.folder,
            "name": manifest.name,
            "artifact_id": "fixture-artifact",
            "storage_revision": "fixture-durable-1",
            "state": "stored",
            "durable": True,
        }
        if self.bad_receipt:
            result.update(self.bad_receipt)
        return result
