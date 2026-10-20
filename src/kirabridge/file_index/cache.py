"""Separate disposable cache; never the Bridge task/event database."""

from __future__ import annotations

import os
import sqlite3
import stat
from time import monotonic
from uuid import uuid4

from kirabridge.bridge_core.config import private_directory
from kirabridge.bridge_core.models import BridgeError
from kirabridge.file_index.source import ENTRIES
from kirabridge.filesystem_manager import PathScope

FTS_SQL = "CREATE VIRTUAL TABLE IF NOT EXISTS content USING fts5(body)"


class Cache:
    def __init__(self, state_path):
        self.directory = state_path / "file-index"
        self.path = self.directory / "content.sqlite3"
        self.db = None
        self.fts = False
        self.identity = None

    def open(self):
        # Reject an existing symlink in the state-directory ancestry before
        # creating or opening any disposable files there.
        scope = PathScope([str(self.directory.parent)])
        with scope.directory(str(self.directory.parent)):
            private_directory(self.directory)
        with scope.directory(str(self.directory)):
            pass
        if self.db is not None:
            try:
                info = self.path.lstat()
                if (
                    (info.st_dev, info.st_ino) != self.identity
                    or not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or info.st_uid != os.getuid()
                    or info.st_mode & 0o077
                    or info.st_size > 1024 * 1024 * 1024
                ):
                    raise OSError("cache exchanged")
            except OSError:
                self.close()
                raise BridgeError("index_unavailable", "Disposable cache changed") from None
            return self.db
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        before = self.path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.getuid()
            or before.st_mode & 0o077
            or before.st_size > 1024 * 1024 * 1024
        ):
            raise BridgeError("index_unavailable", "Disposable cache is not private")
        db = sqlite3.connect(self.path.absolute().as_uri() + "?mode=rw", uri=True, timeout=0.1)
        try:
            after = self.path.lstat()
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise BridgeError("index_unavailable", "Disposable cache changed")
            db.execute("PRAGMA trusted_schema=OFF")
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            db.execute("PRAGMA max_page_count=%d" % (1024 * 1024 * 1024 // page_size))
            db.execute("""CREATE TABLE IF NOT EXISTS scopes(
                id TEXT PRIMARY KEY,token TEXT,epoch TEXT,status TEXT,scan TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS files(
                scope TEXT,relative TEXT,stamp TEXT,bytes INTEGER,seen TEXT,
                UNIQUE(scope,relative))""")
            try:
                db.execute(FTS_SQL)
                self.fts = True
            except sqlite3.OperationalError:
                self.fts = False
            db.commit()
        except BaseException:
            db.close()
            raise
        self.db = db
        self.identity = (after.st_dev, after.st_ino)
        return db

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None

    def discard(self):
        """Trusted local operator only; fixed disposable names, no source paths."""
        self.close()
        if not self.directory.exists():
            return
        private_directory(self.directory)
        names = (
            "content.sqlite3",
            "content.sqlite3-journal",
            "content.sqlite3-wal",
            "content.sqlite3-shm",
        )
        scope = PathScope([str(self.directory)])
        with scope.directory(str(self.directory)) as fd:
            for name in names:
                try:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or info.st_uid != os.getuid()
                ):
                    raise BridgeError("index_unavailable", "Refuse unsafe disposable cache")
            for name in names:
                try:
                    os.unlink(name, dir_fd=fd)
                except FileNotFoundError:
                    pass

    def state(self, scope):
        row = (
            self.open()
            .execute(
                "SELECT substr(token,1,129),substr(epoch,1,129),substr(status,1,64),"
                "substr(scan,1,129) FROM scopes WHERE id=?",
                (scope,),
            )
            .fetchone()
        )
        if row is None:
            return {"token": "", "epoch": "", "status": "not_built", "scan": ""}
        return dict(zip(("token", "epoch", "status", "scan"), row, strict=True))

    def start(self, scope, token):
        scan = uuid4().hex
        with self.open() as db:
            db.execute(
                "INSERT OR REPLACE INTO scopes VALUES(?,?,?,?,?)",
                (scope, token, uuid4().hex, "building", scan),
            )
        return scan

    def write(self, scope, scan, documents, *, exhausted=False, partial=False):
        db = self.open()
        with db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT scan FROM scopes WHERE id=?", (scope,)).fetchone()
            if current is None or current[0] != scan:
                raise BridgeError("generation_changed", "Cache observation superseded")
            for doc in documents:
                row = db.execute(
                    "SELECT rowid FROM files WHERE scope=? AND relative=?", (scope, doc.relative)
                ).fetchone()
                if row is None:
                    cursor = db.execute(
                        "INSERT INTO files VALUES(?,?,?,?,?)",
                        (scope, doc.relative, doc.stamp, doc.size, scan),
                    )
                    rowid = cursor.lastrowid
                else:
                    rowid = row[0]
                    db.execute(
                        "UPDATE files SET stamp=?,bytes=?,seen=? WHERE rowid=?",
                        (doc.stamp, doc.size, scan, rowid),
                    )
                if self.fts:
                    db.execute("DELETE FROM content WHERE rowid=?", (rowid,))
                    db.execute("INSERT INTO content(rowid,body) VALUES(?,?)", (rowid, doc.text))
            status = "building"
            if exhausted:
                old = db.execute(
                    "SELECT rowid FROM files WHERE scope=? AND seen!=? LIMIT ?",
                    (scope, scan, ENTRIES),
                ).fetchall()
                if self.fts:
                    db.executemany("DELETE FROM content WHERE rowid=?", old)
                db.executemany("DELETE FROM files WHERE rowid=?", old)
                if not old:
                    status = "partial" if partial else "reconciled_observation"
            db.execute(
                "UPDATE scopes SET epoch=?,status=? WHERE id=? AND scan=?",
                (uuid4().hex, status, scope, scan),
            )
        return self.state(scope)

    def candidates(self, scope, terms):
        after = 0
        expression = " AND ".join('"' + value.replace('"', '""') + '"' for value in terms)
        while True:
            db = self.open()
            paused = False
            try:
                end = monotonic() + 0.1
                db.set_progress_handler(lambda end=end: int(monotonic() > end), 1000)
                rows = db.execute(
                    """SELECT content.rowid,substr(f.relative,1,4097),substr(f.stamp,1,129)
                    FROM content JOIN files f ON f.rowid=content.rowid
                    WHERE content MATCH ? AND f.scope=? AND content.rowid>?
                    ORDER BY content.rowid LIMIT ?""",
                    (expression, scope, after, ENTRIES),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                if getattr(exc, "sqlite_errorcode", None) in (5, 6, 9) or str(exc) == "interrupted":
                    paused = True
                else:
                    raise
            finally:
                db.set_progress_handler(None, 0)
            if paused:
                yield "", "query_budget"
                continue
            if not rows:
                return
            for rowid, relative, observed in rows:
                after = rowid
                yield relative, observed
