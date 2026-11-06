#!/usr/bin/env python3
"""Build and apply a source Windows parity package. No VM and no policy change.

A native Windows installer executable is not produced here. The zip is a
deterministic source payload that the guest Python can install inside an
explicit root. PowerShell ExecutionPolicy is never set.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kirabridge.windows_package import install, rollback, status  # noqa: E402

LIVE_MARKERS = (
    Path.home() / ".local" / "share" / "kirabridge",
    Path("/Users/landjunge/.local/share/kirabridge"),
)


def refuse_policy(argv: list[str]) -> None:
    for item in argv:
        lowered = item.lower()
        if "executionpolicy" in lowered or "encodedcommand" in lowered or lowered == "bypass":
            raise SystemExit("Refusing an execution-policy change or encoded command")


def payload_files() -> list[Path]:
    files = [
        path
        for path in (ROOT / "src" / "kirabridge").rglob("*.py")
        if "__pycache__" not in path.parts and path.is_file() and not path.is_symlink()
    ]
    files.extend(
        [
            ROOT / "pyproject.toml",
            ROOT / "scripts" / "windows_parity_package.py",
            ROOT / "scripts" / "accept_windows_parity.py",
        ]
    )
    return sorted(files)


def build(output: Path) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    digest = hashlib.sha256()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in payload_files():
            info = zipfile.ZipInfo(path.relative_to(ROOT).as_posix())
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            data = path.read_bytes()
            archive.writestr(info, data)
            digest.update(info.filename.encode())
            digest.update(data)
    file_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    return {"path": str(output), "sha256": file_hash, "content_sha256": digest.hexdigest()}


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
    parser.add_argument("action", choices=("build", "install", "update", "rollback", "status"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--payload", type=Path)
    parser.add_argument("--version", default="0.8.0rc40")
    parser.add_argument("--commit", default="")
    args = parser.parse_args(argv)
    if args.action == "build":
        output = args.output or Path("dist/KiraBridge-0.8.0rc40-windows-parity-20261106.zip")
        print(build(output)["sha256"])
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
    if args.payload is None or not args.commit:
        raise SystemExit("install and update require --payload and --commit")
    print(
        install(
            root,
            guarded_root(args.payload),
            version=args.version,
            commit=args.commit,
            update=args.action == "update",
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
