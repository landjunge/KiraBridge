"""Independent namespace contracts for move; every path is a private test fixture."""

import errno
import json
import os
import re
import stat
from pathlib import Path

import pytest

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.filesystem_manager import FilesystemManager, PathScope


def move(root):
    return FilesystemManager().move(
        PathScope([str(root)]), str(root / "source"), str(root / "destination")
    )


def shared_capture(root, source, options):
    """Locate the effect on the public source, independent of private stage names."""
    fd = options.get("src_dir_fd")
    return (
        fd is not None
        and Path(source).name == "source"
        and (os.fstat(fd).st_dev, os.fstat(fd).st_ino) == (root.stat().st_dev, root.stat().st_ino)
    )


def retained_payloads(root, content):
    return [
        path
        for path in root.rglob("*")
        if stat.S_ISREG(path.lstat().st_mode) and path.read_bytes() == content
    ]


def recovery_receipt(error, root):
    receipt = error.provider_error
    assert receipt["retained"] is True
    assert re.fullmatch(r"[a-f0-9]{32}", receipt["ref"])
    assert isinstance(receipt["phase"], str) and receipt["phase"]
    recovery = Path(receipt["recovery_dir"])
    assert recovery.is_relative_to(root)
    assert stat.S_IMODE(recovery.lstat().st_mode) & 0o077 == 0
    journal = json.loads((recovery / "journal.json").read_text())
    assert journal["ref"] == receipt["ref"]
    return receipt, recovery, journal


