import base64
import binascii
import hashlib
import json
import os
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import request, submit
from test_mcp import http_bridge as http_bridge

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import BridgeError
from kirabridge.filesystem_manager import PathScope
from kirabridge.image_manager import (
    MAX_IMAGE_BYTES,
    SIGNATURE,
    ImageManager,
    image_task_result,
    validate_png,
)
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.proxy import DaemonConnection
from kirabridge.readiness import ReadinessInput, readiness

FIXTURE = Path(__file__).parent / "fixtures/images/own-rgb-32x24.png"


def chunk(kind, payload):
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
    )


def png(width=1, height=1, rows=b"\0\x11\x22\x33", compressed=None, tail=b""):
    return (
        SIGNATURE
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows) if compressed is None else compressed)
        + chunk(b"IEND", b"")
        + tail
    )


@pytest.mark.parametrize(
    "data,code",
    [
        (b"not a PNG", "image_invalid"),
        (FIXTURE.read_bytes()[:-1], "image_invalid"),
        (FIXTURE.read_bytes()[:-4] + b"oops", "image_invalid"),
        (png(width=2049), "image_limit"),
        (png(rows=b"\5\x11\x22\x33"), "image_invalid"),
        (png(rows=b"\0\x11\x22"), "image_invalid"),
        (png(rows=b"\0" * 4000000), "image_invalid"),
        (png(compressed=zlib.compress(b"\0\x11\x22\x33")[:-1]), "image_invalid"),
        (png(compressed=zlib.compress(b"\0\x11\x22\x33") + b"trailing"), "image_invalid"),
        (png(tail=b"extra"), "image_invalid"),
        (b"x" * (MAX_IMAGE_BYTES + 1), "image_limit"),
        (
            png()[:-12] + chunk(b"tEXt", b"not forwarded") + chunk(b"IEND", b""),
            "image_invalid",
        ),
        (
            png()[:33] + chunk(b"IDAT", b"") * 512 + png()[33:],
            "image_limit",
        ),
    ],
)
def test_png_rejects_invalid_actual_data_and_resource_overruns(data, code):
    with pytest.raises(BridgeError) as exc:
        validate_png(data)
    assert exc.value.code == code


def test_png_accepts_bounded_rgb_rgba_and_fixed_metadata():
    assert validate_png(FIXTURE.read_bytes()) == (32, 24)
    rgb = png()
    assert validate_png(rgb[:33] + chunk(b"sRGB", b"\0") + rgb[33:]) == (1, 1)
    rgba = (
        SIGNATURE
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\0\x11\x22\x33\xff"))
        + chunk(b"IEND", b"")
    )
    assert validate_png(rgba) == (1, 1)


def test_descriptor_read_denies_outside_symlinks_fifo_and_private_state(config, tmp_path):
    root = Path(config.principals["local"].roots[0])
    private = root / "private-state"
    private.mkdir()
    image = root / "allowed.png"
    image.write_bytes(FIXTURE.read_bytes())
    (private / "secret.png").write_bytes(FIXTURE.read_bytes())
    alias = root / "alias.png"
    alias.symlink_to(image)
    fifo = root / "fifo.png"
    os.mkfifo(fifo)
    directory_alias = root / "directory-alias"
    directory_alias.symlink_to(root, target_is_directory=True)
    scope = PathScope([str(root)], excluded=[str(private)])
    manager = ImageManager()
    assert (
        manager.read(scope, str(image))["content_sha256"]
        == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    )
    for path in [
        tmp_path / "foreign.png",
        private / "secret.png",
        alias,
        fifo,
        directory_alias / "allowed.png",
    ]:
        with pytest.raises(BridgeError):
            manager.read(scope, str(path))


async def test_read_only_root_image_capability_and_restart_snapshot(config):
    root = Path(config.principals["local"].roots[0])
    image = root / "own.png"
    image.write_bytes(FIXTURE.read_bytes())
    policy = config.principals["local"]
    policy.roots, policy.read_roots = [], [str(root)]
    policy.capabilities = ["file.image", "task.read", "bridge.health"]
    policy.approval_mode = "automatic"
    value = request("file.image", {"path": str(image)}, task_id="snapshot")
    async with Bridge(config) as bridge:
        checks = readiness(bridge, "local", ReadinessInput(image_paths=[str(image)]))
        assert checks["image_path_checks"][0]["ok"]
        assert checks["requested_prerequisites_ready"]
        bridge.prepare("local", value)
        completed = await bridge.tasks.wait("local", value.task_id)
        assert completed["state"] == "completed"
        encoded = completed["result"]["image_data"]
        assert base64.b64decode(encoded) == FIXTURE.read_bytes()
        image.unlink()
        audits = json.dumps([dict(row) for row in bridge.store.db.execute("SELECT * FROM audit")])
        events = json.dumps(bridge.events("local", value.task_id))
        assert encoded not in audits + events
        assert "image_data" not in audits + events
    async with Bridge(config) as restarted:
        task = restarted.task("local", value.task_id)
        response = image_task_result(task)
        assert response.content[1].data == encoded
        assert "image_data" not in response.structuredContent["result"]
        assert restarted.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
        assert (
            sum(e["state"] == "running" for e in restarted.events("local", value.task_id)["events"])
            == 1
        )
        policy.capabilities.remove("file.image")
        with pytest.raises(BridgeError) as exc:
            restarted.prepare("local", request("file.image", {"path": str(image)}, task_id="deny"))
        assert exc.value.code == "forbidden"


