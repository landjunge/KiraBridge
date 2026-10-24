"""Snapshot, hash, stream and reconcile files through injected narrow partners."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import uuid
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.file_transfer.integrity import (
    SecretScan,
    name,
    open_snapshot,
    sha256_file,
    validate_archive,
)
from kirabridge.file_transfer.models import PROTOCOL, Manifest
from kirabridge.file_transfer.protocol import checkpoint, durable_receipt


class FileTransferService:
    def __init__(self, root, settings, sources, authorization, repository, receiver):
        self.root, self.settings, self.sources = Path(root), settings, sources
        self.authorization, self.repository, self.receiver = authorization, repository, receiver
        self.prepare_lock = asyncio.Lock()
        self.transfer_locks = {}

    async def prepare(self, task, args, running):
        principal = task["principal"]
        self.authorization.prepare(principal, args)
        source = self.sources.get(principal, args.source_id)
        self.authorization.source(principal, source)
        filename = name(source.name)
        self.sources.state(principal, args.source_id, "authorized")
        async with self.prepare_lock:
            from kirabridge.bridge_core.config import private_directory

            private_directory(self.root)
            used, copies = 0, 0
            for existing in self.root.iterdir():
                if existing.is_symlink() or not existing.is_dir():
                    raise BridgeError(
                        "transfer_staging_unsafe", "Unexpected staged entry; preserved"
                    )
                copies += 1
                if copies >= self.settings.limits.max_staged_files:
                    raise BridgeError("transfer_storage_limit", "Staged file-count limit reached")
                for content in existing.iterdir():
                    if content.is_symlink() or not content.is_file():
                        raise BridgeError(
                            "transfer_staging_unsafe", "Unexpected staged content; preserved"
                        )
                    used += content.stat().st_size
            if used >= self.settings.limits.max_staged_bytes:
                raise BridgeError("transfer_storage_limit", "Staging quota exceeded")
            folder = self.root / uuid.uuid4().hex
            folder.mkdir(mode=0o700)
            snapshot = folder / filename
            checksum, scan, total = hashlib.sha256(), SecretScan(), 0
            try:
                await running({"phase": "authorized", "source_id": args.source_id})
                fd = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "wb") as target:
                    async for data in source.chunks(self.settings.limits.chunk_bytes):
                        total += len(data)
                        if (
                            total > self.settings.limits.max_file_bytes
                            or used + total > self.settings.limits.max_staged_bytes
                        ):
                            raise BridgeError(
                                "transfer_size_limit", "File/staging byte limit exceeded"
                            )
                        scan.update(data)
                        checksum.update(data)
                        target.write(data)
                    target.flush()
                    os.fsync(target.fileno())
                for directory in (folder, self.root):
                    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                sha256 = checksum.hexdigest()
                if args.expected_sha256 is not None and args.expected_sha256 != sha256:
                    raise BridgeError("transfer_integrity", "Selected source SHA-256 mismatch")
                await asyncio.to_thread(validate_archive, snapshot, self.settings.limits)
                manifest = Manifest(
                    name=filename,
                    mime_type=source.mime_type,
                    size=total,
                    sha256=sha256,
                    project_id=args.project_id,
                    folder=args.folder,
                    library_path=args.library_path,
                    source_kind=source.kind,
                    source_ref=source.reference,
                    source_version=args.source_version,
                    destination_ref=self.receiver.identity,
                )
                record = self.repository.add(principal, manifest, snapshot)
                if record["snapshot"] != str(snapshot):
                    shutil.rmtree(folder)
                self.sources.state(principal, args.source_id, "prepared")
                return self.repository.public(record)
            except BridgeError as exc:
                self.sources.state(principal, args.source_id, "failed")
                shutil.rmtree(folder)
                return {
                    "success": False,
                    "state": "failed",
                    "error_code": exc.code,
                    "import_successful": False,
                    "bytes_sent_to_receiver": 0,
                }
            except BaseException:
                shutil.rmtree(folder)
                raise

    async def transfer(self, task, args, running):
        principal, identifier = task["principal"], args.transfer_id
        self.authorization.check(principal, "files.transfer")
        record = self.repository.get(principal, identifier)
        if record["manifest"]["destination_ref"] != self.receiver.identity:
            raise BridgeError(
                "transfer_destination_changed",
                "Prepared destination differs from current configuration",
            )
        if record["manifest"]["project_id"] not in self.settings.allowed_projects:
            raise BridgeError("transfer_project_denied", "Project authorization was revoked")
        if record["state"] == "stored":
            await running({"phase": "stored_receipt_reused", "transfer_id": identifier})
            return self.repository.public(record)
        if record["state"] == "aborted":
            raise BridgeError("transfer_closed", "Aborted transfers cannot be resumed")
        # Bound lock count by active invocations, not untrusted historical identifiers.
        if identifier in self.transfer_locks:
            raise BridgeError("transfer_busy", "Transfer already running; read its existing status")
        lock = asyncio.Lock()
        self.transfer_locks[identifier] = lock
        try:
            async with lock:
                self.repository.reset_pause(principal, identifier)
                return await self._send(task, record, running)
        except asyncio.CancelledError:
            self.repository.update(
                principal, identifier, "paused", error_code="transfer_interrupted"
            )
            raise
        except BridgeError as exc:
            state = (
                "paused"
                if exc.code
                in {
                    "peer_unknown",
                    "peer_disconnected",
                    "transfer_storage_unconfirmed",
                    "transfer_receipt_mismatch",
                }
                else "failed"
            )
            self.repository.update(principal, identifier, state, error_code=exc.code)
            if state == "paused":
                # Reconcile ONCE by read after a lost response. Never replay the write,
                # even if this read proves it did not arrive. Explicit resume is required.
                try:
                    status = await self.receiver.status(record["operation_id"])
                    manifest = Manifest.model_validate(record["manifest"])
                    offset = checkpoint(status, record["operation_id"], manifest)
                    if status.get("state") == "committed":
                        receipt = durable_receipt(status, record["operation_id"], manifest)
                        return self.repository.public(
                            self.repository.update(
                                principal, identifier, "stored", offset=offset, receipt=receipt
                            )
                        )
                    self.repository.update(
                        principal, identifier, "paused", offset=offset, error_code=exc.code
                    )
                except BridgeError:
                    pass
                raise UncertainExecution(
                    exc.code, "Transfer outcome unconfirmed; resume by status reconciliation"
                ) from None
            raise
        finally:
            self.transfer_locks.pop(identifier, None)

    async def _send(self, task, record, running):
        principal, identifier = task["principal"], record["id"]
        manifest = Manifest.model_validate(record["manifest"])
        if manifest.destination_ref != self.receiver.identity:
            raise BridgeError(
                "transfer_destination_changed",
                "Destination configuration changed; explicit new preparation required",
            )
        path, operation_id = Path(record["snapshot"]), record["operation_id"]
        if await asyncio.to_thread(sha256_file, path) != manifest.sha256:
            raise BridgeError("transfer_integrity", "Staged snapshot changed; no bytes sent")
        capabilities = await self.receiver.capabilities()
        if (
            capabilities.get("protocol") != PROTOCOL
            or capabilities.get("resumable") is not True
            or capabilities.get("durable_receipts") is not True
            or type(capabilities.get("max_chunk_bytes")) is not int
            or not 16384 <= capabilities["max_chunk_bytes"] <= 1024 * 1024
        ):
            raise BridgeError(
                "transfer_protocol_mismatch", "Receiver lacks required resume/storage guarantees"
            )
        block_size = min(self.settings.limits.chunk_bytes, capabilities["max_chunk_bytes"])
        if manifest.size > capabilities.get("max_file_bytes", self.settings.limits.max_file_bytes):
            raise BridgeError("transfer_size_limit", "Receiver file limit exceeded")
        await running({"phase": "running", "transfer_id": identifier, "bytes_total": manifest.size})
        try:
            state = await self.receiver.status(operation_id)
        except BridgeError as exc:
            if exc.code != "transfer_not_found":
                raise
            state = await self.receiver.begin(operation_id, manifest)
        offset = checkpoint(state, operation_id, manifest)
        if state.get("state") == "committed":
            receipt = durable_receipt(
                await self.receiver.receipt(operation_id), operation_id, manifest
            )
            return self.repository.public(
                self.repository.update(
                    principal, identifier, "stored", offset=offset, receipt=receipt
                )
            )
        with open_snapshot(path) as source:
            prefix_hash = hashlib.sha256()
            remaining = offset
            while remaining:
                previous = source.read(min(block_size, remaining))
                if not previous:
                    raise BridgeError("transfer_integrity", "Staged prefix is incomplete")
                prefix_hash.update(previous)
                remaining -= len(previous)
            native = state.get("receiver_contract") == "threaddesk.library.receive.v1"
            if not native and state["prefix_sha256"] != prefix_hash.hexdigest():
                raise BridgeError(
                    "transfer_integrity", "Receiver prefix differs; no resume or overwrite"
                )
            self.repository.update(principal, identifier, "running", offset=offset)
            while data := source.read(block_size):
                if self.repository.get(principal, identifier)["pause_requested"]:
                    return self.repository.public(
                        self.repository.update(
                            principal,
                            identifier,
                            "paused",
                            offset=offset,
                            error_code="requested_pause",
                        )
                    )
                chunk_hash = hashlib.sha256(data).hexdigest()
                prefix_hash.update(data)
                ack = await self.receiver.chunk(operation_id, offset, data, chunk_hash)
                next_offset = checkpoint(ack, operation_id, manifest)
                if (
                    next_offset != offset + len(data)
                    or not native
                    and (
                        ack.get("chunk_sha256") != chunk_hash
                        or ack["prefix_sha256"] != prefix_hash.hexdigest()
                    )
                ):
                    raise BridgeError(
                        "transfer_receipt_mismatch", "Chunk acknowledgement differs from sent bytes"
                    )
                offset = next_offset
                self.repository.update(principal, identifier, "running", offset=offset)
        if offset != manifest.size or await asyncio.to_thread(sha256_file, path) != manifest.sha256:
            raise BridgeError("transfer_integrity", "Source changed before commit")
        self.repository.update(principal, identifier, "transferred", offset=offset)
        await self.receiver.commit(operation_id)
        # A second authenticated call reads the durable storage receipt. A chunk
        # acknowledgement, reference or commit response alone never counts as import.
        receipt = durable_receipt(await self.receiver.receipt(operation_id), operation_id, manifest)
        record = self.repository.update(
            principal, identifier, "stored", offset=offset, receipt=receipt
        )
        return self.repository.public(record)

    async def abort(self, task, args, running):
        principal, identifier = task["principal"], args.transfer_id
        self.authorization.check(principal, "files.transfer")
        record = self.repository.get(principal, identifier)
        manifest = Manifest.model_validate(record["manifest"])
        if (
            manifest.destination_ref != self.receiver.identity
            or manifest.project_id not in self.settings.allowed_projects
        ):
            raise BridgeError("transfer_destination_changed", "Transfer scope is no longer granted")
        if identifier in self.transfer_locks:
            raise BridgeError("transfer_busy", "Pause the running transfer before aborting")
        if record["state"] == "stored":
            raise BridgeError("transfer_already_stored", "Stored files cannot be aborted")
        self.transfer_locks[identifier] = asyncio.Lock()
        try:
            await self.receiver.capabilities()
            await running({"phase": "aborting", "transfer_id": identifier})
            # Even a lost begin must first be reconciled. Never create a new ID here.
            status = await self.receiver.status(record["operation_id"])
            if status.get("state") == "committed":
                receipt = durable_receipt(status, record["operation_id"], manifest)
                return self.repository.public(
                    self.repository.update(
                        principal, identifier, "stored", offset=manifest.size, receipt=receipt
                    )
                )
            if status.get("state") != "aborted":
                checkpoint(status, record["operation_id"], manifest)
                await self.receiver.abort(record["operation_id"])
                status = await self.receiver.status(record["operation_id"])
            checkpoint(status, record["operation_id"], manifest, allow_aborted=True)
            if (
                status.get("state") != "aborted"
                or status.get("transfer_id") != record["operation_id"]
                or status.get("manifest")
                != {
                    "filename": manifest.name,
                    "thread_id": manifest.project_id,
                    "size": manifest.size,
                    "sha256": manifest.sha256,
                }
            ):
                raise UncertainExecution("transfer_storage_unconfirmed", "Abort unconfirmed")
            return self.repository.public(
                self.repository.update(
                    principal, identifier, "aborted", offset=status["next_offset"]
                )
            )
        except BridgeError as exc:
            if exc.code in {"peer_unknown", "peer_disconnected", "transfer_storage_unconfirmed"}:
                self.repository.update(principal, identifier, "paused", error_code=exc.code)
                # The same terminal status can be confirmed without repeating abort.
                try:
                    status = await self.receiver.status(record["operation_id"])
                    checkpoint(status, record["operation_id"], manifest, allow_aborted=True)
                    if (
                        status.get("state") == "aborted"
                        and status.get("transfer_id") == record["operation_id"]
                        and status.get("manifest")
                        == {
                            "filename": manifest.name,
                            "thread_id": manifest.project_id,
                            "size": manifest.size,
                            "sha256": manifest.sha256,
                        }
                    ):
                        return self.repository.public(
                            self.repository.update(
                                principal, identifier, "aborted", offset=status["next_offset"]
                            )
                        )
                except BridgeError:
                    pass
                raise UncertainExecution(
                    exc.code, "Abort outcome unconfirmed; read same ID"
                ) from None
            raise
        finally:
            self.transfer_locks.pop(identifier, None)
