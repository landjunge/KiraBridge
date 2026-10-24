"""Real bytes and storage receipts in isolated fixtures, not product ThreadDesk acceptance."""

import hashlib
import io
import stat
import zipfile

import httpx
import pytest
from conftest import request
from file_transfer_fixture import DiskReceiver

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import BridgeError
from kirabridge.file_transfer.integrity import logical_path, name
from kirabridge.file_transfer.models import Limits
from kirabridge.file_transfer.sources import PublicDownloadTransport, SelectedFile


@pytest.fixture
def files(bridge, config, tmp_path):
    policy = config.principals["local"]
    policy.capabilities += ["files.inspect"]
    policy.permission_level = "full"
    config.file_transfer.enabled = True
    config.file_transfer.allowed_projects = ["project-one", "one"]
    config.file_transfer.export_roots = policy.roots[:]
    receiver = DiskReceiver(tmp_path / "receiver")
    bridge.file_transfers.receiver = receiver
    return bridge, config, receiver


async def prepare(files, filename, data, identifier="prepare"):
    bridge, config, receiver = files
    path = __import__("pathlib").Path(config.principals["local"].roots[0]) / filename
    path.write_bytes(data)
    source_id = bridge.file_sources.export(
        "local", identifier, str(path), config.file_transfer.export_roots
    )
    value = request(
        "files.prepare",
        {
            "source_id": source_id,
            "project_id": "project-one",
            "folder": "folder/subfolder",
            "library_path": "/Library/folder/" + filename,
            "source_version": "source-v1",
            "expected_sha256": hashlib.sha256(data).hexdigest(),
        },
        task_id=identifier,
    )
    bridge.prepare("local", value)
    result = await bridge.tasks.wait("local", value.task_id, 10)
    return result, path


async def send(bridge, transfer_id, identifier="send"):
    value = request("files.transfer", {"transfer_id": transfer_id}, task_id=identifier)
    bridge.prepare("local", value)
    return await bridge.tasks.wait("local", value.task_id, 10)


