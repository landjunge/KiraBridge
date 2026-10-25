"""Real ThreadDesk stdio receiver, never the old disk-receiver contract fixture."""

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
from conftest import request

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import BridgeError


@pytest.fixture
def receiver(config, bridge, tmp_path):
    source = os.environ.get("KIRABRIDGE_TEST_THREADDESK_SOURCE")
    if not source:
        pytest.skip("Pinned real ThreadDesk source required")
    config.principals["local"].permission_level = "full"
    config.file_transfer.enabled = True
    config.file_transfer.export_roots = config.principals["local"].roots[:]
    settings = config.threaddesk
    settings.enabled = True
    settings.command = sys.executable
    settings.args = ["-m", "threaddesk.ui.mcp_stdio"]
    settings.workspace = str(tmp_path / "real-threaddesk")
    Path(settings.workspace).mkdir(mode=0o700)
    settings.source_root = source
    return bridge, config


async def task(bridge, operation, arguments, identifier):
    value = request(operation, arguments, task_id=identifier)
    bridge.prepare("local", value)
    return await bridge.tasks.wait("local", identifier, 20)


async def setup(receiver, filename="native.txt", data=b"native search sentinel"):
    bridge, config = receiver
    created = await task(
        bridge,
        "threaddesk.manage",
        {
            "action": "create",
            "operation_id": "native-project",
            "expected_revision": 0,
            "data": {"title": "Synthetic adapter acceptance"},
        },
        "create",
    )
    project = created["result"]["value"]["thread_id"]
    config.file_transfer.allowed_projects = [project]
    path = Path(config.file_transfer.export_roots[0]) / filename
    path.write_bytes(data)
    sid = bridge.file_sources.export(
        "local", "native", str(path), config.file_transfer.export_roots
    )
    prepared = await task(
        bridge,
        "files.prepare",
        {
            "source_id": sid,
            "project_id": project,
            "library_path": "/Original/" + filename,
            "folder": "Brainstorming/Topic",
            "source_version": "historical-v1",
            "expected_sha256": hashlib.sha256(data).hexdigest(),
        },
        "prepare",
    )
    assert prepared["state"] == "completed", prepared
    return prepared["result"]["id"], project, path


@pytest.mark.parametrize(
    "filename,data",
    [
        ("native.txt", b"native search sentinel"),
        ("native.png", (Path(__file__).parent / "fixtures/file-transfer/image.png").read_bytes()),
    ],
)
async def test_actual_receiver_text_binary_readback_index_receipt_restart(receiver, filename, data):
    bridge, config = receiver
    async with bridge:
        identifier, project, original = await setup(receiver, filename, data)
        result = await task(bridge, "files.transfer", {"transfer_id": identifier}, "send")
        assert result["state"] == "completed", result
        stored = result["result"]
        assert stored["import_successful"] and stored["receipt"]["durable"] is True
        assert stored["manifest"]["library_path"] == "/Original/" + filename
        assert stored["manifest"]["source_version"] == "historical-v1"
        rid = stored["receipt"]["artifact_id"]
        assert original.read_bytes() == data
        assert (
            Path(config.threaddesk.workspace)
            / "library-files/blobs"
            / hashlib.sha256(data).hexdigest()
        ).read_bytes() == data
        await bridge.threaddesk.close()
        await bridge.threaddesk.connect()
        for tool, args in [
            ("library_file_info", {"thread_id": project, "record_id": rid}),
            (
                "library_search",
                {
                    "thread_id": project,
                    "query": "sentinel" if filename.endswith("txt") else filename,
                },
            ),
        ]:
            raw = await bridge.threaddesk.pool.call("threaddesk", tool, args)
            ok, value = bridge.threaddesk.decode(raw, mutation=False)
            assert ok, value
            assert rid in json.dumps(value), value
        duplicate = await task(bridge, "files.transfer", {"transfer_id": identifier}, "again")
        assert duplicate["result"]["receipt"] == stored["receipt"]
        assert (
            len(list((Path(config.threaddesk.workspace) / "library-files/records").glob("*"))) == 1
        )


@pytest.mark.parametrize("lost_action", ["begin", "append", "commit"])
async def test_lost_write_read_status_once_no_replay_and_explicit_resume(receiver, lost_action):
    bridge, config = receiver
    actions = []
    async with bridge:
        identifier, _, _ = await setup(receiver, data=b"resume content " * 60000)
        call = bridge.threaddesk.pool.call
        lost = False

        async def lose_response(peer, tool, args, **kwargs):
            nonlocal lost
            response = await call(peer, tool, args, **kwargs)
            if tool == "library_receive":
                actions.append(args["action"])
                if args["action"] == lost_action and not lost:
                    lost = True
                    raise BridgeError("peer_unknown", "Simulated lost response after real write")
            return response

        bridge.threaddesk.pool.call = lose_response
        sent = await task(bridge, "files.transfer", {"transfer_id": identifier}, "lost")
        if lost_action == "commit":
            assert sent["state"] == "completed", sent  # Read-only receipt proves completion.
        else:
            assert sent["state"] == "unknown", sent
        assert actions.count(lost_action) == 1
    resumed = Bridge(config)
    try:
        async with resumed:
            final = await task(resumed, "files.transfer", {"transfer_id": identifier}, "resume")
            assert final["state"] == "completed", final
            assert final["result"]["import_successful"]
    finally:
        resumed.store.close()
    assert len(list((Path(config.threaddesk.workspace) / "library-files/records").glob("*"))) == 1


