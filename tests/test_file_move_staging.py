"""Move effects use isolated real files; no application or user data is touched."""

import errno
import json
import os
from pathlib import Path

import pytest

from kirabridge.bridge_core.models import UncertainExecution
from kirabridge.filesystem_manager import FilesystemManager, PathScope


def paths(tmp_path):
    root = tmp_path.resolve()
    source, destination = root / "source", root / "destination"
    source.write_bytes(b"original")
    return source, destination, PathScope([str(root)])


def test_new_source_after_publish_is_preserved(tmp_path, monkeypatch):
    source, destination, scope = paths(tmp_path)
    sync = os.fsync
    replaced = False

    def replace_after_publish(fd):
        nonlocal replaced
        if not replaced and destination.exists():
            replaced = True
            replacement = source.parent / "replacement"
            replacement.write_bytes(b"new concurrent source")
            os.replace(replacement, source)
        sync(fd)

    monkeypatch.setattr(os, "fsync", replace_after_publish)
    assert FilesystemManager().move(scope, str(source), str(destination)) == {"moved": True}
    assert replaced
    assert source.read_bytes() == b"new concurrent source"
    assert destination.read_bytes() == b"original"


def test_commit_fsync_failure_retains_recovery_and_reports_uncertainty(tmp_path, monkeypatch):
    source, destination, scope = paths(tmp_path)
    sync = os.fsync

    def failed_commit(fd):
        if destination.exists():
            raise OSError(errno.EIO, "isolated fsync failure")
        sync(fd)

    monkeypatch.setattr(os, "fsync", failed_commit)
    with pytest.raises(UncertainExecution) as error:
        FilesystemManager().move(scope, str(source), str(destination))
    receipt = error.value.provider_error
    assert receipt["retained"] is True
    assert receipt["source_removed"] is True
    assert receipt["dest_published"] is True
    recovery = Path(receipt["recovery_dir"])
    assert recovery.parent == source.parent
    journal = json.loads((recovery / "journal.json").read_text())
    assert journal["ref"] == receipt["ref"]
    assert (recovery / "pin").read_bytes() == b"original"
    assert (recovery / "captured").read_bytes() == b"original"
    assert destination.read_bytes() == b"original"


def test_ordinary_move_preserves_mode_and_removes_owned_stage(tmp_path):
    source, destination, scope = paths(tmp_path)
    source.chmod(0o640)
    assert FilesystemManager().move(scope, str(source), str(destination)) == {"moved": True}
    assert not source.exists()
    assert destination.read_bytes() == b"original"
    assert destination.stat().st_mode & 0o777 == 0o640
    assert sorted(p.name for p in source.parent.iterdir()) == ["destination"]


@pytest.mark.parametrize("replacement", ["directory", "file", "symlink", "fifo", "missing"])
def test_capture_replacement_never_publishes_foreign_object(tmp_path, monkeypatch, replacement):
    import stat

    source, destination, scope = paths(tmp_path)
    target = source.parent / "symlink-target"
    target.write_bytes(b"untouched")
    rename = os.rename

    def replace_before_capture(old, new, **kwargs):
        if old == source.name:
            source.unlink()
            if replacement == "directory":
                source.mkdir()
                (source / "child").write_bytes(b"directory child")
            elif replacement == "file":
                source.write_bytes(b"foreign file")
            elif replacement == "symlink":
                source.symlink_to(target)
            elif replacement == "fifo":
                os.mkfifo(source)
        return rename(old, new, **kwargs)

    monkeypatch.setattr(os, "rename", replace_before_capture)
    with pytest.raises(UncertainExecution) as error:
        FilesystemManager().move(scope, str(source), str(destination))
    recovery = Path(error.value.provider_error["recovery_dir"])
    assert (recovery / "pin").read_bytes() == b"original"
    assert error.value.provider_error["retained"] is True
    assert not destination.exists()
    assert target.read_bytes() == b"untouched"
    if replacement == "directory":
        assert source.is_dir() and (source / "child").read_bytes() == b"directory child"
        assert error.value.provider_error["source_removed"] is False
    elif replacement == "file":
        assert source.read_bytes() == (recovery / "captured").read_bytes() == b"foreign file"
    elif replacement == "symlink":
        assert source.is_symlink() and (recovery / "captured").is_symlink()
        assert os.readlink(source) == str(target)
    elif replacement == "fifo":
        assert stat.S_ISFIFO(source.lstat().st_mode)
        assert stat.S_ISFIFO((recovery / "captured").lstat().st_mode)
    else:
        assert not source.exists()


