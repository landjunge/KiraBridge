#!/usr/bin/env python3
"""Observe one verified Windows candidate tree. Never relabel or execute reports."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

from build_windows_dev_kit import (
    CANDIDATE_BLOB_LIMIT,
    CANDIDATE_PRODUCERS,
    CANDIDATE_TREE_LIMIT,
    MODULE_PATH,
    REQUIRED_HARNESSES,
    VERSION_PATHS,
    candidate_inventory,
    require_same_bytes,
)


def read_regular(path: Path, maximum: int) -> bytes:
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise ValueError("Linked candidate paths are refused")
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise ValueError("Candidate file is not a bounded regular file")
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())

    def signature(value):
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns

    if len(data) > maximum or signature(before) != signature(after):
        raise ValueError("Candidate file changed while reading")
    return data


def inspect_source(
    root: Path, manifest_path: Path, expected_manifest: str, version: str, commit: str
) -> dict:
    """Pure hash comparison; this result alone is never native execution evidence."""
    if not re.fullmatch(r"[a-f0-9]{64}", expected_manifest) or not re.fullmatch(
        r"[a-f0-9]{40}", commit
    ):
        raise ValueError("Exact source and manifest pins required")
    root, manifest_path = root.absolute(), manifest_path.absolute()
    raw = read_regular(manifest_path, 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != expected_manifest:
        raise ValueError("Manifest differs from its explicit pin")
    manifest = json.loads(raw)
    if manifest.get("schema_version") != 1 or manifest.get("source_commit") != commit:
        raise ValueError("Manifest source identity differs")
    entries = manifest.get("files")
    if not isinstance(entries, list) or any(not isinstance(row, dict) for row in entries):
        raise ValueError("Invalid payload manifest")
    source = [row for row in entries if row.get("path") == "source.zip"]
    if len(source) != 1:
        raise ValueError("One source archive is required")
    zipped = read_regular(manifest_path.parent / "source.zip", 512 * 1024 * 1024)
    if (
        source[0].get("bytes") != len(zipped)
        or source[0].get("sha256") != hashlib.sha256(zipped).hexdigest()
    ):
        raise ValueError("Source archive differs from the pinned manifest")
    with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
        names = archive.namelist()
        if len(names) > 20000 or len({name.casefold() for name in names}) != len(names):
            raise ValueError("Duplicate or excessive archive paths")
        if archive.comment != commit.encode("ascii"):
            raise ValueError("Source archive commit differs")
        for name in names:
            path = PurePosixPath(name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in name
                or ":" in name
                or "\x00" in name
                or str(path).rstrip("/") != name.rstrip("/")
            ):
                raise ValueError("Unsafe source archive path")
        modules = [
            name for name in names if name.startswith("src/kirabridge/") and name.endswith(".py")
        ]
        if (
            not modules
            or len(modules) > CANDIDATE_TREE_LIMIT
            or any(not MODULE_PATH.fullmatch(name) for name in modules)
        ):
            raise ValueError("Invalid runtime inventory")
        required = set(modules) | set(REQUIRED_HARNESSES) | set(VERSION_PATHS)
        required.update(CANDIDATE_PRODUCERS)
        if not required <= set(names):
            raise ValueError("Missing candidate producer or harness")
        frozen = {}
        for name in sorted(required):
            info = archive.getinfo(name)
            if info.file_size > CANDIDATE_BLOB_LIMIT or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("Unsafe candidate archive file")
            frozen[name] = archive.read(name)
    actual_names = {p.relative_to(root).as_posix() for p in (root / "src/kirabridge").rglob("*.py")}
    if actual_names != set(modules):
        raise ValueError("Extracted runtime module set differs from frozen source")
    actual = {name: read_regular(root / name, CANDIDATE_BLOB_LIMIT) for name in frozen}
    require_same_bytes(actual, frozen, "Executed source")
    bootstrap = [row for row in entries if row.get("path") == "guest_runner.ps1"]
    if len(bootstrap) != 1:
        raise ValueError("One pinned bootstrap is required")
    runner = read_regular(manifest_path.parent / "guest_runner.ps1", CANDIDATE_BLOB_LIMIT)
    if (
        bootstrap[0].get("sha256") != hashlib.sha256(runner).hexdigest()
        or bootstrap[0].get("bytes") != len(runner)
        or runner != actual["scripts/windows_guest_runner.ps1"]
    ):
        raise ValueError("Executed bootstrap differs from candidate source")
    document, inventory_hash = candidate_inventory(version, commit, actual)
    return {**document, "inventory_sha256": inventory_hash}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--candidate-version", required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args(argv)
    if os.name != "nt" or sys.platform != "win32":
        parser.error("Native Windows required; no evidence is generated on this host")
    observed = inspect_source(
        args.source_root,
        args.manifest,
        args.manifest_sha256,
        args.candidate_version,
        args.source_commit,
    )
    spec = importlib.util.find_spec("kirabridge")
    expected = (args.source_root / "src/kirabridge/__init__.py").resolve()
    if spec is None or spec.origin is None or Path(spec.origin).resolve() != expected:
        parser.error("Python import route does not use the verified candidate source")
    print(json.dumps({**observed, "evidence_platform": sys.platform}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
