"""Package the existing installer app as a conventional drag-to-Applications DMG.

The app inside is the exact app made by scripts/build_installer_app.py, renamed
KiraBridge.app. Its first launch runs the existing, manifest-verified installer
(installer/install.py: visible Terminal, backup, idle and integrity gates, rollback,
preserved configuration/credentials/data). This script builds a disk image only:
it never installs, publishes, notarizes or touches running services.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOLUME = "KiraBridge"
IDENTIFIER = "de.netzwerkpunkt.kirabridge.installer"


def verify_source_app(app: Path, commit: str) -> dict:
    """Refuse anything but a complete, ad-hoc-signed installer app built from `commit`."""
    if app.is_symlink() or not app.is_dir() or app.suffix != ".app":
        raise RuntimeError("A regular installer .app built by build_installer_app.py is required")
    for member in app.rglob("*"):
        if member.is_symlink():
            raise RuntimeError("Installer app symlink refused")
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    if (
        info.get("CFBundleIdentifier") != IDENTIFIER
        or info.get("KiraBridgeSourceCommit") != commit
        or not re.fullmatch(r"[a-f0-9]{40}", commit)
    ):
        raise RuntimeError("Installer app is not built from the current source commit")
    binary = app / "Contents/MacOS/KiraBridgeInstaller"
    # Verifies the signature and every packaged file hash; installs nothing.
    result = subprocess.run(
        [str(binary), "--verify-package"], check=True, capture_output=True, text=True, timeout=60
    )
    receipt = json.loads(result.stdout)
    if receipt.get("verified") is not True or receipt.get("installation_performed") is not False:
        raise RuntimeError("Installer app verification failed")
    return info


def build(destination: Path, app: Path) -> dict:
    if sys.platform != "darwin":
        raise RuntimeError("Build the DMG on macOS")
    if destination.suffix != ".dmg" or destination.is_symlink() or destination.exists():
        raise RuntimeError("Use a new .dmg destination; existing artifacts are preserved")
    sums = destination.with_name(destination.name + ".sha256")
    if sums.is_symlink() or sums.exists():
        raise RuntimeError("Checksum file already exists; existing artifacts are preserved")
    if subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"], text=True):
        raise RuntimeError("Commit all source changes before building the DMG")
    commit = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    info = verify_source_app(app, commit)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kirabridge-dmg-") as scratch:
        stage = Path(scratch) / VOLUME
        stage.mkdir(mode=0o755)
        # ditto keeps the ad-hoc signature, modes and bundle layout byte-exact.
        subprocess.run(
            ["/usr/bin/ditto", str(app), str(stage / "KiraBridge.app")], check=True, timeout=120
        )
        (stage / "Applications").symlink_to("/Applications")  # the drag target
        # The copy must still be the same verified package after staging.
        verify_source_app(stage / "KiraBridge.app", commit)
        subprocess.run(
            [
                "/usr/bin/hdiutil",
                "create",
                "-volname",
                VOLUME,
                "-srcfolder",
                str(stage),
                "-fs",
                "HFS+",
                "-format",
                "UDZO",
                "-ov",
                str(destination),
            ],
            check=True,
            capture_output=True,
            timeout=300,
        )
    subprocess.run(
        ["/usr/bin/hdiutil", "verify", str(destination)],
        check=True,
        capture_output=True,
        timeout=120,
    )
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    with sums.open("x") as handle:  # exclusive create; never overwrites
        handle.write(digest + "  " + destination.name + "\n")
    return {
        "dmg": str(destination),
        "sha256": digest,
        "sha256_file": str(sums),
        "version": info["KiraBridgeVersion"],
        "source_commit": commit,
        "app_signing": "ad-hoc",
        "dmg_signed": False,
        "notarized": False,
        "installation_performed": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--app", type=Path, required=True, help="Installer .app from build_installer_app.py"
    )
    parser.add_argument("--out", type=Path, required=True, help="New .dmg destination")
    args = parser.parse_args()
    print(json.dumps(build(args.out.absolute(), args.app.absolute()), indent=2))
