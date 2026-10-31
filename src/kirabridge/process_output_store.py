"""Durable owned process streams, using the existing Store and file range reader.

Only the managed child drainer writes these files. There is no process attachment,
queue, retry or public arbitrary-file lookup. Storage exhaustion stops capture
explicitly; retained output is never automatically deleted to make room.
"""

import hashlib
import os
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import Field

from kirabridge.bridge_core.models import BridgeError, Input
from kirabridge.file_ranges import _identity, read_file_range
from kirabridge.filesystem_manager import PathScope


class OutputRangeInput(Input):
    task_id: str = Field(min_length=1, max_length=128)
    stream: Literal["stdout", "stderr"] = "stdout"
    offset: int = Field(default=0, ge=0, le=2**63 - 1)
    max_bytes: int = Field(default=65536, ge=1, le=65536)
    encoding: Literal["utf-8", "base64"] = "utf-8"
    expected_identity: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class ProcessOutputStore:
    def __init__(
        self,
        root,
        store,
        *,
        max_stream_bytes=64 * 1024 * 1024,
        max_total_bytes=256 * 1024 * 1024,
        max_streams=4096,
    ):
        self.root, self.store = Path(root).absolute(), store
        for value in (max_stream_bytes, max_total_bytes, max_streams):
            if type(value) is not int or value <= 0:
                raise ValueError("Output resource budgets must be positive integers")
        self.max_stream_bytes = max_stream_bytes
        self.max_total_bytes = max_total_bytes
        self.max_streams = max_streams
        self._writers = {}
        if self.root.is_symlink():
            raise BridgeError("unsafe_state", "Process output directory cannot be a symlink")
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.scope = PathScope([str(self.root)])
        with self.scope.directory(str(self.root)) as fd:
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise BridgeError("unsafe_state", "Process output directory must be owner-only")
            self._directory_identity = (info.st_dev, info.st_ino)
        with store.transaction():
            store.db.execute(
                "CREATE TABLE IF NOT EXISTS process_output_streams ("
                "principal TEXT NOT NULL,task_id TEXT NOT NULL,stream TEXT NOT NULL,"
                "file_name TEXT UNIQUE NOT NULL,bytes INTEGER NOT NULL,sha256 TEXT NOT NULL,"
                "identity TEXT NOT NULL,complete INTEGER NOT NULL,error TEXT,"
                "created REAL NOT NULL,updated REAL NOT NULL,"
                "PRIMARY KEY(principal,task_id,stream))"
            )

    @contextmanager
    def _directory(self):
        with self.scope.directory(str(self.root)) as fd:
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) != self._directory_identity:
                raise BridgeError("process_output_changed", "Process output directory changed")
            yield fd

    def _row(self, principal, task_id, stream):
        if stream not in {"stdout", "stderr"}:
            raise BridgeError("invalid_arguments", "Select stdout or stderr")
        row = self.store.db.execute(
            "SELECT * FROM process_output_streams WHERE principal=? AND task_id=? AND stream=?",
            (principal, task_id, stream),
        ).fetchone()
        if row is None:
            raise BridgeError("not_found", "Owned process output not found")
        return row

    def start(self, principal, task_id):
        """Reserve both streams before starting the child. Never overwrite an old run."""
        created, started_keys = [], []
        try:
            with self.store.transaction(), self._directory() as parent:
                count = self.store.db.execute(
                    "SELECT count(*) FROM process_output_streams"
                ).fetchone()[0]
                if count + 2 > self.max_streams:
                    raise BridgeError(
                        "process_output_limit", "Output stream count budget exhausted"
                    )
                total = self.store.db.execute(
                    "SELECT COALESCE(sum(bytes),0) FROM process_output_streams"
                ).fetchone()[0]
                if total >= self.max_total_bytes:
                    raise BridgeError(
                        "process_output_limit", "Output byte budget exhausted before spawn"
                    )
                if self.store.db.execute(
                    "SELECT 1 FROM process_output_streams WHERE principal=? AND task_id=?",
                    (principal, task_id),
                ).fetchone():
                    raise BridgeError(
                        "process_output_exists", "Output already exists; never replay this run"
                    )
                for stream in ("stdout", "stderr"):
                    name = uuid.uuid4().hex + ".bin"
                    fd = os.open(
                        name,
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=parent,
                    )
                    created.append(name)
                    try:
                        os.fsync(fd)
                        identity = _identity(os.fstat(fd))
                    finally:
                        os.close(fd)
                    hasher = hashlib.sha256()
                    now = time.time()
                    self.store.db.execute(
                        "INSERT INTO process_output_streams VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            principal,
                            task_id,
                            stream,
                            name,
                            0,
                            hasher.hexdigest(),
                            identity,
                            0,
                            None,
                            now,
                            now,
                        ),
                    )
                    self._writers[(principal, task_id, stream)] = hasher
                    started_keys.append((principal, task_id, stream))
                os.fsync(parent)
        except BaseException:
            with self._directory() as parent:
                for name in created:
                    os.unlink(name, dir_fd=parent)
            for key in started_keys:
                self._writers.pop(key, None)
            raise

    def append(self, principal, task_id, stream, chunk):
        if not isinstance(chunk, bytes):
            raise TypeError("Process output must be bytes")
        key = (principal, task_id, stream)
        hasher = self._writers.get(key)
        if hasher is None:
            raise BridgeError("process_output_closed", "No live writer for this output")
        problem = None
        with self.store.transaction(), self._directory() as parent:
            row = self._row(principal, task_id, stream)
            total = self.store.db.execute(
                "SELECT COALESCE(sum(bytes),0) FROM process_output_streams"
            ).fetchone()[0]
            if (
                row["bytes"] + len(chunk) > self.max_stream_bytes
                or total + len(chunk) > self.max_total_bytes
            ):
                raise BridgeError(
                    "process_output_limit", "Output storage budget exhausted; prefix retained"
                )
            fd = os.open(row["file_name"], os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, dir_fd=parent)
            try:
                before = os.fstat(fd)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_nlink != 1
                    or before.st_uid != os.getuid()
                    or before.st_mode & 0o077
                    or before.st_size != row["bytes"]
                    or _identity(before) != row["identity"]
                ):
                    raise BridgeError("process_output_changed", "Output file changed before append")
                position = 0
                try:
                    while position < len(chunk):
                        written = os.write(fd, chunk[position:])
                        if written <= 0:
                            raise OSError("Output append made no progress")
                        hasher.update(chunk[position : position + written])
                        position += written
                    os.fsync(fd)
                except OSError:
                    # Commit the actually retained prefix before reporting the failure.
                    problem = BridgeError(
                        "process_output_storage", "Output append failed; prefix retained"
                    )
                info = os.fstat(fd)
                self.store.db.execute(
                    "UPDATE process_output_streams SET bytes=?,sha256=?,identity=?,updated=? "
                    "WHERE principal=? AND task_id=? AND stream=?",
                    (
                        info.st_size,
                        hasher.hexdigest(),
                        _identity(info),
                        time.time(),
                        principal,
                        task_id,
                        stream,
                    ),
                )
            finally:
                os.close(fd)
        if problem is not None:
            raise problem

    def finish(self, principal, task_id, *, complete, error=None):
        """Finalize captured bytes; an interrupted/limited prefix is never complete."""
        keys = [(principal, task_id, stream) for stream in ("stdout", "stderr")]
        try:
            with self.store.transaction():
                for key in keys:
                    if key not in self._writers:
                        continue
                    self.store.db.execute(
                        "UPDATE process_output_streams SET complete=?,error=?,updated=? "
                        "WHERE principal=? AND task_id=? AND stream=?",
                        (int(complete), error, time.time(), *key),
                    )
        finally:
            for key in keys:
                self._writers.pop(key, None)
        return self.status(principal, task_id)

    def status(self, principal, task_id):
        result = {}
        for stream in ("stdout", "stderr"):
            row = self._row(principal, task_id, stream)
            live = (principal, task_id, stream) in self._writers
            result[stream] = {
                "bytes": row["bytes"],
                "sha256": row["sha256"],
                "identity": row["identity"],
                "complete": bool(row["complete"]),
                "error": row["error"],
                "state": "complete" if row["complete"] else "recording" if live else "incomplete",
            }
        return {
            "streams": result,
            "limits": {
                "max_stream_bytes": self.max_stream_bytes,
                "max_total_bytes": self.max_total_bytes,
                "max_streams": self.max_streams,
                "automatic_deletion": False,
            },
        }

    def read(
        self,
        principal,
        task_id,
        stream="stdout",
        *,
        offset=0,
        max_bytes=65536,
        encoding="utf-8",
        expected_identity=None,
    ):
        row = self._row(principal, task_id, stream)
        with self._directory() as parent:
            info = os.stat(row["file_name"], dir_fd=parent, follow_symlinks=False)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
                or _identity(info) != row["identity"]
            ):
                raise BridgeError("process_output_changed", "Stored output file changed")
        page = read_file_range(
            self.scope,
            str(self.root / row["file_name"]),
            max_bytes,
            offset=offset,
            encoding=encoding,
            expected_identity=expected_identity,
        )
        if page["identity"] != row["identity"] or page["size_observed"] != row["bytes"]:
            raise BridgeError("process_output_changed", "Output changed during page read")
        state = self.status(principal, task_id)
        return {
            **page,
            "task_id": task_id,
            "stream": stream,
            "stream_sha256": row["sha256"],
            "stream_complete": bool(row["complete"]),
            "capture_error": row["error"],
            "capture_state": state["streams"][stream]["state"],
            "limits": state["limits"],
            "scope": "owned process stream page; EOF is for observed bytes, "
            "not a live completion claim",
        }
