"""Historical receiver bindings; isolated disk bytes are not live ThreadDesk evidence."""

import asyncio
import base64
import hashlib
import sys
from types import SimpleNamespace

import pytest
from file_transfer_fixture import DiskReceiver

from kirabridge.bridge_core.models import BridgeError, digest
from kirabridge.file_transfer.models import Manifest, TransferInput
from kirabridge.file_transfer.threaddesk import TOOLS, ThreadDeskFileReceiver

NATIVE = {"library_receive", "library_receive_status", "library_search", "library_file_info"}


class Pool:
    def __init__(self, disk):
        self.disk, self.names, self.calls = disk, set(TOOLS), []

    async def list_tools(self, peer):
        return [SimpleNamespace(name=name) for name in self.names]

    async def call(self, peer, tool, args):
        self.calls.append((tool, args))
        assert tool in TOOLS, "Legacy checkpoint must never invoke native operations"
        if tool == "file_import_capabilities":
            return True, await self.disk.capabilities()
        operation = args["operation_id"]
        try:
            if tool == "file_import_begin":
                value = await self.disk.begin(operation, Manifest.model_validate(args["manifest"]))
            elif tool == "file_import_chunk":
                value = await self.disk.chunk(
                    operation, args["offset"], base64.b64decode(args["data_base64"]), args["sha256"]
                )
            else:
                action = tool.removeprefix("file_import_")
                value = await getattr(self.disk, action)(operation)
        except BridgeError as exc:
            if exc.code == "transfer_not_found":
                return False, {"error": {"code": "not_found"}}
            raise
        return True, value


@pytest.fixture
def historical(bridge, config, tmp_path):
    config.file_transfer.enabled = True
    config.file_transfer.allowed_projects = ["project-one"]
    pool = Pool(DiskReceiver(tmp_path / "disk"))
    settings = SimpleNamespace(
        command=sys.executable,
        args=["-m", "isolated.fixture"],
        workspace=str(tmp_path / "workspace"),
        storage="json",
        source_root=None,
    )

    async def connect():
        pass

    manager = SimpleNamespace(settings=settings, pool=pool, lock=asyncio.Lock(), connect=connect)
    manager.decode = lambda result, **kwargs: result
    adapter = ThreadDeskFileReceiver(manager)
    bridge.file_transfers.receiver = adapter
    data = b"Unchanged authorized export.\n" * 4000
    snapshot = tmp_path / "snapshot"
    snapshot.write_bytes(data)
    legacy = digest([settings.command, settings.args, settings.workspace, settings.storage])
    manifest = Manifest(
        name="original.txt",
        mime_type="text/plain",
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        project_id="project-one",
        folder="ideas/topic",
        library_path="/Originals/original.txt",
        source_kind="authorized_export",
        source_ref="historical-export",
        source_version="version-one",
        destination_ref=legacy,
    )
    record = bridge.file_repository.add("local", manifest, snapshot)
    return bridge, adapter, manager, pool, manifest, record, data


async def observed(evidence):
    pass


@pytest.mark.parametrize("families", ["legacy", "both"])
async def test_legacy_four_field_checkpoint_resumes_original_bytes_and_identity(
    historical, families
):
    bridge, adapter, manager, pool, manifest, record, data = historical
    if families == "both":
        pool.names |= NATIVE
    operation = record["operation_id"]
    await pool.disk.begin(operation, manifest)
    prefix = data[:4096]
    await pool.disk.chunk(operation, 0, prefix, hashlib.sha256(prefix).hexdigest())
    bridge.file_repository.update("local", record["id"], "paused", offset=4096)
    audit = [tuple(row) for row in bridge.store.db.execute("SELECT * FROM audit ORDER BY seq")]
    prior = dict(bridge.store.db.execute("SELECT * FROM kb_file_transfers").fetchone())
    result = await bridge.file_transfers.transfer(
        {"principal": "local"}, TransferInput(transfer_id=record["id"]), observed
    )
    assert result["import_successful"] is True
    after = dict(bridge.store.db.execute("SELECT * FROM kb_file_transfers").fetchone())
    for key in ("id", "manifest", "manifest_hash", "operation_id", "snapshot"):
        assert after[key] == prior[key]
    assert pool.disk.folder(operation).joinpath("stored").read_bytes() == data
    assert pool.disk.offsets[1] == 4096
    assert all(tool in TOOLS for tool, _ in pool.calls)
    assert all(args.get("operation_id", operation) == operation for _, args in pool.calls)
    assert adapter.native is False  # Per-transfer binding cannot mutate the shared adapter.
    assert [tuple(row) for row in bridge.store.db.execute("SELECT * FROM audit ORDER BY seq")][
        : len(audit)
    ] == audit


async def test_legacy_refuses_native_only_receiver_without_begin_or_fallback(historical):
    bridge, _, _, pool, _, record, _ = historical
    pool.names = NATIVE.copy()
    with pytest.raises(BridgeError) as error:
        await bridge.file_transfers.transfer(
            {"principal": "local"}, TransferInput(transfer_id=record["id"]), observed
        )
    assert error.value.code == "transfer_protocol_unavailable"
    assert not pool.calls and not list(pool.disk.root.iterdir())