def test_move_accepts_an_unreadable_regular_source(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    source, destination = root / "source", root / "destination"
    source.write_bytes(b"original")
    source.chmod(0)
    original_open = os.open

    def no_source_open(path, *args, **options):
        assert Path(path).name != "source", "Pinning must not require opening source data"
        return original_open(path, *args, **options)

    monkeypatch.setattr(os, "open", no_source_open)
    try:
        assert move(root) == {"moved": True}
        assert not source.exists()
        assert stat.S_IMODE(destination.stat().st_mode) == 0
    finally:
        for path in (source, destination):
            if path.exists():
                path.chmod(0o600)
    assert destination.read_bytes() == b"original"


@pytest.mark.parametrize("kind", ["regular", "directory", "symlink"])
def test_existing_destination_is_never_overwritten(tmp_path, kind):
    root = tmp_path.resolve()
    source, destination = root / "source", root / "destination"
    source.write_bytes(b"original")
    if kind == "regular":
        destination.write_bytes(b"preserved")
    elif kind == "directory":
        destination.mkdir()
        (destination / "child").write_bytes(b"preserved")
    else:
        destination.symlink_to("source")
    before = destination.lstat()

    with pytest.raises(FileExistsError):
        move(root)

    after = destination.lstat()
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
    assert source.read_bytes() == b"original"
    if kind == "directory":
        assert (destination / "child").read_bytes() == b"preserved"
    elif kind == "symlink":
        assert destination.is_symlink()
    else:
        assert destination.read_bytes() == b"preserved"


def test_same_source_and_destination_retains_no_clobber_contract(tmp_path):
    root = tmp_path.resolve()
    source = root / "source"
    source.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        FilesystemManager().move(PathScope([str(root)]), str(source), str(source))
    assert source.read_bytes() == b"original"


def test_source_recreated_after_destination_publication_is_preserved(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    source, destination = root / "source", root / "destination"
    source.write_bytes(b"original")
    original_sync = os.fsync
    recreated = False

    def after_publish(fd):
        nonlocal recreated
        if not recreated and destination.exists():
            recreated = True
            replacement = root / "writer-temporary"
            replacement.write_bytes(b"new writer")
            os.replace(replacement, source)
        return original_sync(fd)

    monkeypatch.setattr(os, "fsync", after_publish)
    assert move(root) == {"moved": True}
    assert recreated
    assert source.read_bytes() == b"new writer"
    assert destination.read_bytes() == b"original"


def test_directory_substituted_at_capture_is_never_moved(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    source, destination = root / "source", root / "destination"
    source.write_bytes(b"original")
    original_rename = os.rename
    captures = []

    def substitute_directory(old, new, *args, **options):
        if shared_capture(root, old, options):
            captures.append(old)
            source.unlink()
            source.mkdir()
            (source / "child").write_bytes(b"unapproved directory content")
        return original_rename(old, new, *args, **options)

    monkeypatch.setattr(os, "rename", substitute_directory)
    with pytest.raises((BridgeError, OSError)):
        move(root)

    assert len(captures) == 1
    assert (source / "child").read_bytes() == b"unapproved directory content"
    assert not destination.exists()


@pytest.mark.parametrize("kind", ["regular", "symlink", "fifo"])
def test_wrong_captured_identity_is_not_published(tmp_path, monkeypatch, kind):
    root = tmp_path.resolve()
    source, destination = root / "source", root / "destination"
    source.write_bytes(b"original")
    (root / "target").write_bytes(b"untouched target")
    original_rename = os.rename
    captures = []

    def substitute_nondirectory(old, new, *args, **options):
        if shared_capture(root, old, options):
            captures.append(old)
            source.unlink()
            if kind == "regular":
                source.write_bytes(b"replacement")
            elif kind == "symlink":
                source.symlink_to("target")
            else:
                os.mkfifo(source)
        return original_rename(old, new, *args, **options)

    monkeypatch.setattr(os, "rename", substitute_nondirectory)
    with pytest.raises(UncertainExecution):
        move(root)

    assert len(captures) == 1
    assert not destination.exists()
    assert retained_payloads(root, b"original"), "The pinned original must remain recoverable"
    assert (root / "target").read_bytes() == b"untouched target"
    if kind == "regular":
        assert source.read_bytes() == b"replacement"
    elif kind == "symlink":
        assert source.is_symlink()
    else:
        assert stat.S_ISFIFO(source.lstat().st_mode)


def test_publication_and_restore_conflict_preserve_every_writer(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    source, destination = root / "source", root / "destination"
    source.write_bytes(b"original")
    original_rename = os.rename
    captures = []

    def competing_names_after_capture(old, new, *args, **options):
        result = original_rename(old, new, *args, **options)
        if shared_capture(root, old, options):
            captures.append(old)
            source.write_bytes(b"new source writer")
            destination.write_bytes(b"new destination writer")
        return result

    monkeypatch.setattr(os, "rename", competing_names_after_capture)
    with pytest.raises(UncertainExecution):
        move(root)

    assert len(captures) == 1
    assert source.read_bytes() == b"new source writer"
    assert destination.read_bytes() == b"new destination writer"
    assert retained_payloads(root, b"original")


def test_source_removed_by_another_writer_after_pin_remains_recoverable(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    source = root / "source"
    source.write_bytes(b"original")
    original_rename = os.rename
    interrupted = False

    def remove_before_capture(old, new, *args, **options):
        nonlocal interrupted
        if shared_capture(root, old, options):
            interrupted = True
            source.unlink()
        return original_rename(old, new, *args, **options)

    monkeypatch.setattr(os, "rename", remove_before_capture)
    with pytest.raises(UncertainExecution) as error:
        move(root)

    assert interrupted and not source.exists()
    assert not (root / "destination").exists()
    _, recovery, _ = recovery_receipt(error.value, root)
    assert retained_payloads(recovery, b"original")


def test_failed_initial_persistence_prevents_shared_source_capture(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    source = root / "source"
    source.write_bytes(b"original")
    original_rename, original_sync = os.rename, os.fsync
    captures = []
    failed = False

    def track_capture(old, new, *args, **options):
        if shared_capture(root, old, options):
            captures.append(old)
        return original_rename(old, new, *args, **options)

    def fail_first_sync(fd):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError(errno.EIO, "private initial-persistence failure")
        return original_sync(fd)

    monkeypatch.setattr(os, "rename", track_capture)
    monkeypatch.setattr(os, "fsync", fail_first_sync)
    with pytest.raises((BridgeError, OSError)):
        move(root)

    assert failed and not captures
    assert source.read_bytes() == b"original"
    assert not (root / "destination").exists()


def test_fsync_failure_after_capture_retains_receipt_and_original(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    (root / "source").write_bytes(b"original")
    original_rename, original_sync = os.rename, os.fsync
    captured, failed = False, False

    def capture(old, new, *args, **options):
        nonlocal captured
        result = original_rename(old, new, *args, **options)
        if shared_capture(root, old, options):
            captured = True
        return result

    def fail_first_capture_sync(fd):
        nonlocal failed
        if captured and not failed:
            failed = True
            raise OSError(errno.EIO, "private simulated synchronization failure")
        return original_sync(fd)

    monkeypatch.setattr(os, "rename", capture)
    monkeypatch.setattr(os, "fsync", fail_first_capture_sync)
    with pytest.raises(UncertainExecution) as error:
        move(root)

    assert captured and failed
    receipt, recovery, _ = recovery_receipt(error.value, root)
    assert receipt["dest_published"] is False
    assert retained_payloads(recovery, b"original")
    assert not (root / "destination").exists()


def test_fsync_failure_after_publication_keeps_both_durable_evidence_names(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    (root / "source").write_bytes(b"original")
    destination = root / "destination"
    original_sync = os.fsync
    failed = False

    def fail_first_published_sync(fd):
        nonlocal failed
        if destination.exists() and not failed:
            failed = True
            raise OSError(errno.EIO, "private simulated synchronization failure")
        return original_sync(fd)

    monkeypatch.setattr(os, "fsync", fail_first_published_sync)
    with pytest.raises(UncertainExecution) as error:
        move(root)

    assert failed and destination.read_bytes() == b"original"
    receipt, recovery, _ = recovery_receipt(error.value, root)
    assert receipt["dest_published"] is True
    retained = retained_payloads(recovery, b"original")
    assert retained
    assert any(path.stat().st_ino == destination.stat().st_ino for path in retained)


def test_capture_effect_followed_by_io_error_keeps_recovery_and_new_source(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    source = root / "source"
    source.write_bytes(b"original")
    original_rename = os.rename
    interrupted = False

    def error_after_effect(old, new, *args, **options):
        nonlocal interrupted
        result = original_rename(old, new, *args, **options)
        if shared_capture(root, old, options):
            interrupted = True
            source.write_bytes(b"new source writer")
            raise OSError(errno.EIO, "private ambiguous capture completion")
        return result

    monkeypatch.setattr(os, "rename", error_after_effect)
    with pytest.raises(UncertainExecution) as error:
        move(root)

    assert interrupted and source.read_bytes() == b"new source writer"
    assert not (root / "destination").exists()
    _, recovery, _ = recovery_receipt(error.value, root)
    assert retained_payloads(recovery, b"original")


def test_publication_effect_followed_by_io_error_is_retained_without_replay(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    source, destination = root / "source", root / "destination"
    source.write_bytes(b"original")
    original_link = os.link
    attempts = []

    def ambiguous_publication(old, new, *args, **options):
        result = original_link(old, new, *args, **options)
        if Path(new).name == "destination":
            attempts.append(new)
            source.write_bytes(b"new source writer")
            raise OSError(errno.EIO, "private ambiguous publication completion")
        return result

    monkeypatch.setattr(os, "link", ambiguous_publication)
    with pytest.raises(UncertainExecution) as error:
        move(root)

    assert len(attempts) == 1
    assert source.read_bytes() == b"new source writer"
    assert destination.read_bytes() == b"original"
    receipt, recovery, _ = recovery_receipt(error.value, root)
    assert receipt["dest_published"] is not False
    assert receipt["automatic_retry"] is False
    assert retained_payloads(recovery, b"original")


def test_journal_enospc_after_capture_keeps_last_durable_intent(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    (root / "source").write_bytes(b"original")
    original_rename, original_write = os.rename, os.write
    captured = False
    failures = []

    def capture(old, new, *args, **options):
        nonlocal captured
        result = original_rename(old, new, *args, **options)
        if shared_capture(root, old, options):
            captured = True
        return result

    def full_medium(fd, content):
        if captured:
            failures.append(fd)
            raise OSError(errno.ENOSPC, "private full-medium simulation")
        return original_write(fd, content)

    monkeypatch.setattr(os, "rename", capture)
    monkeypatch.setattr(os, "write", full_medium)
    with pytest.raises(UncertainExecution) as error:
        move(root)

    assert captured and failures
    receipt, recovery, journal = recovery_receipt(error.value, root)
    assert journal["entries"]["pin"]
    assert receipt["automatic_recovery"] is False
    assert retained_payloads(recovery, b"original")
    assert not (root / "destination").exists()


def test_capture_metadata_failure_cannot_hide_uncertain_recovery_receipt(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    (root / "source").write_bytes(b"original")
    original_rename, original_stat = os.rename, os.stat
    captured = False

    def ambiguous_capture(old, new, *args, **options):
        nonlocal captured
        result = original_rename(old, new, *args, **options)
        if shared_capture(root, old, options):
            captured = True
            raise OSError(errno.EIO, "private ambiguous capture")
        return result

    def unreadable_captured_metadata(path, *args, **options):
        if captured and str(path) == "captured" and options.get("dir_fd") is not None:
            raise OSError(errno.EIO, "private capture-metadata failure")
        return original_stat(path, *args, **options)

    monkeypatch.setattr(os, "rename", ambiguous_capture)
    monkeypatch.setattr(os, "stat", unreadable_captured_metadata)
    with pytest.raises(UncertainExecution) as error:
        move(root)

    assert captured
    receipt = error.value.provider_error
    assert receipt["automatic_retry"] is False
    assert receipt["automatic_recovery"] is False
    assert receipt["source_removed"] is not False
    assert receipt["retained"] in (True, None)
    recovery = Path(receipt["recovery_dir"])
    assert json.loads((recovery / "journal.json").read_text())["ref"] == receipt["ref"]
    assert retained_payloads(recovery, b"original")
    assert not (root / "destination").exists()


def test_source_metadata_failure_during_error_handling_retains_a_receipt(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    source = root / "source"
    source.write_bytes(b"original")
    original_rename, original_stat = os.rename, os.stat
    attempted = False

    def failed_capture(old, new, *args, **options):
        nonlocal attempted
        if shared_capture(root, old, options):
            attempted = True
            raise OSError(errno.EIO, "private capture failed without effect")
        return original_rename(old, new, *args, **options)

    def unreadable_source_metadata(path, *args, **options):
        if attempted and str(path) == "source" and options.get("dir_fd") is not None:
            raise OSError(errno.EIO, "private source-metadata failure")
        return original_stat(path, *args, **options)

    monkeypatch.setattr(os, "rename", failed_capture)
    monkeypatch.setattr(os, "stat", unreadable_source_metadata)
    with pytest.raises(UncertainExecution) as error:
        move(root)

    assert attempted and source.read_bytes() == b"original"
    _, recovery, _ = recovery_receipt(error.value, root)
    assert retained_payloads(recovery, b"original")
    assert not (root / "destination").exists()


@pytest.mark.parametrize("variant", ["uppercase", "kelvin_sign"])
def test_recovery_guard_cannot_be_bypassed_by_a_case_alias(tmp_path, variant):
    root = tmp_path.resolve()
    name = ".kirabridge-move-" + "a" * 32
    recovery = root / name
    recovery.mkdir(mode=0o700)
    (recovery / "payload").write_bytes(b"private retained content")
    alias_name = name.upper() if variant == "uppercase" else name.replace("k", "\u212a")
    alias = root / alias_name / "payload"
    if not alias.exists():
        pytest.skip("This volume distinguishes the two case variants")

    with pytest.raises(BridgeError) as error:
        FilesystemManager().read(PathScope([str(root)]), str(alias), 100)

    assert error.value.code == "path_denied"
    assert (recovery / "payload").read_bytes() == b"private retained content"
