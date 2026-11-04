#!/usr/bin/env python3
"""Assemble a private offline Windows runtime; optionally compile Inno Setup.

Inputs are fixed published RC33 bytes and the official CPython embeddable ZIP.
No downloads, platform installs, VM operations or release publication occur.
Runtime staging on macOS is not Windows runtime or installer acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import struct
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

VERSION = "0.8.0rc33"
SOURCE_COMMIT = "ce0687dd8831dae261bf285922a146bcf3aedc41"
KIT_SHA256 = "1002e68cbef96c7fd9a383d542beb5abc727f5843316352a65638fe4266a919a"
PYTHON_VERSION = "3.14.10"
# https://www.python.org/ftp/python/3.14.10/windows-3.14.10.json
# pythonembed-3.14-64 (the newer 'embeddable' filename, not the legacy 'embed').
PYTHON_SHA256 = "b553e7dac884469b40e0740bb527271c3378f700b427e0485835f1bb6424361c"
PYTHON_URL = "https://www.python.org/ftp/python/3.14.10/python-3.14.10-embeddable-amd64.zip"
ROOT = Path(__file__).resolve().parents[1]
SHELL_FILES = ("launch.cmd", "configure.cmd", "windows_launcher.ps1")
MAX_ARCHIVE = 128 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def path_name(name: str) -> str:
    parts = PurePosixPath(name).parts
    if (
        not name
        or name.startswith("/")
        or "\\" in name
        or not parts
        or any(part in (".", "..") or ":" in part or part.endswith((".", " ")) for part in parts)
        or "/".join(parts) != name
        or any(
            re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", p, re.I) for p in parts
        )
    ):
        raise ValueError("Unsafe archive path")
    return name


def archive_files(raw: bytes) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    seen = set()
    expanded = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for info in archive.infolist():
            name = info.filename.rstrip("/") if info.is_dir() else info.filename
            path_name(name)
            key = name.casefold()
            if key in seen or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("Duplicate or linked archive member")
            seen.add(key)
            if info.is_dir():
                continue
            expanded += info.file_size
            if expanded > MAX_EXPANDED or info.file_size > MAX_ARCHIVE:
                raise ValueError("Archive exceeds unpacking budget")
            files[name] = archive.read(info)
    return files


def checked_input(path: Path, expected: str) -> bytes:
    path = path.expanduser().absolute()
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("Linked input path refused")
    with path.open("rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_ARCHIVE:
            raise ValueError("Expected bounded regular archive")
        raw = source.read(MAX_ARCHIVE + 1)
        after = os.fstat(source.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    ) or digest(raw) != expected:
        raise ValueError("Archive digest differs from the fixed published input")
    return raw


def verified_kit(raw: bytes) -> dict[str, bytes]:
    archive = archive_files(raw)
    prefix = "KiraBridge-Windows-Dev-Kit/"
    if any(not name.startswith(prefix) for name in archive):
        raise ValueError("Unexpected Dev Kit root")
    files = {name[len(prefix) :]: body for name, body in archive.items()}
    sums = {}
    for line in files["SHA256SUMS"].decode("ascii").splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  (.+)", line)
        if not match or match[2] in sums:
            raise ValueError("Invalid Dev Kit checksum list")
        sums[path_name(match[2])] = match[1]
    if set(sums) != set(files) - {"SHA256SUMS"}:
        raise ValueError("Dev Kit checksum inventory differs")
    if any(digest(files[name]) != expected for name, expected in sums.items()):
        raise ValueError("Dev Kit member digest differs")
    package = json.loads(files["package.json"])
    manifest = json.loads(files["manifest.json"])
    if (
        package.get("version") != VERSION
        or package.get("source_commit") != SOURCE_COMMIT
        or manifest.get("python_version") != PYTHON_VERSION
        or package.get("payload_manifest_sha256") != digest(files["manifest.json"])
    ):
        raise ValueError("Dev Kit source, Python or version differs")
    return files


def require_amd64_pe(raw: bytes):
    if len(raw) < 64 or raw[:2] != b"MZ":
        raise ValueError("Expected AMD64 PE executable")
    offset = struct.unpack_from("<I", raw, 0x3C)[0]
    if offset + 6 > len(raw) or raw[offset : offset + 6] != b"PE\0\0d\x86":
        raise ValueError("Expected AMD64 PE executable")


def wheel_destination(name: str) -> str:
    path_name(name)
    parts = name.split("/")
    if parts[0].endswith(".data"):
        if len(parts) < 3:
            raise ValueError("Incomplete wheel data path")
        scheme = parts[1]
        if scheme in ("purelib", "platlib"):
            return "Lib/site-packages/" + "/".join(parts[2:])
        if scheme == "scripts":
            return "Scripts/" + "/".join(parts[2:])
        if scheme == "data":
            return "/".join(parts[2:])
        if scheme == "headers":
            return "Include/" + "/".join(parts[2:])
        raise ValueError("Unsupported wheel data scheme")
    return "Lib/site-packages/" + name


def runtime_files(kit: dict[str, bytes], python_zip: bytes) -> dict[str, bytes]:
    runtime = archive_files(python_zip)
    for name in ("python.exe", "pythonw.exe", "python314.dll"):
        require_amd64_pe(runtime[name])
    if "python314.zip" not in runtime or "python314._pth" not in runtime:
        raise ValueError("Incomplete embedded Python")
    # Site imports pywin32's own .pth bootstrap; isolated paths exclude global
    # Python installs, PYTHONPATH and the current working directory.
    runtime["python314._pth"] = b"python314.zip\r\n.\r\nLib/site-packages\r\nimport site\r\n"
    seen = {name.casefold() for name in runtime}
    wheels = {name: body for name, body in kit.items() if name.startswith("wheels/")}
    if len(wheels) != 38:
        raise ValueError("Expected 38 frozen offline wheels")
    for name, raw in sorted(wheels.items()):
        if not name.endswith(("-win_amd64.whl", "-any.whl")):
            raise ValueError("Wheel architecture differs")
        for member, body in archive_files(raw).items():
            destination = path_name(wheel_destination(member))
            if destination.casefold() in seen:
                raise ValueError("Wheel would overwrite another runtime member")
            seen.add(destination.casefold())
            runtime[destination] = body
    runtime["windows_lifecycle.py"] = (ROOT / "installer/windows/windows_lifecycle.py").read_bytes()
    return runtime


def stage(kit_path: Path, python_path: Path, out: Path):
    kit = verified_kit(checked_input(kit_path, KIT_SHA256))
    runtime = runtime_files(kit, checked_input(python_path, PYTHON_SHA256))
    files = {name: digest(body) for name, body in sorted(runtime.items())}
    manifest = {
        "schema_version": 1,
        "version": VERSION,
        "release_id": digest(canonical(files))[:32],
        "source_commit": SOURCE_COMMIT,
        "python_version": PYTHON_VERSION,
        "kit_sha256": KIT_SHA256,
        "python_archive_sha256": PYTHON_SHA256,
        "files": files,
    }
    runtime["runtime-manifest.json"] = canonical(manifest) + b"\n"
    payload = {"Runtime/" + name: body for name, body in runtime.items()}
    for name in SHELL_FILES:
        payload["shell/" + name] = (ROOT / "installer/windows" / name).read_bytes()
    payload["shell/KiraBridge.ico"] = (
        ROOT / "assets/design/icons/windows/KiraBridge-dark.ico"
    ).read_bytes()
    payload["LICENSE.txt"] = kit["LICENSE"]
    for name in ("README-DE.txt", "README-EN.txt", "setup.iss"):
        payload[name] = (ROOT / "installer/windows" / name).read_bytes()
    out = out.expanduser().absolute()
    if any(parent.is_symlink() for parent in (out, *out.parents)) or out.exists():
        raise ValueError("Output must be a new directory without symlink components")
    if not out.parent.is_dir():
        raise ValueError("Output parent must already exist")
    out.mkdir(mode=0o700)
    for name, body in sorted(payload.items()):
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    report = {
        **{key: value for key, value in manifest.items() if key != "files"},
        "runtime_files": len(files),
        "offline_wheels": 38,
        "python_url": PYTHON_URL,
        "native_acceptance": False,
        "stage_files": {name: digest(body) for name, body in sorted(payload.items())},
    }
    (out / "build-plan.json").write_bytes(canonical(report) + b"\n")
    return report


def compile_setup(stage_dir: Path, compiler: Path):
    if os.name != "nt":
        raise ValueError("Inno compilation requires a native Windows environment")
    result = subprocess.run(
        [str(compiler.absolute()), "/Q", str((stage_dir / "setup.iss").absolute())],
        cwd=stage_dir,
        check=True,
        capture_output=True,
        text=True,
        timeout=900,
    )
    asset = stage_dir / "output" / f"KiraBridge-{VERSION}-Windows-x64-Setup.exe"
    raw = asset.read_bytes()
    if raw[:2] != b"MZ":
        raise ValueError("Compiler did not produce a PE Setup executable")
    report = {
        "asset": asset.name,
        "sha256": digest(raw),
        "bytes": len(raw),
        "compile_exit": result.returncode,
        "compiler_sha256": digest(compiler.read_bytes()),
        "native_installer_acceptance": False,
    }
    (asset.parent / "compiler-log.txt").write_text(
        (result.stdout + result.stderr)[-65536:], encoding="utf-8"
    )
    (asset.parent / "build-result.json").write_bytes(canonical(report) + b"\n")
    (asset.parent / "SHA256SUMS").write_text(
        f"{report['sha256']}  {asset.name}\n", encoding="ascii"
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--python-embed", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--iscc", type=Path, help="Compile the staged payload on Windows")
    args = parser.parse_args(argv)
    report = stage(args.kit, args.python_embed, args.out_dir)
    if args.iscc:
        report["compiler"] = compile_setup(args.out_dir, args.iscc)
    print(
        json.dumps({key: value for key, value in report.items() if key != "stage_files"}, indent=2)
    )


if __name__ == "__main__":
    main()