@pytest.mark.parametrize("field", ["command", "args", "workspace", "storage", "source_root"])
async def test_bound_legacy_view_refuses_settings_changed_while_connecting(historical, field):
    _, adapter, manager, pool, manifest, _, _ = historical
    bound = adapter.bind_destination(manifest.destination_ref)
    assert bound is not adapter and bound.identity == manifest.destination_ref
    adapter.native = True  # An unrelated discovery on the shared receiver is not inherited.
    pool.names |= NATIVE

    async def changed_connect():
        setattr(manager.settings, field, ["changed"] if field == "args" else "changed")

    manager.connect = changed_connect
    with pytest.raises(BridgeError) as error:
        await bound.capabilities()
    assert error.value.code == "transfer_destination_changed"
    assert not pool.calls and adapter.native is True and bound.native is False


async def test_legacy_four_field_id_cannot_bind_a_new_source_root(historical):
    bridge, _, manager, pool, _, record, _ = historical
    manager.settings.source_root = "/explicit/new/source"
    before = dict(bridge.store.db.execute("SELECT * FROM kb_file_transfers").fetchone())
    with pytest.raises(BridgeError) as error:
        await bridge.file_transfers.transfer(
            {"principal": "local"}, TransferInput(transfer_id=record["id"]), observed
        )
    assert error.value.code == "transfer_destination_changed"
    assert dict(bridge.store.db.execute("SELECT * FROM kb_file_transfers").fetchone()) == before
    assert not pool.calls


async def test_lost_legacy_chunk_ack_reconciles_with_the_same_bound_view_and_id(historical):
    from kirabridge.bridge_core.models import UncertainExecution

    bridge, adapter, _, pool, manifest, record, data = historical
    pool.names |= NATIVE
    pool.disk.lose_ack_once = True
    with pytest.raises(UncertainExecution):
        await bridge.file_transfers.transfer(
            {"principal": "local"}, TransferInput(transfer_id=record["id"]), observed
        )
    stored = bridge.file_repository.get("local", record["id"])
    assert stored["state"] == "paused" and stored["offset"] == 65536
    assert stored["manifest"] == record["manifest"]
    assert stored["manifest_hash"] == record["manifest_hash"]
    assert stored["operation_id"] == record["operation_id"]
    assert [tool for tool, _ in pool.calls][-1] == "file_import_status"
    assert pool.disk.folder(record["operation_id"]).joinpath("part").read_bytes() == data[:65536]
    assert not adapter.native and manifest.destination_ref == record["manifest"]["destination_ref"]


async def test_legacy_abort_never_switches_to_native_or_overwrites_checkpoint(historical):
    bridge, _, _, pool, manifest, record, _ = historical
    pool.names |= NATIVE
    await pool.disk.begin(record["operation_id"], manifest)
    before = dict(bridge.store.db.execute("SELECT * FROM kb_file_transfers").fetchone())
    with pytest.raises(BridgeError) as error:
        await bridge.file_transfers.abort(
            {"principal": "local"}, TransferInput(transfer_id=record["id"]), observed
        )
    assert error.value.code == "transfer_protocol_unavailable"
    assert [tool for tool, _ in pool.calls] == ["file_import_capabilities", "file_import_status"]
    assert dict(bridge.store.db.execute("SELECT * FROM kb_file_transfers").fetchone()) == before


def test_current_five_field_identity_remains_exact_and_binding_local(historical):
    _, adapter, manager, _, _, _, _ = historical
    settings = manager.settings
    expected = digest(
        [
            settings.command,
            settings.args,
            settings.workspace,
            settings.storage,
            settings.source_root,
        ]
    )
    assert adapter.identity == expected
    bound = adapter.bind_destination(expected)
    assert bound.identity == expected and bound is not adapter
    bound.native = True
    assert adapter.native is False


async def test_legacy_stored_receipt_is_reused_without_rehash_or_remote_calls(historical):
    from kirabridge.file_transfer.protocol import durable_receipt

    bridge, _, _, pool, manifest, record, data = historical
    operation = record["operation_id"]
    await pool.disk.begin(operation, manifest)
    await pool.disk.chunk(operation, 0, data, hashlib.sha256(data).hexdigest())
    await pool.disk.commit(operation)
    receipt = durable_receipt(await pool.disk.receipt(operation), operation, manifest)
    bridge.file_repository.update(
        "local", record["id"], "stored", offset=len(data), receipt=receipt
    )
    before = dict(bridge.store.db.execute("SELECT * FROM kb_file_transfers").fetchone())
    audit = [tuple(row) for row in bridge.store.db.execute("SELECT * FROM audit ORDER BY seq")]
    result = await bridge.file_transfers.transfer(
        {"principal": "local"}, TransferInput(transfer_id=record["id"]), observed
    )
    assert result["receipt"] == receipt and result["import_successful"]
    assert dict(bridge.store.db.execute("SELECT * FROM kb_file_transfers").fetchone()) == before
    assert [
        tuple(row) for row in bridge.store.db.execute("SELECT * FROM audit ORDER BY seq")
    ] == audit
    assert not pool.calls