def test_rename_error_after_capture_keeps_both_original_aliases(tmp_path, monkeypatch):
    source, destination, scope = paths(tmp_path)
    rename = os.rename

    def uncertain_capture(*args, **kwargs):
        rename(*args, **kwargs)
        raise OSError(errno.EIO, "capture completed before error")

    monkeypatch.setattr(os, "rename", uncertain_capture)
    with pytest.raises(UncertainExecution) as error:
        FilesystemManager().move(scope, str(source), str(destination))
    receipt = error.value.provider_error
    assert receipt["source_removed"] is True and receipt["retained"] is True
    recovery = Path(receipt["recovery_dir"])
    assert (recovery / "pin").read_bytes() == (recovery / "captured").read_bytes() == b"original"
    assert not source.exists() and not destination.exists()


@pytest.mark.parametrize("recreate_source", [False, True])
def test_destination_race_never_clobbers_source_or_destination(
    tmp_path, monkeypatch, recreate_source
):
    source, destination, scope = paths(tmp_path)
    link = os.link

    def occupy_before_publish(old, new, **kwargs):
        if new == destination.name:
            destination.write_bytes(b"concurrent destination")
            if recreate_source:
                source.write_bytes(b"concurrent source")
        return link(old, new, **kwargs)

    monkeypatch.setattr(os, "link", occupy_before_publish)
    with pytest.raises(UncertainExecution if recreate_source else FileExistsError) as error:
        FilesystemManager().move(scope, str(source), str(destination))
    assert destination.read_bytes() == b"concurrent destination"
    if recreate_source:
        assert source.read_bytes() == b"concurrent source"
        recovery = Path(error.value.provider_error["recovery_dir"])
        assert (recovery / "pin").read_bytes() == b"original"
        assert (recovery / "captured").read_bytes() == b"original"
    else:
        assert source.read_bytes() == b"original"
        assert not list(source.parent.glob(".kirabridge-move-*"))


def test_regular_source_never_requires_content_open(tmp_path, monkeypatch):
    source, destination, scope = paths(tmp_path)
    source.chmod(0)
    opened = os.open

    def reject_source_open(path, *args, **kwargs):
        assert path != source.name and path != str(source)
        return opened(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", reject_source_open)
    assert FilesystemManager().move(scope, str(source), str(destination)) == {"moved": True}
    assert destination.stat().st_mode & 0o777 == 0


def test_source_alias_is_rejected_before_capture(tmp_path):
    source, _, scope = paths(tmp_path)
    with pytest.raises(FileExistsError):
        FilesystemManager().move(scope, str(source), str(source))
    assert source.read_bytes() == b"original"
    assert not list(source.parent.glob(".kirabridge-move-*"))


def test_cleanup_error_after_restore_keeps_a_recovery_receipt(tmp_path, monkeypatch):
    source, destination, scope = paths(tmp_path)
    link, unlink = os.link, os.unlink

    def conflict_before_publish(old, new, **kwargs):
        if new == destination.name:
            destination.write_bytes(b"preserved target")
        return link(old, new, **kwargs)

    def fail_owned_cleanup(name, **kwargs):
        if name == "captured" and source.exists() and destination.exists():
            raise OSError(errno.EIO, "owned-alias cleanup failure")
        return unlink(name, **kwargs)

    monkeypatch.setattr(os, "link", conflict_before_publish)
    monkeypatch.setattr(os, "unlink", fail_owned_cleanup)
    with pytest.raises(UncertainExecution) as error:
        FilesystemManager().move(scope, str(source), str(destination))
    assert source.read_bytes() == b"original"
    assert destination.read_bytes() == b"preserved target"
    assert error.value.provider_error["retained"] is True
    assert error.value.provider_error["source_removed"] is False


def test_ambiguous_pin_with_disappeared_source_keeps_the_only_original(tmp_path, monkeypatch):
    source, destination, scope = paths(tmp_path)
    link = os.link

    def ambiguous_pin(old, new, **kwargs):
        result = link(old, new, **kwargs)
        if new == "pin":
            source.unlink()
            raise OSError(errno.EIO, "pin completed before error")
        return result

    monkeypatch.setattr(os, "link", ambiguous_pin)
    with pytest.raises(UncertainExecution) as error:
        FilesystemManager().move(scope, str(source), str(destination))
    assert not source.exists() and not destination.exists()
    receipt = error.value.provider_error
    assert receipt["retained"] is True
    assert (Path(receipt["recovery_dir"]) / "pin").read_bytes() == b"original"
