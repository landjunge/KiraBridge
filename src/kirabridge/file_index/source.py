"""Current, bounded POSIX file observations through the existing PathScope."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from kirabridge.bridge_core.models import BridgeError, digest
from kirabridge.filesystem_manager import PathScope
from kirabridge.permissions import permission_revision, state_exclusions

FILE_BYTES = 1024 * 1024
BATCH_BYTES = 8 * FILE_BYTES
ENTRIES = 500
IGNORED = {
    "node_modules",
    "target",
    "dist",
    "build",
    "venv",
    "__pycache__",
    "vault",
    "vaults",
    "secrets",
    "credentials",
}
SECRET_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".db", ".sqlite", ".sqlite3"}


class SourceFailure(BridgeError):
    def __init__(self, code="source_changed"):
        super().__init__(code, "File source unavailable, changed or excluded")


@dataclass(frozen=True)
class Document:
    relative: str
    text: str
    stamp: str
    size: int


def stamp(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_mode,
        info.st_nlink,
    )


def case_excluded(scope, path):
    # Conservatively covers case aliases on the target Mac as well; no resolve
    # or protected-directory traversal is needed to enforce the deny list.
    value = str(path).casefold().rstrip("/")
    return any(
        value == str(p).casefold().rstrip("/")
        or value.startswith(str(p).casefold().rstrip("/") + "/")
        for p in scope.excluded
    )


class Source:
    def __init__(self, config, security, principal, project):
        self.config, self.security = config, security
        self.principal, self.project = principal, project

    def view(self):
        # Re-fetch both capabilities: no cached PrincipalConfig is authority.
        self.security.principal(self.principal, "file.read")
        policy = self.security.principal(self.principal, "file.list")
        settings = self.config.file_index
        if not settings.enabled or self.project not in settings.projects:
            raise BridgeError("search_scope_denied", "Search scope unavailable")
        root = Path(settings.projects[self.project])
        if root in {Path("/"), Path.home().absolute()}:
            raise BridgeError("search_scope_denied", "An explicit project directory is required")
        home = Path.home().absolute()
        protected = [
            self.config.state_path,
            home / ".config/kirabridge",
            home / ".ssh",
            home / ".gnupg",
            home / ".4allpass",
            home / ".config/4allpass",
            home / "Library/Safari",
            home / "Library/Keychains",
            home / "Library/Application Support/Google",
            home / "Library/Application Support/Chromium",
            home / "Library/Application Support/Firefox",
        ]
        for value in (self.config._source_path, self.config.credentials_file):
            if value:
                protected.append(Path(value).expanduser().absolute())
        excluded = [
            *state_exclusions(self.config, policy),
            *(str(p) for p in protected),
            *(str(root / value) for value in settings.exclusions),
        ]
        scope = PathScope(policy.roots + policy.read_roots, excluded=excluded)
        scope.split(str(root))
        if case_excluded(scope, root):
            raise BridgeError("search_scope_denied", "Search scope unavailable")
        try:
            with scope.directory(str(root)) as fd:
                info = os.fstat(fd)
                identity = (info.st_dev, info.st_ino)
        except OSError:
            raise SourceFailure() from None
        token = digest(
            [
                self.principal,
                self.project,
                str(root),
                identity,
                permission_revision(self.config),
                settings.model_dump(),
                excluded,
            ]
        )
        return scope, root, token

    def checked_view(self, expected):
        view = self.view()
        if view[2] != expected:
            raise BridgeError("generation_changed", "Search observation changed")
        return view

    def relative(self, value, *, directory=False):
        try:
            size = len(value.encode("utf-8")) if isinstance(value, str) else 4097
        except UnicodeError:
            raise SourceFailure("source_excluded") from None
        if size > 4096 or "\0" in value:
            raise SourceFailure("source_excluded")
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or not value
            or str(path) != value
            or any(
                p in {".", ".."} or p.startswith(".") or p.casefold() in IGNORED for p in path.parts
            )
        ):
            raise SourceFailure("source_excluded")
        if any(
            path == PurePosixPath(p) or PurePosixPath(p) in path.parents
            for p in self.config.file_index.exclusions
        ):
            raise SourceFailure("source_excluded")
        if not directory and (
            path.suffix.lower() in SECRET_SUFFIXES
            or path.suffix.lower() not in self.config.file_index.text_extensions
            or path.name.lower().startswith(("secrets.", "credentials."))
        ):
            raise SourceFailure("source_excluded")
        return path

    def capture(self, relative, expected):
        part = self.relative(relative)
        scope, root, _ = self.checked_view(expected)
        path = str(root / part)
        if len(path.encode("utf-8")) > 4096 or case_excluded(scope, path):
            raise SourceFailure("source_excluded")
        try:
            with scope.parent(path) as (parent, name):
                parent_id = stamp(os.fstat(parent))[:2]
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    before = os.fstat(fd)
                    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                        raise SourceFailure("source_excluded")
                    if before.st_size > FILE_BYTES:
                        raise SourceFailure("source_over_limit")
                    with os.fdopen(fd, "rb", closefd=False) as stream:
                        raw = stream.read(FILE_BYTES)
                    after = os.fstat(fd)
                    if stamp(before) != stamp(after) or len(raw) != before.st_size:
                        raise SourceFailure()
                    fresh_scope, _, _ = self.checked_view(expected)
                    with fresh_scope.parent(path) as (fresh_parent, fresh_name):
                        current = os.stat(fresh_name, dir_fd=fresh_parent, follow_symlinks=False)
                        if stamp(os.fstat(fresh_parent))[:2] != parent_id or stamp(
                            current
                        ) != stamp(after):
                            raise SourceFailure()
                finally:
                    os.close(fd)
        except OSError:
            raise SourceFailure() from None
        if b"\0" in raw:
            raise SourceFailure("source_excluded")
        try:
            text = raw.decode("utf-8")
        except UnicodeError:
            raise SourceFailure("source_excluded") from None
        self.checked_view(expected)
        return Document(relative, text, digest(stamp(after)), len(raw))

    def walk(self, expected, relative="", depth=0):
        scope, root, _ = self.checked_view(expected)
        try:
            with scope.directory(str(root / relative)) as fd, os.scandir(fd) as entries:
                for entry in entries:
                    value = str(PurePosixPath(relative) / entry.name)
                    try:
                        is_directory = entry.is_dir(follow_symlinks=False)
                        self.relative(value, directory=is_directory)
                        scope.split(str(root / value))
                        if case_excluded(scope, root / value):
                            raise SourceFailure("source_excluded")
                    except (BridgeError, UnicodeError, OSError):
                        yield "", "skip"
                        continue
                    if is_directory:
                        yield "", "skip"
                        if depth >= 11:
                            yield "", "depth_budget"
                        else:
                            yield from self.walk(expected, value, depth + 1)
                    elif entry.is_file(follow_symlinks=False):
                        yield value, "file"
                    else:
                        yield "", "skip"
        except OSError:
            yield "", "source_unreadable"
