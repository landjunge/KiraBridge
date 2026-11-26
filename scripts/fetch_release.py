"""Download the GitHub-built macOS package of a main commit, verify SHA256SUMS, print its path.

Usage: python3 scripts/fetch_release.py [--sha COMMIT] [--out DIR] [--wait [SECONDS]]
Default commit: origin/main. Needs `gh` (authenticated).
--wait [SECONDS] waits for a queued or running build (bare flag: 900 s).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = "landjunge/KiraBridge"
WORKFLOW = "macos-build-main.yml"


def run(*cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def find_run(sha, wait):
    """Return the successful run id for sha; with wait seconds, wait for a queued/running one."""
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
        active = [row for row in rows if row["status"] != "completed"]
        if active and time.time() < deadline:
            # blocks until that run ends; the loop then re-reads its conclusion
            subprocess.run(
                [
                    "gh",
                    "run",
                    "watch",
                    str(active[0]["databaseId"]),
                    "-R",
                    REPO,
                    "--interval",
                    "15",
                ],
                capture_output=True,
                text=True,
            )
            continue
        if not rows and wait and time.time() < deadline:
            time.sleep(10)  # run not registered yet
            continue
        raise SystemExit(f"No successful {WORKFLOW} run for {sha}: {rows or 'none yet'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sha", help="full commit SHA (default: origin/main)")
    parser.add_argument("--out", type=Path, default=Path.home() / "kirabridge-downloads")
    parser.add_argument(
        "--wait",
        nargs="?",
        type=int,
        const=900,
        default=0,
        metavar="SECONDS",
        help="wait for a queued/running build (bare flag: 900 s)",
    )
    args = parser.parse_args()
    sha = args.sha or json.loads(run("gh", "api", f"repos/{REPO}/commits/main"))["sha"]
    run_id = find_run(sha, args.wait)  # nothing is created before a run exists
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / sha
    with tempfile.TemporaryDirectory(dir=args.out) as scratch:
        part = Path(scratch) / "pkg"
        run(
            "gh",
            "run",
            "download",
            run_id,
            "-R",
            REPO,
            "-n",
            f"KiraBridge-macos-intel-{sha}",
            "-D",
            str(part),
        )
        for line in (part / "SHA256SUMS").read_text().splitlines():
            digest, _, name = line.partition("  ")
            if hashlib.sha256((part / name.strip()).read_bytes()).hexdigest() != digest:
                raise SystemExit(f"SHA256 mismatch: {name}")
        if target.exists():
            shutil.rmtree(target)
        part.rename(target)  # only a verified package appears at the final path
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
