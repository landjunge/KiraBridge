"""File-level Windows install, update and rollback inside one explicit root.

No service, registry, execution-policy or macOS install path is changed.
User data under root/data is kept. A release directory is not deleted.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path


class PackageError(ValueError):
    pass


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


def _digest_tree(payload: Path) -> dict:
    files = {}
    for path in sorted(item for item in payload.rglob("*") if item.is_file()):
        if path.is_symlink():
            raise PackageError("Refusing a symlink in the package payload")
        relative = path.relative_to(payload).as_posix()
        if relative.startswith("../") or relative == "data":
            raise PackageError("Refusing a payload path outside the release files")
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not files:
        raise PackageError("The package payload is empty")
    return files


def _read_current(root: Path) -> dict | None:
    path = root / "current.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_current(root: Path, value: dict) -> None:
    temporary = root / f".current.{os.getpid()}.json"
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(value, output, separators=(",", ":"), sort_keys=True)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, root / "current.json")


def status(root: Path) -> dict:
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
    if root.is_symlink() or payload.is_symlink():
        raise PackageError("Refusing a symlink package root or payload")
    root.mkdir(parents=True, exist_ok=True)
    root = _inside(root, root)
    payload = _inside(payload, payload)
    release = _release_id(version, commit)
    destination = _inside(root, root / "releases" / release)
    current = _read_current(root)
    if update and current is None:
        raise PackageError("Update requires an existing installation")
    if not update and current is not None:
        raise PackageError("Install refuses to replace an existing installation; use update")
    files = _digest_tree(payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        existing = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
        if existing.get("files") != files:
            raise PackageError("This release id already exists with different bytes")
    else:
        staging = destination.with_name(destination.name + ".partial")
        if staging.exists():
            raise PackageError("A partial release already exists and was not replaced")
        shutil.copytree(payload, staging, symlinks=False)
        manifest = {
            "release": release,
            "version": version,
            "commit": commit,
            "files": files,
            "execution_policy_changed": False,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        os.replace(staging, destination)
    previous = None if current is None else current["release"]
    if previous == release:
        return {"action": "unchanged", "release": release, "previous": current.get("previous")}
    _write_current(
        root,
        {
            "release": release,
            "version": version,
            "commit": commit,
            "previous": previous,
            "execution_policy_changed": False,
        },
    )
    (root / "data").mkdir(exist_ok=True)
    return {
        "action": "update" if update else "install",
        "release": release,
        "previous": previous,
        "execution_policy_changed": False,
    }


def rollback(root: Path) -> dict:
    root = _inside(Path(root), Path(root))
    current = _read_current(root)
    if not current or not current.get("previous"):
        raise PackageError("Rollback requires a recorded previous release")
    previous = current["previous"]
    manifest_path = root / "releases" / previous / "manifest.json"
    if not manifest_path.is_file():
        raise PackageError("The previous release manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _write_current(
        root,
        {
            "release": previous,
            "version": manifest["version"],
            "commit": manifest["commit"],
            "previous": current["release"],
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
