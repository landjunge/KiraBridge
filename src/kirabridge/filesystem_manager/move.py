"""Regular-file moves through owned names; never unlink a shared source pathname."""

from __future__ import annotations

import errno
import json
import os
import stat
import uuid
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError, UncertainExecution

MAX_JOURNAL_BYTES = 65536


def _identity(info):
    return {"dev": info.st_dev, "ino": info.st_ino, "type": stat.S_IFMT(info.st_mode)}


def _stat(fd, name):
    try:
        return os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


class _Move:
    def __init__(self, source_fd, source, dest_fd, dest, path, destination, identity):
        self.source_fd, self.source = source_fd, source
        self.dest_fd, self.dest = dest_fd, dest
        self.ref = uuid.uuid4().hex
        self.stage = ".kirabridge-move-" + self.ref
        self.recovery_dir = str(Path(path).parent / self.stage)
        self.stage_fd = None
        self.pin_verified = False
        self.capture_attempted = False
        self.capture_observed = False
        self.cleanup_complete = False
        self.source_removed = False
        self.dest_published = False
        self.placeholder = None
        self.record = {
            "schema": "kirabridge.file-move.v1",
            "ref": self.ref,
            "phase": "preparing",
            "source": path,
            "destination": destination,
            "source_parent": _identity(os.fstat(source_fd)),
            "destination_parent": _identity(os.fstat(dest_fd)),
            "expected": identity,
            "entries": {"pin": None, "captured": None},
            "source_removed": False,
            "dest_published": False,
            "automatic_recovery": False,
        }

    def _journal(self, phase):
        self.record.update(
            phase=phase, source_removed=self.source_removed, dest_published=self.dest_published
        )
        raw = json.dumps(self.record, ensure_ascii=True, allow_nan=False).encode() + b"\n"
        if len(raw) > MAX_JOURNAL_BYTES:
            raise BridgeError("file_move_journal_limit", "Move metadata exceeds recovery limit")
        temporary = ".journal-" + uuid.uuid4().hex
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=self.stage_fd,
        )
        try:
            remaining = memoryview(raw)
            while remaining:
                written = os.write(fd, remaining)
                if written == 0:
                    raise OSError(errno.EIO, "Move journal write made no progress")
                remaining = remaining[written:]
            os.fsync(fd)
            os.replace(
                temporary, "journal.json", src_dir_fd=self.stage_fd, dst_dir_fd=self.stage_fd
            )
            os.fsync(self.stage_fd)
        finally:
            os.close(fd)
            try:
                os.unlink(temporary, dir_fd=self.stage_fd)
            except FileNotFoundError:
                pass

    def _source_is_pin(self):
        current = _stat(self.source_fd, self.source)
        return current is not None and _identity(current) == self.record["expected"]

    def _retained(self):
        entries = {}
        for name in ("pin", "captured"):
            info = _stat(self.stage_fd, name)
            if info is not None and _identity(info) != self.placeholder:
                entries[name] = _identity(info)
        return entries

    def _uncertain(self, phase):
        try:
            self._journal(phase)
        except (OSError, BridgeError, ValueError, TypeError):
            pass  # The pre-capture intent remains useful when later fsync/write fails.
        try:
            entries = self._retained()
        except OSError:
            entries = None
        error = UncertainExecution(
            "file_move_recovery_required", "Move requires explicit local recovery inspection"
        )
        error.provider_error = {
            "schema": "kirabridge.file-move.receipt.v1",
            "ref": self.ref,
            "phase": phase,
            "retained": bool(entries) if entries is not None else None,
            "retained_entries": entries,
            "source_removed": self.source_removed,
            "dest_published": self.dest_published,
            "recovery_dir": self.recovery_dir,
            "automatic_retry": False,
            "automatic_recovery": False,
        }
        return error

    def _cleanup(self):
        # These are exclusively owned aliases. Never unlink source or destination.
        for name in ("captured", "pin"):
            try:
                os.unlink(name, dir_fd=self.stage_fd)
            except FileNotFoundError:
                pass
        os.fsync(self.stage_fd)
        try:
            os.unlink("journal.json", dir_fd=self.stage_fd)
        except FileNotFoundError:
            pass
        os.fsync(self.stage_fd)
        os.rmdir(self.stage, dir_fd=self.source_fd)
        os.fsync(self.source_fd)
        self.cleanup_complete = True

    def _restore(self):
        # Link is no-clobber even if an external writer recreated source already.
        try:
            os.link(
                "captured",
                self.source,
                src_dir_fd=self.stage_fd,
                dst_dir_fd=self.source_fd,
                follow_symlinks=False,
            )
        except OSError:
            return False
        os.fsync(self.source_fd)
        self.source_removed = False
        self._journal("restored")
        return True

    def _perform(self):
        self._journal("preparing")
        os.link(
            self.source,
            "pin",
            src_dir_fd=self.source_fd,
            dst_dir_fd=self.stage_fd,
            follow_symlinks=False,
        )
        pinned = os.stat("pin", dir_fd=self.stage_fd, follow_symlinks=False)
        self.record["entries"]["pin"] = _identity(pinned)
        if not stat.S_ISREG(pinned.st_mode) or _identity(pinned) != self.record["expected"]:
            raise BridgeError("file_move_source_changed", "Move source changed before pinning")
        self.pin_verified = True
        fd = os.open(
            "captured",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=self.stage_fd,
        )
        try:
            self.placeholder = _identity(os.fstat(fd))
        finally:
            os.close(fd)
        self.record["sentinel"] = self.placeholder
        self._journal("prepared")
        # Persist the stage name, pin and intent before removing any public name.
        os.fsync(self.source_fd)
        self.capture_attempted = True
        os.rename(self.source, "captured", src_dir_fd=self.source_fd, dst_dir_fd=self.stage_fd)
        captured = os.stat("captured", dir_fd=self.stage_fd, follow_symlinks=False)
        captured_identity = _identity(captured)
        self.record["entries"]["captured"] = captured_identity
        self.source_removed = captured_identity != self.placeholder
        self.capture_observed = True
        os.fsync(self.source_fd)
        os.fsync(self.stage_fd)
        self._journal("captured")
        if not stat.S_ISREG(captured.st_mode) or captured_identity != self.record["expected"]:
            self._restore()
            # Keep the original pin as well as the unexpected captured entry.
            raise self._uncertain("source_changed")
        self._journal("publish_attempted")
        try:
            os.link(
                "captured",
                self.dest,
                src_dir_fd=self.stage_fd,
                dst_dir_fd=self.dest_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            if not self._restore():
                raise self._uncertain("restore_conflict") from None
            self._cleanup()
            raise FileExistsError(
                errno.EEXIST, "Move destination already exists", self.dest
            ) from None
        except OSError:
            self.dest_published = None  # Do not assert no effect after ambiguous FS errors.
            raise
        self.dest_published = True
        os.fsync(self.dest_fd)
        self._journal("committed")
        self._cleanup()
        return {"moved": True}

    def run(self):
        os.mkdir(self.stage, 0o700, dir_fd=self.source_fd)
        try:
            self.stage_fd = os.open(
                self.stage,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=self.source_fd,
            )
            try:
                return self._perform()
            except UncertainExecution:
                raise
            except Exception:
                if self.cleanup_complete:
                    raise
                # A syscall can fail after an effect (or fsync can fail afterwards).
                try:
                    if not self.pin_verified:
                        pinned = _stat(self.stage_fd, "pin")
                        if pinned is not None and _identity(pinned) == self.record["expected"]:
                            self.pin_verified = True
                            self.record["entries"]["pin"] = _identity(pinned)
                    captured = _stat(self.stage_fd, "captured")
                    source_matches = not self.pin_verified or self._source_is_pin()
                except OSError:
                    if self.capture_attempted and not self.capture_observed:
                        self.source_removed = None
                    raise self._uncertain("observation_uncertain") from None
                if (
                    self.capture_attempted
                    and not self.capture_observed
                    and captured is not None
                    and _identity(captured) != self.placeholder
                ):
                    self.source_removed = True
                    self.record["entries"]["captured"] = _identity(captured)
                if self.capture_observed or self.source_removed or self.dest_published is not False:
                    raise self._uncertain("effect_uncertain") from None
                if not source_matches:
                    raise self._uncertain("source_changed") from None
                self._cleanup()
                raise
        finally:
            if self.stage_fd is not None:
                os.close(self.stage_fd)


def move_file(scope, path, destination):
    with scope.parent(path) as (source_fd, source), scope.parent(destination) as (dest_fd, dest):
        before = os.stat(source, dir_fd=source_fd, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise BridgeError("file_type", "Move supports regular files only")
        if _stat(dest_fd, dest) is not None:
            raise FileExistsError(errno.EEXIST, "Move destination already exists", destination)
        if os.fstat(source_fd).st_dev != os.fstat(dest_fd).st_dev:
            raise OSError(errno.EXDEV, "Move cannot cross filesystems", destination)
        return _Move(source_fd, source, dest_fd, dest, path, destination, _identity(before)).run()
