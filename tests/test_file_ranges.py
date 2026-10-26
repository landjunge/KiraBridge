import base64
import hashlib
import os

import pytest

from kirabridge.bridge_core.models import BridgeError, ReadInput
from kirabridge.filesystem_manager import FilesystemManager, PathScope


def test_byte_pages_reconstruct_utf8_and_binary_without_total_file_cap(tmp_path):
    data = ("ä🧠漢字\n".encode() + bytes(range(256))) * 20
    path = tmp_path / "source.bin"
    path.write_bytes(data)
    manager, scope = FilesystemManager(), PathScope([str(tmp_path)])
    received, offset, identity = bytearray(), 0, None
    while True:
        page = manager.read(scope, str(path), 31, offset=offset, expected_identity=identity)
        raw = base64.b64decode(page["data_base64"], validate=True)
        assert len(raw) == page["bytes"] <= 31
        assert hashlib.sha256(raw).hexdigest() == page["content_sha256"]
        assert page["offset"] == offset and page["next_offset"] == offset + len(raw)
        identity = page["identity"]
        received.extend(raw)
        if page["eof"]:
            assert not page["truncated"]
            break
        assert page["truncated"] and page["next_offset"] > offset
        offset = page["next_offset"]
    assert received == data and path.read_bytes() == data


@pytest.mark.parametrize("change", ["append", "truncate", "replace"])
def test_changed_identity_refuses_next_page(tmp_path, change):
    path = tmp_path / "source"
    path.write_bytes(b"abcdef")
    fs, scope = FilesystemManager(), PathScope([str(tmp_path)])
    identity = fs.read(scope, str(path), 2)["identity"]
    if change == "append":
        with path.open("ab") as stream:
            stream.write(b"new")
    elif change == "truncate":
        path.write_bytes(b"a")
    else:
        replacement = tmp_path / "replacement"
        replacement.write_bytes(b"abcdef")
        replacement.replace(path)
    with pytest.raises(BridgeError) as exc:
        fs.read(scope, str(path), 2, offset=2, expected_identity=identity)
    assert exc.value.code == "file_changed"


def test_text_boundaries_binary_tail_and_eof_are_explicit(tmp_path):
    path = tmp_path / "unicode"
    path.write_bytes("a🧠z".encode())
    fs, scope = FilesystemManager(), PathScope([str(tmp_path)])
    split = fs.read(scope, str(path), 2)
    assert isinstance(split["text"], str) and split["text_status"] == "invalid_or_partial_utf8"
    assert not split["text_lossless"]
    assert base64.b64decode(split["data_base64"]) == b"a\xf0"
    assert fs.read(scope, str(path), 4, offset=1)["text"] == "🧠"
    tail = fs.read(scope, str(path), 1, tail=True, encoding="base64")
    assert tail["offset"] == 5 and tail["eof"] and tail["has_before"]
    assert tail["text"] == "" and tail["text_status"] == "binary"
    assert not tail["text_lossless"]
    assert base64.b64decode(tail["data_base64"]) == b"z"
    end = fs.read(scope, str(path), 3, offset=100)
    assert end["bytes"] == 0 and end["eof"] and end["next_offset"] == 100
    path.write_bytes(b"")
    assert fs.read(scope, str(path), 3)["eof"]


@pytest.mark.parametrize("kind", ["symlink", "fifo", "directory", "excluded", "outside"])
def test_unsafe_sources_remain_denied(tmp_path, kind):
    root = tmp_path / "root"
    root.mkdir()
    path = root / "source"
    scope = PathScope([str(root)])
    if kind == "symlink":
        target = root / "target"
        target.write_bytes(b"secret")
        path.symlink_to(target)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    elif kind == "excluded":
        path.write_bytes(b"secret")
        scope = PathScope([str(root)], excluded=[str(path)])
    else:
        path = tmp_path / "outside"
        path.write_bytes(b"secret")
    with pytest.raises(BridgeError):
        FilesystemManager().read(scope, str(path), 10)


def test_mutation_during_range_read_returns_no_mixed_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "source"
    path.write_bytes(b"original")
    original = os.pread

    def mutate(fd, size, offset):
        result = original(fd, size, offset)
        path.write_bytes(b"modified-and-longer")
        return result

    monkeypatch.setattr(os, "pread", mutate)
    with pytest.raises(BridgeError) as exc:
        FilesystemManager().read(PathScope([str(tmp_path)]), str(path), 3)
    assert exc.value.code == "file_changed"


@pytest.mark.parametrize(
    "args",
    [
        {"offset": -1},
        {"offset": True},
        {"tail": True, "offset": 1},
        {"encoding": "latin1"},
        {"expected_identity": "bad"},
    ],
)
def test_legacy_range_schema_rejects_invalid_selectors(args):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ReadInput(path="/tmp/example", **args)


def test_path_replacement_during_read_cannot_return_detached_original_page(tmp_path, monkeypatch):
    path, replacement = tmp_path / "source", tmp_path / "replacement"
    path.write_bytes(b"original")
    replacement.write_bytes(b"original")
    original = os.pread

    def replace(fd, size, offset):
        data = original(fd, size, offset)
        replacement.replace(path)
        return data

    monkeypatch.setattr(os, "pread", replace)
    with pytest.raises(BridgeError) as exc:
        FilesystemManager().read(PathScope([str(tmp_path)]), str(path), 2)
    assert exc.value.code == "file_changed"


def test_zero_byte_read_before_observed_eof_fails_without_stuck_cursor(tmp_path, monkeypatch):
    path = tmp_path / "source"
    path.write_bytes(b"not-empty")
    monkeypatch.setattr(os, "pread", lambda *args: b"")
    with pytest.raises(BridgeError) as exc:
        FilesystemManager().read(PathScope([str(tmp_path)]), str(path), 2)
    assert exc.value.code == "read_incomplete"
