"""Build the local macOS companion window; configuration and credentials remain private."""

import argparse
import hashlib
import platform
import plistlib
import re
import subprocess
import sys
import tomllib
from pathlib import Path


def build(destination=None):
    if sys.platform != "darwin":
        raise RuntimeError("The native companion is for macOS; other systems use the browser")
    root = Path(__file__).resolve().parents[1]
    bundle = Path(destination) if destination else Path.home() / "Applications/KiraBridge.app"
    if bundle.is_symlink() or bundle.exists():
        raise RuntimeError("Use a new app destination; existing installations are preserved")
    if subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True):
        raise RuntimeError("Commit all source changes before building the companion")
    commit = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    numeric_version = re.fullmatch(r"(\d+\.\d+\.\d+)(?:(?:a|b|rc)\d+)?", version)
    if not numeric_version or not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise RuntimeError("Cannot identify companion source version")
    source = root / "integrations/desktop/main.swift"
    native_sources = [
        source,
        root / "integrations/desktop/SystemBridge.swift",
        root / "integrations/desktop/SystemControl.swift",
        root / "integrations/desktop/SystemServices.swift",
        root / "integrations/desktop/SystemKeyboard.swift",
        root / "integrations/desktop/SystemShortcuts.swift",
        root / "integrations/desktop/SystemSpecialKeys.swift",
    ]
    binary = bundle / "Contents/MacOS/KiraBridge"
    binary.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "/usr/bin/xcrun",
            "swiftc",
            "-swift-version",
            "5",
            "-target",
            f"{platform.machine()}-apple-macosx12.0",
            "-O",
            "-framework",
            "Cocoa",
            "-framework",
            "WebKit",
            "-framework",
            "ScreenCaptureKit",
            "-framework",
            "UserNotifications",
            "-framework",
            "ImageIO",
            "-framework",
            "UniformTypeIdentifiers",
            "-framework",
            "ApplicationServices",
            "-framework",
            "CryptoKit",
            "-framework",
            "SystemConfiguration",
            "-framework",
            "Security",
            "-framework",
            "CoreAudio",
            "-framework",
            "IOKit",
            *map(str, native_sources),
            "-o",
            str(binary),
        ],
        check=True,
        timeout=180,
    )
    binary.chmod(0o755)
    (bundle / "Contents/Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleExecutable": "KiraBridge",
                "CFBundleIdentifier": "de.netzwerkpunkt.kirabridge",
                "CFBundleName": "KiraBridge",
                "CFBundleDisplayName": "KiraBridge",
                "CFBundleVersion": "1",
                "CFBundleShortVersionString": numeric_version.group(1),
                "CFBundleGetInfoString": f"KiraBridge {version} ({commit[:12]})",
                "KiraBridgeVersion": version,
                "KiraBridgeSourceCommit": commit,
                "KiraBridgeCompanionSourceSHA256": hashlib.sha256(
                    b"".join(
                        path.name.encode() + b"\0" + path.read_bytes() for path in native_sources
                    )
                ).hexdigest(),
                "KiraBridgeSystemProtocol": 1,
                "KiraBridgeKeyboardProtocol": 1,
                "CFBundlePackageType": "APPL",
                "NSHighResolutionCapable": True,
                "LSMinimumSystemVersion": "12.0",
            }
        )
    )
    subprocess.run(
        ["/usr/bin/codesign", "--force", "--sign", "-", str(bundle)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    # A private build directory may use umask077. The runtime manifest still
    # needs deterministic signed app member modes on every operator machine.
    for member in bundle.rglob("*"):
        if member.is_symlink():
            raise RuntimeError("Unexpected symlink in the generated companion")
        if member.is_file():
            member.chmod(0o755 if member == binary else 0o644)
    subprocess.run(
        ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(bundle)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return str(bundle)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, help="New .app destination; existing apps are preserved"
    )
    print(build(parser.parse_args().out))
