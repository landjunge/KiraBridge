"""Bounded native integrity reads with real owned files; no app or worker launch."""

import os
import stat
import tracemalloc
from types import SimpleNamespace

import pytest

from kirabridge.platform_adapters.macos import system_transport as native


def private_file(tmp_path, data=b"native fixture"):
    path = tmp_path / "native-fixture"
    path.write_bytes(data)
    path.chmod(0o600)
    return path


def intercept_read(monkeypatch, action):
    original = native.os.fdopen
    descriptors = []

    class Reader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def read(self, size):
            return action(self.stream, size)

    def opened(fd, *args, **kwargs):
        descriptors.append(fd)
        return Reader(original(fd, *args, **kwargs))

    monkeypatch.setattr(native.os, "fdopen", opened)
    return descriptors


@pytest.mark.parametrize("size", [0, 1, 15, 16])
def test_private_file_accepts_complete_data_through_exact_limit(tmp_path, size):
    expected = b"x" * size
    path = private_file(tmp_path, expected)
    data, observed = native._private_file(path, 16)
    assert data == expected and observed.st_size == size


def test_private_file_rejects_oversize_before_opening_stream(tmp_path, monkeypatch):
    path = private_file(tmp_path, b"x" * 17)

    def refuse(*args, **kwargs):
        pytest.fail("Oversized file must not reach a stream read")

    monkeypatch.setattr(native.os, "fdopen", refuse)
    with pytest.raises(ValueError, match="exceeds limit"):
        native._private_file(path, 16)


def test_private_file_small_binary_does_not_reserve_32_mib_limit(tmp_path):
    path = private_file(tmp_path, b"x" * 1024)
    if tracemalloc.is_tracing():
        pytest.skip("Another tracing owner is active")
    tracemalloc.start()
    try:
        data, _ = native._private_file(path, 32 * 1024 * 1024)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert data == b"x" * 1024
    assert peak < 1024 * 1024, "A small binary must not allocate the entire 32-MiB allowance"


@pytest.mark.parametrize("change", ["growth", "shrink", "same_size"])
def test_private_file_rejects_file_changes_during_read(tmp_path, monkeypatch, change):
    path = private_file(tmp_path)
    initial = path.stat()

    def read(stream, size):
        changed = {"growth": b"x" * 30, "shrink": b"x", "same_size": b"x" * initial.st_size}
        path.write_bytes(changed[change])
        os.utime(path, ns=(initial.st_atime_ns, initial.st_mtime_ns + 1_000_000_000))
        return stream.read(size)

    descriptors = intercept_read(monkeypatch, read)
    with pytest.raises(ValueError, match="changed during metadata read"):
        native._private_file(path, 1024)
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


@pytest.mark.parametrize("delta", [-1, 1])
def test_private_file_requires_exact_byte_count_even_when_stat_is_unchanged(
    tmp_path, monkeypatch, delta
):
    path = private_file(tmp_path)

    def read(stream, size):
        data = stream.read(size)
        return data[:-1] if delta < 0 else data + b"x"

    intercept_read(monkeypatch, read)
    with pytest.raises(ValueError, match="changed during metadata read"):
        native._private_file(path, 1024)


@pytest.mark.parametrize("field", ["st_ino", "st_size", "st_mtime_ns"])
def test_private_file_rechecks_original_identity_after_read(tmp_path, monkeypatch, field):
    path = private_file(tmp_path)
    original = native.os.fstat
    calls = 0

    def observed(fd):
        nonlocal calls
        info = original(fd)
        calls += 1
        if calls == 1:
            return info
        value = {
            name: getattr(info, name)
            for name in ("st_mode", "st_uid", "st_size", "st_ino", "st_mtime_ns")
        }
        value[field] += 1
        return SimpleNamespace(**value)

    monkeypatch.setattr(native.os, "fstat", observed)
    with pytest.raises(ValueError, match="changed during metadata read"):
        native._private_file(path, 1024)
    assert calls == 2


@pytest.mark.parametrize(
    "kind", ["symlink", "directory", "fifo", "group_writable", "world_writable"]
)
def test_private_file_refuses_untrusted_file_types_and_modes(tmp_path, kind):
    path = private_file(tmp_path)
    if kind == "symlink":
        link = tmp_path / "link"
        link.symlink_to(path)
        path = link
    elif kind in {"directory", "fifo"}:
        path.unlink()
        path.mkdir() if kind == "directory" else os.mkfifo(path, 0o600)
    else:
        path.chmod(0o620 if kind == "group_writable" else 0o602)
    with pytest.raises((OSError, ValueError)):
        native._private_file(path, 1024)


def test_private_file_refuses_untrusted_owner_before_read(tmp_path, monkeypatch):
    path = private_file(tmp_path)
    info = path.stat()
    observed = SimpleNamespace(st_mode=info.st_mode, st_uid=max(os.getuid(), 0) + 100_000)
    monkeypatch.setattr(native.os, "fstat", lambda fd: observed)
    with pytest.raises(ValueError, match="Untrusted native app file"):
        native._private_file(path, 1024)


def test_private_file_keeps_regular_read_only_root_or_user_files_valid(tmp_path):
    path = private_file(tmp_path)
    path.chmod(stat.S_IRUSR)
    assert native._private_file(path, 1024)[0] == b"native fixture"
