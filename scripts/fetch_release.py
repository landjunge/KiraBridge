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
POLL = 10


def run(*cmd):
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(f"{' '.join(cmd[:3])} failed: {done.stderr.strip()[:300]}")
    return done.stdout.strip()


def say(message):
    print(message, file=sys.stderr, flush=True)


def find_run(sha, wait):
    """Return the successful run id for sha; with wait seconds, poll queued/running runs."""
    deadline = time.time() + wait
    last = None
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
        if not active and rows:
            done = ", ".join(f"{r['databaseId']}={r['conclusion']}" for r in rows)
            raise SystemExit(f"Build for {sha} did not succeed: {done}")
        if time.time() >= deadline:
            state = f"run {active[0]['databaseId']} {active[0]['status']}" if active else "no run"
            raise SystemExit(f"Timeout for {sha}: {state} (wait {wait} s)")
        state = f"run {active[0]['databaseId']} {active[0]['status']}" if active else "no run yet"
        if state != last:
            say(f"{sha[:7]}: {state}, polling every {POLL} s")
            last = state
        time.sleep(POLL)


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
    # `gh run list --commit` needs the full SHA; resolve short ones (or main) first.
    sha = args.sha or "main"
    if len(sha) != 40:
        sha = json.loads(run("gh", "api", f"repos/{REPO}/commits/{sha}"))["sha"]
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