@pytest.mark.parametrize(
    "filename,data",
    [
        ("note.txt", "Grüße\nOriginal bytes".encode()),
        ("note.md", b"# Markdown\nunchanged\n"),
        ("document.pdf", b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n"),
        ("image.png", b"\x89PNG\r\n\x1a\n" + bytes(range(256))),
        ("sound.wav", b"RIFF\x24\x00\x00\x00WAVEfmt " + bytes(range(40))),
        ("clip.mp4", b"\x00\x00\x00\x18ftypmp42" + bytes(range(80))),
        ("payload.bin", bytes(range(256)) * 6000),
    ],
)
async def test_bytes_manifest_folder_and_durable_receipt(files, filename, data):
    bridge, _, receiver = files
    async with bridge:
        prepared, path = await prepare(files, filename, data)
        assert prepared["state"] == "completed", prepared
        record = prepared["result"]
        assert record["state"] == "authorized" and not record["import_successful"]
        sent = await send(bridge, record["id"])
        assert sent["state"] == "completed", sent
        stored = sent["result"]
        assert stored["state"] == "stored" and stored["import_successful"]
        assert stored["receipt"]["sha256"] == hashlib.sha256(data).hexdigest()
        assert stored["manifest"]["library_path"] == "/Library/folder/" + filename
        assert stored["manifest"]["folder"] == "folder/subfolder"
        payload = next(receiver.root.glob("*/stored"))
        assert payload.read_bytes() == data and path.read_bytes() == data
        with pytest.raises(BridgeError):
            bridge.file_repository.get("other", record["id"])


def archive_bytes(name="folder/document.xml", body=b"<document>original</document>", mode=None):
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        entry = zipfile.ZipInfo(name)
        if mode is not None:
            entry.external_attr = mode << 16
        archive.writestr(entry, body)
    return target.getvalue()


@pytest.mark.parametrize("filename", ["office.docx", "sheet.xlsx", "slides.pptx", "archive.zip"])
async def test_zip_container_bytes_preserved_without_extraction(files, filename):
    bridge, _, receiver = files
    data = archive_bytes()
    async with bridge:
        prepared, original = await prepare(files, filename, data)
        assert prepared["state"] == "completed", prepared
        result = await send(bridge, prepared["result"]["id"])
        assert result["result"]["state"] == "stored"
        assert next(receiver.root.glob("*/stored")).read_bytes() == original.read_bytes() == data


async def test_lost_ack_resume_after_both_sides_restart_without_replaying_chunk(files, tmp_path):
    bridge, config, receiver = files
    data = bytes(range(256)) * 2000
    async with bridge:
        prepared, original = await prepare(files, "restart.bin", data)
        transfer_id = prepared["result"]["id"]
        receiver.lose_ack_once = True
        result = await send(bridge, transfer_id)
        assert result["state"] == "unknown"
        assert bridge.file_repository.get("local", transfer_id)["state"] == "paused"
        assert receiver.offsets == [0]
    resumed = Bridge(config)
    remote = DiskReceiver(receiver.root)
    resumed.file_transfers.receiver = remote
    async with resumed:
        result = await send(resumed, transfer_id, "resume-after-restart")
        assert result["state"] == "completed", result
        assert result["result"]["import_successful"]
        assert remote.offsets and remote.offsets[0] == 65536 and 0 not in remote.offsets
        assert original.read_bytes() == next(remote.root.glob("*/stored")).read_bytes() == data


@pytest.mark.parametrize(
    "bad",
    [
        {"durable": False},
        {"durable": "true"},
        {"sha256": "0" * 64},
        {"project_id": "another-project"},
        {"manifest_sha256": "0" * 64},
        {"size": True},
    ],
)
async def test_no_import_success_without_exact_durable_storage_receipt(files, bad):
    bridge, _, receiver = files
    receiver.bad_receipt = bad
    async with bridge:
        prepared, _ = await prepare(files, "unconfirmed.bin", b"unchanged\x00payload")
        result = await send(bridge, prepared["result"]["id"])
        assert result["state"] == "unknown", result
        record = bridge.file_repository.get("local", prepared["result"]["id"])
        assert record["state"] == "paused" and record["receipt"] is None


async def test_exact_duplicate_returns_existing_receipt_without_second_transfer(files):
    bridge, _, receiver = files
    async with bridge:
        first, _ = await prepare(files, "duplicate.bin", b"same file")
        await send(bridge, first["result"]["id"])
        offsets = receiver.offsets[:]
        second, _ = await prepare(files, "duplicate.bin", b"same file", "prepare-again")
        assert second["result"]["id"] == first["result"]["id"]
        sent = await send(bridge, second["result"]["id"], "send-again")
        assert sent["result"]["import_successful"] and receiver.offsets == offsets


@pytest.mark.parametrize(
    "entry",
    ["../escape.txt", "/absolute.txt", "C:/windows.txt", "folder/../../escape", "folder/.env"],
)
async def test_dangerous_archive_or_secret_paths_never_reach_receiver(files, entry):
    bridge, _, receiver = files
    async with bridge:
        prepared, _ = await prepare(files, "unsafe.zip", archive_bytes(entry))
        assert prepared["state"] == "failed"
        assert not list(receiver.root.iterdir())


async def test_archive_symlink_and_secret_payload_rejected(files):
    bridge, _, receiver = files
    async with bridge:
        link, _ = await prepare(
            files, "link.zip", archive_bytes("link", b"../elsewhere", stat.S_IFLNK | 0o777)
        )
        assert link["state"] == "failed"
        secret, _ = await prepare(
            files, "plain.txt", b"-----BEGIN PRIVATE KEY-----\nnot-for-transfer", "secret"
        )
        assert secret["state"] == "failed"
        assert not list(receiver.root.iterdir())


async def test_size_limit_and_changed_destination_do_not_send_bytes(files):
    bridge, config, receiver = files
    config.file_transfer.limits = Limits(max_file_bytes=100)
    async with bridge:
        oversized, _ = await prepare(files, "large.bin", b"x" * 101)
        assert oversized["state"] == "failed"
        prepared, _ = await prepare(files, "small.bin", b"original", "small")
        receiver.identity = "b" * 64
        denied = await send(bridge, prepared["result"]["id"])
        assert denied["state"] == "failed" and not receiver.offsets


@pytest.mark.parametrize("value", ["../x", "/abs", "a\\b", "a//b", "a/..", "C:/x"])
def test_logical_paths_reject_escape(value):
    with pytest.raises(BridgeError):
        logical_path(value)


@pytest.mark.parametrize(
    "value", [".env", "credentials.json", "private.pem", "id_ed25519", "x\x00y", ".."]
)
def test_secret_and_invalid_names_rejected(value):
    with pytest.raises(BridgeError):
        name(value)


async def test_download_transport_pins_public_ip_tls_and_drops_credentials():
    seen = []

    async def handler(request):
        seen.append(request)
        return httpx.Response(200, content=b"original bytes")

    async def resolver(host):
        assert host == "files.example.org"
        return {"8.8.8.8"}

    transport = PublicDownloadTransport(
        ["files.example.org"], inner=httpx.MockTransport(handler), resolver=resolver
    )
    request_value = httpx.Request(
        "GET",
        "https://files.example.org/object?signature=secret",
        headers={"Authorization": "MUST_NOT_FORWARD", "Cookie": "secret"},
    )
    response = await transport.handle_async_request(request_value)
    assert response.status_code == 200
    assert seen[0].url.host == "8.8.8.8"
    assert seen[0].headers["host"] == "files.example.org"
    assert seen[0].extensions["sni_hostname"] == "files.example.org"
    assert "authorization" not in seen[0].headers and "cookie" not in seen[0].headers


async def test_download_dns_rebinding_or_private_addresses_rejected():
    async def resolver(host):
        return {"8.8.8.8", "127.0.0.1"}

    transport = PublicDownloadTransport(["files.example.org"], resolver=resolver)
    try:
        with pytest.raises(BridgeError):
            await transport.handle_async_request(
                httpx.Request("GET", "https://files.example.org/file")
            )
    finally:
        await transport.aclose()


async def test_source_stream_bytes_and_expired_capability_do_not_leak_urls():
    secret_url = "https://files.example.org/file?signature=DO_NOT_LOG"

    async def response(request):
        return httpx.Response(200, stream=httpx.ByteStream(bytes(range(256)) * 100))

    source = SelectedFile(
        "bytes.bin",
        "application/octet-stream",
        "ref",
        secret_url,
        transport=httpx.MockTransport(response),
    )
    content = b"".join([block async for block in source.chunks(16384)])
    assert content == bytes(range(256)) * 100 and secret_url not in repr(source)


async def test_pause_and_resume_keeps_checkpoint_and_original(files):
    bridge, _, receiver = files
    data = bytes(range(256)) * 2000
    async with bridge:
        prepared, original = await prepare(files, "pause.bin", data)
        identifier = prepared["result"]["id"]
        chunk = receiver.chunk

        async def pausing(*args):
            result = await chunk(*args)
            bridge.file_repository.pause("local", identifier)
            return result

        receiver.chunk = pausing
        paused = await send(bridge, identifier)
        assert paused["state"] == "completed" and paused["result"]["state"] == "paused"
        assert not paused["result"]["import_successful"]
        assert paused["result"]["offset"] == 65536
        receiver.chunk = chunk
        resumed = await send(bridge, identifier, "resume-paused")
        assert resumed["result"]["import_successful"]
        assert receiver.offsets.count(0) == 1 and original.read_bytes() == data


async def test_mismatched_receiver_prefix_is_never_overwritten(files):
    bridge, _, receiver = files
    async with bridge:
        prepared, _ = await prepare(files, "prefix.bin", bytes(range(256)) * 2000)
        identifier = prepared["result"]["id"]
        receiver.lose_ack_once = True
        await send(bridge, identifier)
        partial = next(receiver.root.glob("*/part"))
        partial.write_bytes(b"x" * partial.stat().st_size)
        offsets = receiver.offsets[:]
        result = await send(bridge, identifier, "resume-bad-prefix")
        assert result["state"] == "unknown"  # receiver state exists, no successful import
        assert receiver.offsets == offsets and partial.read_bytes() == b"x" * 65536
        assert bridge.file_repository.get("local", identifier)["receipt"] is None


async def test_export_symlink_and_source_change_are_rejected(files, tmp_path):
    bridge, config, receiver = files
    root = __import__("pathlib").Path(config.principals["local"].roots[0])
    target = root / "real.bin"
    target.write_bytes(b"original bytes")
    link = root / "link.bin"
    link.symlink_to(target)
    async with bridge:
        source_id = bridge.file_sources.export("local", "linked", str(link), [str(root)])
        value = request(
            "files.prepare", {"source_id": source_id, "project_id": "one"}, task_id="linked"
        )
        bridge.prepare("local", value)
        rejected = await bridge.tasks.wait("local", "linked", 10)
        assert rejected["state"] == "failed"
        assert target.read_bytes() == b"original bytes" and not receiver.offsets
        target.write_bytes(bytes(range(256)) * 3000)
        source_id = bridge.file_sources.export("local", "changed", str(target), [str(root)])
        source = bridge.file_sources.get("local", source_id)
        original_chunks = source.chunks

        async def changing(chunk_bytes):
            first = True
            async for data in original_chunks(chunk_bytes):
                yield data
                if first:
                    first = False
                    target.write_bytes(b"externally changed fixture")

        source.chunks = changing
        value = request(
            "files.prepare", {"source_id": source_id, "project_id": "one"}, task_id="changed"
        )
        bridge.prepare("local", value)
        rejected = await bridge.tasks.wait("local", "changed", 10)
        assert rejected["state"] == "failed"
        assert rejected["result"]["error_code"] == "transfer_source_changed"
        assert not receiver.offsets


def test_transfer_package_dependency_direction():
    import ast
    from pathlib import Path

    package = Path(__file__).parents[1] / "src/kirabridge/file_transfer"
    forbidden = (
        "kirabridge.bridge_core.bridge",
        "kirabridge.operator",
        "kirabridge.terminal",
        "kirabridge.agent_manager",
        "kirabridge.mcp_gateway.server",
        "threaddesk.",
    )
    for module in package.glob("*.py"):
        for node in ast.walk(ast.parse(module.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(forbidden), (module.name, node.module)
            if isinstance(node, ast.Import):
                assert not any(item.name.startswith(forbidden) for item in node.names)


@pytest.mark.parametrize("lose_commit", [False, True])
async def test_actual_mcp_bytes_and_independent_disk_receipt_across_receiver_restart(
    files, tmp_path, lose_commit
):
    import asyncio
    import sys
    from pathlib import Path

    from kirabridge.file_transfer.threaddesk import ThreadDeskFileReceiver

    bridge, config, _ = files
    workspace = tmp_path / "receiver-workspace"
    workspace.mkdir(mode=0o700)
    settings = config.threaddesk
    settings.enabled = True
    settings.command = sys.executable
    settings.args = [str(Path(__file__).with_name("file_import_mcp_fixture.py"))]
    if lose_commit:
        settings.args.append("--lose-commit-once")
    settings.workspace = str(workspace)
    bridge.file_transfers.receiver = ThreadDeskFileReceiver(bridge.threaddesk)
    data = bytes(range(256)) * 2000
    async with bridge:
        prepared, original = await prepare(files, "through-mcp.bin", data)
        assert prepared["state"] == "completed", prepared
        transfer_id = prepared["result"]["id"]
        sent = await send(bridge, transfer_id)
        if lose_commit:
            assert sent["state"] == "unknown", sent
            # Only an explicit new resume request reconnects; no mutation replay.
            async with asyncio.timeout(5):
                while "threaddesk" in bridge.threaddesk.pool.sessions:
                    await asyncio.sleep(0.05)
            sent = await send(bridge, transfer_id, "resume-lost-commit")
        assert sent["state"] == "completed", sent
        assert sent["result"]["import_successful"]
        assert sent["result"]["receipt"]["sha256"] == hashlib.sha256(data).hexdigest()
        assert next((workspace / "fixture-files").glob("*/stored")).read_bytes() == data
        assert original.read_bytes() == data
        assert "--lose-commit-once" not in str(sent["result"])  # transport details not disclosed
