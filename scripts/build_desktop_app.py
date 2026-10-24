"""Build the local macOS companion window; configuration and credentials remain private."""

import plistlib
import subprocess
import sys
from pathlib import Path


def build(destination=None):
    if sys.platform != "darwin":
        raise RuntimeError("The native companion is for macOS; other systems use the browser")
    root = Path(__file__).resolve().parents[1]
    bundle = destination or Path.home() / "Applications/KiraBridge.app"
    binary = bundle / "Contents/MacOS/KiraBridge"
    binary.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "/usr/bin/xcrun",
            "swiftc",
            "-O",
            "-framework",
            "Cocoa",
            "-framework",
            "WebKit",
            str(root / "integrations/desktop/main.swift"),
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
                "CFBundleShortVersionString": "0.8.0",
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
    return str(bundle)


if __name__ == "__main__":
    print(build())
