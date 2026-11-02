"""Build a signed native installer launcher around the exact existing macOS release.

The embedded release still uses installer/install.py, including its visibility,
backup, idle, integrity and rollback gates. This builder never installs anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import plistlib
import re
import stat
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def release_files(archive: Path, commit: str, version: str, architecture: str):
    """Validate all archive paths and hashes before creating the destination app."""
    if archive.is_symlink() or not archive.is_file():
        raise RuntimeError("A regular exact release archive is required")
    files, modes, total = {}, {}, 0
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            path = PurePosixPath(member.name)
            if (
                not member.isfile()
                or str(path) != member.name
                or path.is_absolute()
                or len(path.parts) < 2
                or path.parts[0] != "KiraBridge"
                or any(part in {".", ".."} for part in path.parts)
                or member.size > 64 * 1024 * 1024
                or len(files) >= 20000
            ):
                raise RuntimeError("Unsafe release archive member")
            name = str(PurePosixPath(*path.parts[1:]))
            if name in files or member.mode not in {0o644, 0o755}:
                raise RuntimeError("Duplicate or unsafe release archive member")
            total += member.size
            if total > 256 * 1024 * 1024:
                raise RuntimeError("Release archive exceeds installer limits")
            with source.extractfile(member) as handle:
                files[name] = handle.read(member.size + 1)
            if len(files[name]) != member.size:
                raise RuntimeError("Incomplete release member")
            modes[name] = member.mode
    manifest = json.loads(files.get("release.json", b"{}"))
    if (
        manifest.get("source_commit") != commit
        or manifest.get("commit") != commit
        or manifest.get("version") != version
        or manifest.get("platforms") != ["Darwin-" + architecture]
        or manifest.get("native_app_required") is not True
        or not isinstance(manifest.get("files"), dict)
        or set(files) != set(manifest["files"]) | {"release.json"}
    ):
        raise RuntimeError("Release identity or complete file inventory differs")
    for name, expected in manifest["files"].items():
        if (
            not isinstance(expected, str)
            or not re.fullmatch(r"[a-f0-9]{64}", expected)
            or hashlib.sha256(files[name]).hexdigest() != expected
        ):
            raise RuntimeError("Release member checksum differs: " + name)
    native = manifest.get("native_app", {})
    binary = "native/KiraBridge.app/Contents/MacOS/KiraBridge"
    metadata = plistlib.loads(files.get("native/KiraBridge.app/Contents/Info.plist", b""))
    if (
        native.get("source_commit") != commit
        or native.get("architecture") != architecture
        or hashlib.sha256(files.get(binary, b"")).hexdigest() != native.get("binary_sha256")
        or modes.get(binary) != 0o755
        or metadata.get("KiraBridgeSourceCommit") != commit
        or metadata.get("KiraBridgeVersion") != version
        or metadata.get("CFBundleExecutable") != "KiraBridge"
        or metadata.get("CFBundleIdentifier") != "de.netzwerkpunkt.kirabridge"
    ):
        raise RuntimeError("Native app identity differs")
    for name in ("installer/install.py", "installer/visible_terminal.py", "install.sh"):
        if name not in files:
            raise RuntimeError("Existing installer is missing")
    return files, modes


def build(destination: Path, archive: Path):
    if destination.is_symlink() or destination.exists():
        raise RuntimeError("Use a new installer app destination; existing artifacts are preserved")
    if sys.platform != "darwin" or platform.machine() not in {"x86_64", "arm64"}:
        raise RuntimeError("Build this installer on its target macOS architecture")
    if subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"], text=True):
        raise RuntimeError("Commit all source changes before building the installer")
    commit = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise RuntimeError("Invalid exact source commit")
    files, modes = release_files(archive, commit, version, platform.machine())
    resources = destination / "Contents/Resources"
    runtime = resources / "Runtime"
    runtime.mkdir(parents=True)
    for name, data in files.items():
        target = runtime / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(modes[name])
    command = resources / "KiraBridge-Installieren.command"
    command.write_bytes((ROOT / "integrations/installer/install.command").read_bytes())
    command.chmod(0o755)
    envelope = {
        "schema": "kirabridge.installer-app.v1",
        "source_commit": commit,
        "version": version,
        "architecture": platform.machine(),
        "runtime_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "files": {
            **{"Runtime/" + name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
            command.name: hashlib.sha256(command.read_bytes()).hexdigest(),
        },
    }
    receipt = resources / "installer-package.json"
    receipt.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n")
    numeric = re.fullmatch(r"(\d+\.\d+\.\d+)(?:(?:a|b|rc)\d+)?", version)
    if not numeric:
        raise RuntimeError("Invalid package version")
    (destination / "Contents/Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleExecutable": "KiraBridgeInstaller",
                "CFBundleIdentifier": "de.netzwerkpunkt.kirabridge.installer",
                "CFBundleName": "KiraBridge installieren",
                "CFBundleDisplayName": "KiraBridge installieren",
                "CFBundlePackageType": "APPL",
                "CFBundleVersion": "1",
                "CFBundleShortVersionString": numeric.group(1),
                "NSHighResolutionCapable": True,
                "LSMinimumSystemVersion": "12.0",
                "KiraBridgeVersion": version,
                "KiraBridgeSourceCommit": commit,
                "KiraBridgePackageSHA256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
            }
        )
    )
    binary = destination / "Contents/MacOS/KiraBridgeInstaller"
    binary.parent.mkdir()
    subprocess.run(
        [
            "/usr/bin/xcrun",
            "swiftc",
            "-swift-version",
            "5",
            "-O",
            "-target",
            platform.machine() + "-apple-macosx12.0",
            "-framework",
            "Cocoa",
            "-framework",
            "CryptoKit",
            str(ROOT / "integrations/installer/main.swift"),
            "-o",
            str(binary),
        ],
        check=True,
        timeout=120,
    )
    binary.chmod(0o755)
    for member in destination.rglob("*"):
        if member.is_symlink():
            raise RuntimeError("Installer app symlink refused")
        if member.is_dir():
            member.chmod(0o755)
        elif member.is_file():
            member.chmod(0o755 if stat.S_IMODE(member.stat().st_mode) & 0o111 else 0o644)
    subprocess.run(
        [
            "/usr/bin/codesign",
            "--force",
            "--sign",
            "-",
            str(destination),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    subprocess.run(
        [
            "/usr/bin/codesign",
            "--verify",
            "--deep",
            "--strict",
            str(destination),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    verified = subprocess.run(
        [str(binary), "--verify-package"], check=True, capture_output=True, text=True, timeout=30
    )
    return json.loads(verified.stdout)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="New .app destination")
    parser.add_argument("--archive", type=Path, required=True, help="Exact KiraBridge-macos.tar.gz")
    args = parser.parse_args()
    print(json.dumps(build(args.out.absolute(), args.archive.absolute()), indent=2))
