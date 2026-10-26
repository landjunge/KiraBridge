import base64
from pathlib import Path

import pytest
from conftest import request, submit
from pydantic import ValidationError

from kirabridge.bridge_core.models import BridgeError
from kirabridge.read_query import ReadQuery, read_query


def test_direct_and_legacy_range_results_match_with_no_task_on_direct_route(bridge, config):
    path = Path(config.principals["local"].roots[0]) / "bytes"
    path.write_bytes(b"begin\xf0\x9f\xa7\xa0\xffend")
    query = ReadQuery(
        operation="file.read", path=str(path), max_bytes=4, offset=5, encoding="base64"
    )
    direct = read_query(bridge, "local", query)
    from kirabridge.filesystem_manager import PathScope

    legacy = bridge.filesystem.read(
        PathScope(config.principals["local"].roots), str(path), 4, offset=5, encoding="base64"
    )
    assert {k: direct[k] for k in legacy} == legacy
    assert base64.b64decode(direct["data_base64"]) == "🧠".encode()
    assert bridge.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    with path.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(BridgeError) as exc:
        read_query(
            bridge, "local", query.model_copy(update={"expected_identity": direct["identity"]})
        )
    assert exc.value.code == "file_changed"


async def test_legacy_dispatched_schema_forwards_additive_range_fields(bridge, config):
    path = Path(config.principals["local"].roots[0]) / "source"
    path.write_bytes(b"prefix\x00\xffsuffix")
    value = request(
        "file.read",
        {"path": str(path), "offset": 6, "max_bytes": 2, "encoding": "base64"},
        task_id="range-read",
    )
    submit(bridge, value)
    async with bridge:
        task = await bridge.tasks.wait("local", value.task_id, 5)
    assert task["state"] == "completed", task
    assert base64.b64decode(task["result"]["data_base64"]) == b"\x00\xff"
    assert task["result"]["next_offset"] == 8 and not task["result"]["eof"]


def test_direct_ranges_preserve_capability_and_state_exclusions(bridge, config):
    state_file = config.state_path / "secret"
    state_file.write_bytes(b"private")
    with pytest.raises(BridgeError):
        read_query(
            bridge,
            "local",
            ReadQuery(operation="file.read", path=str(state_file), encoding="base64"),
        )
    path = Path(config.principals["local"].roots[0]) / "allowed"
    path.write_bytes(b"bytes")
    config.principals["local"].capabilities.remove("file.read")
    with pytest.raises(BridgeError):
        read_query(
            bridge, "local", ReadQuery(operation="file.read", path=str(path), encoding="base64")
        )


@pytest.mark.parametrize(
    "operation,args",
    [
        ("file.list", {"path": "/tmp", "encoding": "base64"}),
        ("terminal.output", {"task_id": "task", "expected_identity": "a" * 64}),
        ("session.read", {"pane_id": "%1", "expected_pid": 2, "encoding": "base64"}),
    ],
)
def test_file_only_selectors_never_leak_to_other_tools(operation, args):
    with pytest.raises(ValidationError):
        ReadQuery(operation=operation, **args)


@pytest.mark.parametrize("route", ["direct", "dispatched"])
async def test_both_api_routes_reconstruct_large_original_bytes_with_pinned_pages(
    bridge, config, route
):
    import hashlib

    data = ("split🧠ä漢字\n".encode() + bytes(range(256))) * 4100
    assert len(data) > 1048576  # The cap is per page, never per entire file.
    path = Path(config.principals["local"].roots[0]) / "large-original"
    path.write_bytes(data)
    received, offset, identity = bytearray(), 0, None
    async with bridge:
        for index in range(100):
            args = {
                "path": str(path),
                "offset": offset,
                "max_bytes": 65536,
                "encoding": "base64",
                "expected_identity": identity,
            }
            if route == "direct":
                page = read_query(bridge, "local", ReadQuery(operation="file.read", **args))
            else:
                value = request("file.read", args, task_id=f"range-page-{index}")
                submit(bridge, value)
                task = await bridge.tasks.wait("local", value.task_id, 5)
                assert task["state"] == "completed", task
                page = task["result"]
            raw = base64.b64decode(page["data_base64"], validate=True)
            assert hashlib.sha256(raw).hexdigest() == page["content_sha256"]
            received.extend(raw)
            identity, offset = page["identity"], page["next_offset"]
            if page["eof"]:
                break
        else:
            pytest.fail("Page cursor failed to reach EOF")
    assert received == data and path.read_bytes() == data
    assert hashlib.sha256(received).digest() == hashlib.sha256(data).digest()
