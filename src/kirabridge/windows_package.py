"""File-level Windows install, update and rollback inside one explicit root.

No service, registry, execution-policy or macOS install path is changed.
User data under root/data is kept. A release directory is not deleted.
Activation rehashes the bytes on disk. Links and reparse points are refused.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import time
from contextlib import contextmanager
from pathlib import Path

_RELEASE_ID = re.compile(r"[0-9a-z][0-9a-z.-]{0,60}-[0-9a-f]{12}\Z")
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class PackageError(ValueError):
    pass


def _is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, "st_file_attributes", 0) & _REPARSE)


def _inside(root: Path, path: Path) -> Path:
    root = root.resolve()
    path = path.resolve()
    if path != root and root not in path.parents:
        raise PackageError("Refusing a path outside the package root")
    return path


def _release_id(version: str, commit: str) -> str:
    if not version or not commit or len(commit) < 12:
        raise PackageError("Version and a commit of at least 12 hex characters are required")
    if any(char not in "0123456789abcdefghijklmnopqrstuvwxyz.-" for char in version):
        raise PackageError("Version contains an unsupported character")
    if any(char not in "0123456789abcdef" for char in commit[:12]):
        raise PackageError("Commit prefix must be lowercase hex")
    return f"{version}-{commit[:12]}"


def _release_directory(root: Path, release_id: str) -> Path:
    if not isinstance(release_id, str) or _RELEASE_ID.fullmatch(release_id) is None:
        raise PackageError("Refusing a release id that is not a single safe path segment")
    releases = root / "releases"
    candidate = releases / release_id
    if _is_link_or_reparse(releases) or _is_link_or_reparse(candidate):
        raise PackageError("Refusing a linked release path")
    if candidate.exists():
        resolved = candidate.resolve()
        if resolved.parent != releases.resolve():
            raise PackageError("Refusing a release outside the package root")
    return candidate


def _reject_special(path: Path, *, allow_hardlink: bool = False) -> None:
    if _is_link_or_reparse(path):
        raise PackageError("Refusing a link or reparse point in the package payload")
    info = path.lstat()
    if not allow_hardlink and stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        raise PackageError("Refusing a hard link in the package payload")
    if not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode):
        raise PackageError("Refusing a non-regular package entry")


def _digest_tree(payload: Path) -> dict:
    files = {}
    if _is_link_or_reparse(payload) or not payload.is_dir():
        raise PackageError("Refusing a package payload that is not a real directory")
    for directory, dirnames, filenames in os.walk(payload, followlinks=False):
        current = Path(directory)
        if current != payload:
            _reject_special(current, allow_hardlink=True)
        for name in dirnames:
            child = current / name
            if _is_link_or_reparse(child) or not child.is_dir():
                raise PackageError("Refusing a directory link or reparse point")
        for name in filenames:
            path = current / name
            _reject_special(path)
            relative = path.relative_to(payload).as_posix()
            if relative.startswith("../") or relative == ".." or "/../" in f"/{relative}/":
                raise PackageError("Refusing a payload path outside the release files")
            files[relative] = hashlib.sha256(_read_nofollow(path)).hexdigest()
    if not files:
        raise PackageError("The package payload is empty")
    return files


def _read_nofollow(path: Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        stream = os.fdopen(fd, "rb")
    except Exception:
        os.close(fd)
        raise
    with stream:
        return stream.read()


def _copy_regular_tree(source: Path, destination: Path) -> None:
    destination.mkdir()
    for directory, dirnames, filenames in os.walk(source, followlinks=False):
        current = Path(directory)
        target = destination / current.relative_to(source)
        for name in dirnames:
            child = current / name
            if _is_link_or_reparse(child) or not stat.S_ISDIR(child.lstat().st_mode):
                raise PackageError("Refusing a directory link or reparse point")
            (target / name).mkdir()
        for name in filenames:
            child = current / name
            _reject_special(child)
            target_file = target / name
            data = _read_nofollow(child)
            fd = os.open(target_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            with os.fdopen(fd, "wb") as output:
                output.write(data)


def _provenance(payload: Path, files: dict) -> dict | None:
    path = payload / "provenance.json"
    if not path.exists():
        return None
    _reject_special(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PackageError("Payload provenance is not JSON") from error
    if not isinstance(value, dict):
        raise PackageError("Payload provenance must be an object")
    inventory = value.get("files")
    if not isinstance(inventory, dict):
        raise PackageError("Payload provenance has no file inventory")
    actual = {name: digest for name, digest in files.items() if name != "provenance.json"}
    if actual != inventory:
        raise PackageError("Payload bytes do not match the provenance inventory")
    commit = value.get("commit")
    if not isinstance(commit, str) or len(commit) < 12:
        raise PackageError("Payload provenance has no commit")
    return value


def _manifest_of(directory: Path) -> dict:
    path = directory / "manifest.json"
    if not path.is_file() or _is_link_or_reparse(path):
        raise PackageError("The release manifest is missing")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PackageError("The release manifest is not JSON") from error
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise PackageError("The release manifest has no file inventory")
    return manifest


def _verify_release_bytes(directory: Path, files: dict) -> None:
    actual = _digest_tree(directory)
    actual.pop("manifest.json", None)
    if actual != files:
        raise PackageError("Release bytes do not match the pinned manifest")


def _read_current(root: Path) -> dict | None:
    path = root / "current.json"
    if not path.exists():
        return None
    if _is_link_or_reparse(path):
        raise PackageError("Refusing a linked current.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_current(root: Path, value: dict) -> None:
    temporary = root / f".current.{os.getpid()}.json"
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(value, output, separators=(",", ":"), sort_keys=True)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, root / "current.json")


def _discard_staging(staging: Path, releases: Path) -> None:
    if staging.name.endswith(".partial") and staging.parent.resolve() == releases.resolve():
        shutil.rmtree(staging)


@contextmanager
def package_lock(root: Path):
    """Block other install, update and rollback processes. Do not rewrite user data."""
    root.mkdir(parents=True, exist_ok=True)
    if _is_link_or_reparse(root):
        raise PackageError("Refusing a linked package root")
    lock_path = root / ".package.lock"
    if _is_link_or_reparse(lock_path):
        raise PackageError("Refusing a linked package lock")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(lock_path, flags, 0o600)
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(fd).st_size < 1:
                os.write(fd, b"\0")
            deadline = time.monotonic() + 120
            while True:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise PackageError("The package lock is busy") from None
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def status(root: Path) -> dict:
    root = Path(root)
    if root.is_symlink() or _is_link_or_reparse(root):
        raise PackageError("Refusing a linked package root")
    root = _inside(root, root)
    current = _read_current(root)
    return {
        "root": str(root),
        "installed": current is not None,
        "current": current,
        "data_preserved": (root / "data").is_dir(),
        "execution_policy_changed": False,
    }


def install(root: Path, payload: Path, *, version: str, commit: str, update: bool = False) -> dict:
    root = Path(root)
    payload = Path(payload)
    if root.is_symlink() or payload.is_symlink() or _is_link_or_reparse(payload):
        raise PackageError("Refusing a symlink package root or payload")
    with package_lock(root):
        root = _inside(root, root)
        payload = _inside(payload, payload)
        release = _release_id(version, commit)
        files = _digest_tree(payload)
        provenance = _provenance(payload, files)
        if provenance is not None and provenance.get("commit") != commit:
            raise PackageError("Commit does not match the payload provenance")
        destination = _release_directory(root, release)
        current = _read_current(root)
        if update and current is None:
            raise PackageError("Update requires an existing installation")
        if not update and current is not None:
            raise PackageError("Install refuses to replace an existing installation; use update")
        releases = root / "releases"
        releases.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            manifest = _manifest_of(destination)
            _verify_release_bytes(destination, manifest["files"])
            if manifest["files"] != files or manifest.get("commit") != commit:
                raise PackageError("This release id already exists with different bytes")
        else:
            staging = destination.with_name(destination.name + ".partial")
            if staging.exists():
                raise PackageError("A partial release already exists and was not replaced")
            try:
                _copy_regular_tree(payload, staging)
                if _digest_tree(staging) != files:
                    raise PackageError("Staged tree does not match the pinned manifest")
                manifest = {
                    "release": release,
                    "version": version,
                    "commit": commit,
                    "files": files,
                    "provenance_verified": provenance is not None,
                    "execution_policy_changed": False,
                }
                (staging / "manifest.json").write_text(
                    json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8"
                )
                os.replace(staging, destination)
            except Exception:
                if staging.exists():
                    _discard_staging(staging, releases)
                raise
        previous = None if current is None else current["release"]
        if previous == release:
            return {
                "action": "unchanged",
                "release": release,
                "previous": current.get("previous"),
                "provenance_verified": provenance is not None,
                "execution_policy_changed": False,
            }
        _write_current(
            root,
            {
                "release": release,
                "version": version,
                "commit": commit,
                "previous": previous,
                "provenance_verified": provenance is not None,
                "execution_policy_changed": False,
            },
        )
        (root / "data").mkdir(exist_ok=True)
        return {
            "action": "update" if update else "install",
            "release": release,
            "previous": previous,
            "provenance_verified": provenance is not None,
            "execution_policy_changed": False,
        }


def rollback(root: Path) -> dict:
    root = Path(root)
    if root.is_symlink() or _is_link_or_reparse(root):
        raise PackageError("Refusing a linked package root")
    with package_lock(root):
        root = _inside(root, root)
        current = _read_current(root)
        if not current or not current.get("previous"):
            raise PackageError("Rollback requires a recorded previous release")
        previous = current["previous"]
        directory = _release_directory(root, previous)
        manifest = _manifest_of(directory)
        _verify_release_bytes(directory, manifest["files"])
        if manifest.get("release") != previous:
            raise PackageError("The previous release manifest does not name that release")
        _write_current(
            root,
            {
                "release": previous,
                "version": manifest["version"],
                "commit": manifest["commit"],
                "previous": current["release"],
                "provenance_verified": manifest.get("provenance_verified") is True,
                "execution_policy_changed": False,
            },
        )
        return {
            "action": "rollback",
            "release": previous,
            "previous": current["release"],
            "data_preserved": (root / "data").is_dir(),
            "execution_policy_changed": False,
        }


def uninstall(root: Path) -> dict:
    """Remove release directories and current.json. Keep root/data.

    No service, registry or execution-policy change. Unexpected release
    entries are left in place and reported as an error instead of deleted.
    """
    root = Path(root)
    if root.is_symlink() or _is_link_or_reparse(root):
        raise PackageError("Refusing a linked package root")
    with package_lock(root):
        root = _inside(root, root)
        current = _read_current(root)
        if current is None:
            raise PackageError("Uninstall requires an existing installation")
        releases = root / "releases"
        if _is_link_or_reparse(releases) or not releases.is_dir():
            raise PackageError("Refusing a release path that is not a real directory")
        removed = []
        for child in sorted(releases.iterdir(), key=lambda item: item.name):
            if _is_link_or_reparse(child):
                raise PackageError("Refusing a linked release path")
            if child.is_dir() and (
                _RELEASE_ID.fullmatch(child.name) or child.name.endswith(".partial")
            ):
                if child.name.endswith(".partial"):
                    raise PackageError("A partial release exists and was not removed")
                shutil.rmtree(child)
                removed.append(child.name)
                continue
            raise PackageError("Refusing to uninstall around an unexpected release entry")
        current_path = root / "current.json"
        if _is_link_or_reparse(current_path) or not current_path.is_file():
            raise PackageError("Refusing a current.json that is not a regular file")
        current_path.unlink()
        return {
            "action": "uninstall",
            "removed": removed,
            "previous": current.get("release"),
            "data_preserved": (root / "data").is_dir(),
            "execution_policy_changed": False,
        }
