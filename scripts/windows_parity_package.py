#!/usr/bin/env python3
"""Build and apply a source Windows parity package. No VM and no policy change.

The zip is a deterministic source payload plus provenance. It is not a
standalone executable. Install it with the existing Python inside an explicit
root. PowerShell ExecutionPolicy is never set. A --commit value is accepted
only when it equals the commit recorded in the payload provenance.

A repository build records `git rev-parse HEAD`. A guest without git can
rebuild that same zip from an unchanged provenance.json after the file
inventory matches. The export bytes are not rewritten and git is not invented.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kirabridge.windows_package import PackageError, install, rollback, status, uninstall  # noqa: E402

LIVE_MARKERS = (
    Path.home() / ".local" / "share" / "kirabridge",
    Path("/Users/landjunge/.local/share/kirabridge"),
)


def refuse_policy(argv: list[str]) -> None:
    for item in argv:
        lowered = item.lower()
        if "executionpolicy" in lowered or "encodedcommand" in lowered or lowered == "bypass":
            raise SystemExit("Refusing an execution-policy change or encoded command")


HARNESS_FILES = (
    "scripts/windows_parity_package.py",
    "scripts/accept_windows_parity.py",
    "scripts/accept_windows_keyboard.py",
    "scripts/accept_windows_windows.py",
    "tests/test_windows_parity_20261106.py",
)


def payload_files() -> list[Path]:
    files = [
        path
        for path in (ROOT / "src" / "kirabridge").rglob("*.py")
        if "__pycache__" not in path.parts and path.is_file() and not path.is_symlink()
    ]
    files.append(ROOT / "pyproject.toml")
    license_file = ROOT / "LICENSE"
    if not license_file.is_file() or license_file.is_symlink():
        raise SystemExit("LICENSE is required by pyproject license-files and is missing")
    files.append(license_file)
    for relative in HARNESS_FILES:
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise SystemExit(f"Required package file is missing: {relative}")
        files.append(path)
    return sorted(set(files))


def git_provenance() -> dict:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        raise SystemExit("git rev-parse HEAD did not return a full lowercase commit")
    return {"commit": commit, "commit_source": "git-rev-parse-HEAD", "dirty": bool(dirty)}


def provenance_document(files: dict[str, bytes]) -> dict:
    observed = git_provenance()
    inventory = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}
    return {
        "commit": observed["commit"],
        "commit_source": observed["commit_source"],
        "dirty": observed["dirty"],
        "version": "0.8.0rc40",
        "standalone_executable": False,
        "kind": "existing-python-plus-zip",
        "files": inventory,
        "entry": {
            "python": "Existing Python >=3.11. The prepared guest is Python 3.14.10.",
            "build": "python -B scripts/windows_parity_package.py build --output dist/parity.zip",
            "build_from_export": (
                "python -B scripts/windows_parity_package.py build "
                "--output dist/parity.zip --provenance-export provenance.json"
            ),
            "install": (
                "python -B scripts/windows_parity_package.py install "
                "--root <new-root> --payload <extracted-zip>"
            ),
            "import": (
                "python -P -B -c \"import sys; sys.path.insert(0, r'<release>/src'); "
                'import kirabridge; print(kirabridge.__file__)"'
            ),
            "dependencies": (
                "Use the prepared Python environment. If a module is missing, install it only "
                "from the existing RC33 Windows Dev Kit wheelhouse with pip --no-index "
                "--find-links. Do not change ExecutionPolicy."
            ),
        },
    }


_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_INVENTORY_NAME = re.compile(r"[A-Za-z0-9_./-]+\Z")


def _hex64(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _inventory_name(name: object) -> bool:
    if not isinstance(name, str) or _INVENTORY_NAME.fullmatch(name) is None:
        return False
    if name in {"", ".", "..", "provenance.json"} or name.startswith("/") or name.endswith("/"):
        return False
    return not name.startswith("../") and "/../" not in f"/{name}/"


def read_provenance_export(path: Path) -> tuple[dict, bytes]:
    """Load one unchanged provenance export. Do not call git and do not rewrite it."""
    if path.is_symlink() or not path.is_file():
        raise SystemExit("Refusing a provenance export that is not a regular file")
    raw = path.read_bytes()
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SystemExit("Provenance export is not JSON") from error
    if not isinstance(document, dict):
        raise SystemExit("Provenance export must be an object")
    if document.get("commit_source") != "git-rev-parse-HEAD":
        raise SystemExit("Refusing a provenance export that did not come from git rev-parse HEAD")
    if document.get("dirty") is not False:
        raise SystemExit("Refusing a dirty provenance export")
    commit = document.get("commit")
    if not isinstance(commit, str) or _COMMIT.fullmatch(commit) is None:
        raise SystemExit("Provenance export commit is not a full lowercase hash")
    files = document.get("files")
    if not isinstance(files, dict) or not files:
        raise SystemExit("Provenance export has no file inventory")
    for name, digest in files.items():
        if not _inventory_name(name) or not _hex64(digest):
            raise SystemExit("Provenance export inventory is not a path-to-sha256 map")
    return document, raw


def _require_same_inventory(members: dict[str, bytes], expected: dict) -> None:
    actual = {name: hashlib.sha256(data).hexdigest() for name, data in members.items()}
    if actual != expected:
        raise SystemExit("Refusing changed export bytes: file inventory does not match provenance")


def _zip_info(name: str) -> zipfile.ZipInfo:
    # Pin the system id. Windows CPython would otherwise write 0 and change the hash.
    info = zipfile.ZipInfo(name)
    info.date_time = (1980, 1, 1, 0, 0, 0)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.create_version = 20
    info.extract_version = 20
    info.external_attr = 0o644 << 16
    info.flag_bits = 0
    return info


def build(output: Path, provenance_export: Path | None = None) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    members = {path.relative_to(ROOT).as_posix(): path.read_bytes() for path in payload_files()}
    if provenance_export is None:
        document = provenance_document(members)
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    else:
        document, encoded = read_provenance_export(provenance_export)
        _require_same_inventory(members, document["files"])
    members["provenance.json"] = encoded
    digest = hashlib.sha256()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(members):
            data = members[name]
            archive.writestr(_zip_info(name), data)
            digest.update(name.encode())
            digest.update(data)
    file_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    return {
        "path": str(output),
        "sha256": file_hash,
        "content_sha256": digest.hexdigest(),
        "commit": document["commit"],
        "commit_source": document.get("commit_source"),
        "dirty": document["dirty"],
        "members": len(members),
        "standalone_executable": False,
    }


def guarded_root(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    for marker in LIVE_MARKERS:
        if resolved == marker or marker in resolved.parents:
            raise SystemExit(f"Refusing the live KiraBridge root {resolved}")
    return resolved


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    refuse_policy(argv)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=("build", "install", "update", "rollback", "uninstall", "status")
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--payload", type=Path)
    parser.add_argument("--provenance-export", type=Path)
    parser.add_argument("--version", default="0.8.0rc40")
    parser.add_argument("--commit", default="")
    args = parser.parse_args(argv)
    if args.provenance_export is not None and args.action != "build":
        raise SystemExit("--provenance-export is only valid for build")
    if args.action == "build":
        output = args.output or Path("dist/KiraBridge-0.8.0rc40-windows-parity-20261106.zip")
        print(build(output, provenance_export=args.provenance_export)["sha256"])
        return 0
    if args.root is None:
        raise SystemExit("An explicit --root is required")
    root = guarded_root(args.root)
    if args.action == "status":
        print(status(root))
        return 0
    if args.action == "rollback":
        print(rollback(root))
        return 0
    if args.action == "uninstall":
        try:
            print(uninstall(root))
        except PackageError as error:
            raise SystemExit(str(error)) from error
        return 0
    if args.payload is None:
        raise SystemExit("install and update require --payload")
    payload = guarded_root(args.payload)
    provenance_path = payload / "provenance.json"
    if not provenance_path.is_file() or provenance_path.is_symlink():
        raise SystemExit("Refusing a payload without provenance.json")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    commit = provenance.get("commit")
    if not isinstance(commit, str):
        raise SystemExit("Payload provenance has no commit")
    if args.commit and args.commit != commit:
        raise SystemExit("Refusing --commit that differs from the payload provenance")
    version = provenance.get("version")
    if not isinstance(version, str) or version != args.version:
        raise SystemExit("Refusing a version that differs from the payload provenance")
    try:
        print(
            install(
                root,
                payload,
                version=version,
                commit=commit,
                update=args.action == "update",
            )
        )
    except PackageError as error:
        raise SystemExit(str(error)) from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