async def test_abort_is_scoped_terminal_and_does_not_delete_original(receiver):
    bridge, _ = receiver
    async with bridge:
        identifier, _, path = await setup(receiver)
        service = bridge.file_transfers
        from kirabridge.file_transfer.models import Manifest

        record = bridge.file_repository.get("local", identifier)
        await service.receiver.capabilities()
        await service.receiver.begin(
            record["operation_id"], Manifest.model_validate(record["manifest"])
        )
        for index in range(2):
            result = await task(bridge, "files.abort", {"transfer_id": identifier}, f"abort{index}")
            assert result["state"] == "completed", result
            assert result["result"]["state"] == "aborted"
        result = await task(bridge, "files.transfer", {"transfer_id": identifier}, "resume-aborted")
        assert result["state"] == "failed" and path.exists()


async def test_lost_abort_is_reconciled_once_and_revoked_project_cannot_abort(receiver):
    from kirabridge.file_transfer.models import Manifest

    bridge, config = receiver
    async with bridge:
        identifier, _, path = await setup(receiver)
        record = bridge.file_repository.get("local", identifier)
        remote = bridge.file_transfers.receiver
        await remote.capabilities()
        await remote.begin(record["operation_id"], Manifest.model_validate(record["manifest"]))
        projects = config.file_transfer.allowed_projects
        config.file_transfer.allowed_projects = []
        denied = await task(bridge, "files.abort", {"transfer_id": identifier}, "denied")
        assert denied["state"] == "failed"
        assert (await remote.status(record["operation_id"]))["state"] == "receiving"
        config.file_transfer.allowed_projects = projects
        original, calls = remote.abort, []

        async def lose(operation):
            calls.append(operation)
            await original(operation)
            raise BridgeError("peer_unknown", "Lost abort response after real abort")

        remote.abort = lose
        result = await task(bridge, "files.abort", {"transfer_id": identifier}, "lost-abort")
        assert result["state"] == "completed", result
        assert result["result"]["state"] == "aborted" and len(calls) == 1
        assert path.exists()


@pytest.mark.parametrize(
    "field,value", [("sha256", "0" * 64), ("size", True), ("thread_id", "wrong")]
)
async def test_native_receipt_mismatch_never_counts_as_import(receiver, field, value):
    bridge, _ = receiver
    async with bridge:
        identifier, _, _ = await setup(receiver)
        original = bridge.file_transfers.receiver.receipt

        async def corrupt(operation):
            state = await original(operation)
            state["receipt"][field] = value
            return state

        bridge.file_transfers.receiver.receipt = corrupt
        status_read = bridge.file_transfers.receiver.status

        async def corrupt_status(operation):
            state = await status_read(operation)
            if state.get("receipt"):
                state["receipt"][field] = value
            return state

        bridge.file_transfers.receiver.status = corrupt_status
        result = await task(bridge, "files.transfer", {"transfer_id": identifier}, "corrupt")
        assert result["state"] == "unknown", result
        record = bridge.file_repository.get("local", identifier)
        assert record["receipt"] is None and record["state"] == "paused"


async def test_scoped_batch_runner_originals_inventory_and_no_duplicate_resume(receiver, tmp_path):
    import asyncio
    import subprocess

    bridge, config = receiver
    async with bridge:
        _, project, original = await setup(receiver)
    export = Path(config.file_transfer.export_roots[0])
    image = Path(__file__).parent / "fixtures/file-transfer/image.png"
    (export / "native.png").write_bytes(image.read_bytes())
    inventory = tmp_path / "inventory.json"
    files = []
    for filename, mime in [("native.txt", "text/plain"), ("native.png", "image/png")]:
        body = (export / filename).read_bytes()
        files.append(
            {
                "source_ref": filename,
                "original_path": "/Project/" + filename,
                "export_relative": filename,
                "project": "Project",
                "thread_id": project,
                "mime_type": mime,
                "size": len(body),
                "source_version": "v1",
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
    files += [
        {"blocked_reason": "sensitive_inventory_only", "source_ref": "redacted"},
        {"source_ref": "missing", "project": "Project", "thread_id": project},
    ]
    inventory.write_text(json.dumps({"files": files}))
    script = Path(__file__).parent.parent / "scripts/import_library_exports.py"
    args = [
        sys.executable,
        str(script),
        "--inventory",
        str(inventory),
        "--exports",
        str(export),
        "--state",
        str(tmp_path / "batch-state"),
        "--workspace",
        config.threaddesk.workspace,
        "--receiver-python",
        sys.executable,
        "--receiver-source",
        config.threaddesk.source_root,
    ]
    for _ in range(2):
        result = await asyncio.to_thread(subprocess.run, args, capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr.decode()
        counts = json.loads(result.stdout)["durably_confirmed"]
        assert counts == 2
        report = json.loads((tmp_path / "batch-state/reconciliation.json").read_text())
        assert report["counts"] == {
            "expected": 4,
            "transferred": 2,
            "durably_confirmed": 2,
            "readback_confirmed": 2,
            "indexed": 2,
            "blocked": 2,
            "failed": 0,
            "unknown": 0,
            "not_processed": 0,
        }
    assert original.read_bytes() == b"native search sentinel"
    assert len(list((Path(config.threaddesk.workspace) / "library-files/records").glob("*"))) == 2