def test_only_completed_image_tasks_get_image_and_corrupt_snapshot_is_denied():
    for operation, state in [
        ("file.read", "completed"),
        ("file.image", "unknown"),
        ("file.image", "failed"),
        ("file.image", "running"),
    ]:
        task = {"operation": operation, "state": state, "result": {"image_data": "bad"}}
        assert image_task_result(task) is task
    with pytest.raises(BridgeError):
        image_task_result(
            {
                "operation": "file.image",
                "state": "completed",
                "result": {
                    "image_data": base64.b64encode(FIXTURE.read_bytes()).decode(),
                    "content_sha256": "0" * 64,
                },
            }
        )


def test_whole_tool_response_limit_and_no_unbounded_stored_image(config):
    root = Path(config.principals["local"].roots[0])
    image = root / "own.png"
    image.write_bytes(FIXTURE.read_bytes())
    result = ImageManager().read(PathScope([str(root)]), str(image))
    task = {
        "operation": "file.image",
        "state": "completed",
        "result": result,
        "unexpected_metadata": "x" * 1048576,
    }
    with pytest.raises(BridgeError) as exc:
        image_task_result(task)
    assert exc.value.code == "image_limit"
    result["image_data"] = "x" * (2 * MAX_IMAGE_BYTES)
    with pytest.raises(BridgeError) as exc:
        image_task_result(task)
    assert exc.value.code == "image_invalid"


def test_image_change_during_read_is_not_verified(config, monkeypatch):
    root = Path(config.principals["local"].roots[0])
    image = root / "changing.png"
    image.write_bytes(FIXTURE.read_bytes())
    original = os.fstat
    calls = 0

    def changing(fd):
        nonlocal calls
        calls += 1
        value = original(fd)
        if calls == 2:
            return SimpleNamespace(
                st_size=value.st_size,
                st_mtime_ns=value.st_mtime_ns + 1,
                st_ctime_ns=value.st_ctime_ns,
            )
        return value

    monkeypatch.setattr(os, "fstat", changing)
    with pytest.raises(BridgeError) as exc:
        ImageManager().read(PathScope([str(root)]), str(image))
    assert exc.value.code == "image_changed"


async def test_actual_dispatch_capability_private_state_and_invalid_png(bridge, config):
    root = Path(config.principals["local"].roots[0])
    bad = root / "bad.png"
    bad.write_bytes(b"bad PNG")
    config.principals["local"].read_roots.append(str(config.state_path.parent))
    async with bridge:
        private = request(
            "file.image", {"path": str(config.state_path / "bridge.sqlite3")}, task_id="private"
        )
        submit(bridge, private)
        failed = await bridge.tasks.wait("local", private.task_id)
        assert failed["state"] == "failed" and failed["error"]["code"] == "path_denied"
        invalid = request("file.image", {"path": str(bad)}, task_id="invalid")
        submit(bridge, invalid)
        unknown = await bridge.tasks.wait("local", invalid.task_id)
        assert unknown["state"] == "unknown" and unknown["error"]["code"] == "image_invalid"
        assert unknown["result"] is None
        assert isinstance(image_task_result(bridge.task("local", invalid.task_id)), dict)
        config.principals["local"].capabilities.remove("file.image")
        checks = readiness(bridge, "local", ReadinessInput(image_paths=[str(bad)]))
        assert checks["image_path_checks"][0]["code"] == "forbidden"
        with pytest.raises(BridgeError) as exc:
            bridge.prepare("local", request("file.image", {"path": str(bad)}, task_id="no-cap"))
        assert exc.value.code == "forbidden"


async def test_real_mcp_imagecontent_ownership_normal_json_and_reconnect(http_bridge, config):
    bridge, endpoint = http_bridge
    root = Path(config.principals["local"].roots[0])
    image = root / "design.png"
    image.write_bytes(FIXTURE.read_bytes())
    value = request("file.image", {"path": str(image)}, task_id="mcp-image")
    submit(bridge, value)
    assert (await bridge.tasks.wait("local", value.task_id))["state"] == "completed"
    peer = Peer("local", url=endpoint, token="local-test-" + "a" * 40)
    async with MCPClientPool() as clients:
        await clients.connect(peer)
        await clients.connect(Peer("other", url=endpoint, token="other-test-" + "b" * 40))
        result = await clients.call("local", "task_get", {"task_id": value.task_id})
        assert [c.type for c in result.content] == ["text", "image"]
        assert json.loads(result.content[0].text) == result.structuredContent
        assert result.content[1].mimeType == "image/png"
        assert base64.b64decode(result.content[1].data) == FIXTURE.read_bytes()
        assert "image_data" not in result.structuredContent["result"]
        denied = await clients.call("other", "task_get", {"task_id": value.task_id})
        assert denied.structuredContent["error"]["code"] == "not_found"
        assert all(c.type == "text" for c in denied.content)
        image.unlink()
        await clients.disconnect("local")
        await clients.connect(peer)
        proxy = DaemonConnection(clients, peer)
        reread = await proxy.call_tool("task_get", {"task_id": value.task_id})
        assert reread.content[1].data == result.content[1].data
        plain = request(arguments={"path": str(root)}, task_id="plain-list")
        submit(bridge, plain)
        await bridge.tasks.wait("local", plain.task_id)
        normal = await clients.call("local", "task_get", {"task_id": plain.task_id})
        assert normal.structuredContent == bridge.task("local", plain.task_id)
        assert all(c.type == "text" for c in normal.content)
        assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 2
