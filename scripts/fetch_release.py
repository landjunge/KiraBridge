"""Download the GitHub-built macOS package of a main commit, verify SHA256SUMS, print its path.

Usage: python3 scripts/fetch_release.py [--sha COMMIT] [--out DIR]
Default commit: origin/main. Needs `gh` (authenticated). Waits for a running build.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = "landjunge/KiraBridge"
WORKFLOW = "macos-build-main.yml"


def run(*cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def find_run(sha, wait):
    deadline = time.time() + wait
    while True:
        rows = json.loads(
            run(
                "gh",
                "run",
                "list",
                "-R",
                REPO,
                "-w",
                WORKFLOW,
                "-c",
                sha,
                "--json",
                "databaseId,status,conclusion",
            )
        )
        for row in rows:
            if row["conclusion"] == "success":
                return str(row["databaseId"])
        if not any(row["status"] != "completed" for row in rows):
            raise SystemExit(f"No successful {WORKFLOW} run for {sha}: {rows or 'none yet'}")
        if time.time() > deadline:
            raise SystemExit(f"Build for {sha} still running; retry later")
        time.sleep(20)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sha", help="full commit SHA (default: origin/main)")
    parser.add_argument("--out", type=Path, default=Path.home() / "kirabridge-downloads")
    parser.add_argument(
        "--wait", type=int, default=1800, help="seconds to wait for a running build"
    )
    args = parser.parse_args()
    sha = args.sha or json.loads(run("gh", "api", f"repos/{REPO}/commits/main"))["sha"]
    target = args.out / sha
    target.mkdir(parents=True, exist_ok=True)
    run(
        "gh",
        "run",
        "download",
        find_run(sha, args.wait),
        "-R",
        REPO,
        "-n",
        f"KiraBridge-macos-intel-{sha}",
        "-D",
        str(target),
    )
    for line in (target / "SHA256SUMS").read_text().splitlines():
        digest, _, name = line.partition("  ")
        if hashlib.sha256((target / name.strip()).read_bytes()).hexdigest() != digest:
            raise SystemExit(f"SHA256 mismatch: {name}")
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
