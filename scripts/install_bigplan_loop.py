#!/usr/bin/env python3
"""Install only the dedicated coordinator launch agent; never touches product services."""

import argparse
import json
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path

LABEL = "de.threaddesk.bigplan-coordinator"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    profile = args.profile.resolve(strict=True)
    info = json.loads(profile.read_text())
    marker = Path(info["state_dir"], "coordinator-profile.json")
    expected = {
        "instance": info["instance"],
        "cwd": str(Path(info["cwd"]).resolve()),
        "workspace": str(Path(info["workspace"]).resolve()),
    }
    if not marker.is_file() or json.loads(marker.read_text()) != expected:
        raise RuntimeError("Validate the matching dedicated profile before installation")
    executable = Path.home() / ".local/bin/bigplan-loop"
    destination = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    if any(p.exists() or p.is_symlink() for p in (executable, destination)):
        raise RuntimeError("Existing launcher or launch agent preserved")
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text(
        "#!/bin/sh\nexport PYTHONPATH="
        + shlex.quote(str(source / "src"))
        + "\nexec "
        + shlex.quote(sys.executable)
        + " "
        + shlex.quote(str(source / "scripts/bigplan_loop.py"))
        + " --profile "
        + shlex.quote(str(profile))
        + ' "$@"\n'
    )
    executable.chmod(0o755)
    logs = Path.home() / ".local/state/bigplan-coordinator"
    logs.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(
        plistlib.dumps(
            {
                "Label": LABEL,
                "ProgramArguments": [str(executable), "serve"],
                "RunAtLoad": True,
                "KeepAlive": True,
                "ThrottleInterval": 60,
                "StandardOutPath": str(logs / "stdout.log"),
                "StandardErrorPath": str(logs / "stderr.log"),
            }
        )
    )
    destination.chmod(0o600)
    subprocess.run(
        ["/bin/launchctl", "bootstrap", f"gui/{__import__('os').getuid()}", str(destination)],
        check=True,
    )
    print("Installed dedicated coordinator only:", LABEL)


if __name__ == "__main__":
    main()
