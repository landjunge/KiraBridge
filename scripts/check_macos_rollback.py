#!/usr/bin/env python3
"""Focused real macOS rollback probe; only an owned temporary launchd test service.

Explicit trusted prepared runtime inputs are copied before use. No package build,
GUI actions, clipboard access, production paths or full test suite are involved.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace


def service_snapshot(service):
    result = subprocess.run(
        ["launchctl", "print", service], capture_output=True, text=True, timeout=3
    )
    observation = {"at": time.time(), "launchctl_returncode": result.returncode}
    # Never retain raw launchctl environment, arguments, or unfiltered output.
    for key in ("state", "pid", "runs", "last exit code", "last terminating signal", "spawn type"):
        match = re.search(r"^\s*" + re.escape(key) + r" = (.+)$", result.stdout, re.MULTILINE)
        if match:
            observation[key] = match.group(1)
    return observation


def hashes(paths, root):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    }


def probe(root, previous, candidate, expected_commit, *, lifecycle=False):
    if platform.system() != "Darwin" or os.getuid() == 0:
        raise SystemExit("A normal macOS user and its GUI launchd domain are required")
    root, previous, candidate = (path.resolve() for path in (root, previous, candidate))
    repository = Path(__file__).resolve().parents[1]
    if not root.is_relative_to(repository / "dist") or root.exists():
        raise SystemExit("Root must be a new isolated directory below this checkout's dist")
    old_manifest = json.loads((previous / "release.json").read_text())
    new_manifest = json.loads((candidate / "release.json").read_text())
    if old_manifest.get("version") != "0.8.0rc14" or old_manifest.get("commit") != (
        "c21d37ebdd42f03c85df1e89cd3c6969a6362e4c"
    ):
        raise SystemExit("The explicitly supplied previous runtime must be verified RC14")
    if (
        not re.fullmatch(r"[a-f0-9]{40}", expected_commit)
        or new_manifest.get("commit") != expected_commit
    ):
        raise SystemExit("Candidate runtime must match its explicitly pinned commit")
    label = "com.kirabridge.test." + root.name.lower().replace("_", "-")
    if not re.fullmatch(r"com\.kirabridge\.test\.[a-z0-9-]{8,64}", label):
        raise SystemExit("Choose a unique test directory name of 8..64 lowercase ASCII characters")
    service = f"gui/{os.getuid()}/{label}"
    if service_snapshot(service)["launchctl_returncode"] != 113:
        raise SystemExit("Exact test service absence must be positively confirmed before setup")
    root.mkdir(mode=0o700, parents=True)
    old, new = root / "previous", root / "candidate"
    shutil.copytree(previous, old, symlinks=True)
    shutil.copytree(candidate, new, symlinks=True)
    spec = importlib.util.spec_from_file_location(
        "rollback_installer", repository / "installer/install.py"
    )
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    installer.LABEL = label
    args = SimpleNamespace(
        prefix=root / "install",
        config=root / "config/config.toml",
        launcher=root / "bin/kirabridge",
        plist=root / "service.plist",
        service="launchd",
        full_access=False,
        workspace=root / "workspace",
    )
    installer.private_dir(args.prefix)
    installer.fresh_config(args, new)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    installer.atomic(args.config, args.config.read_text().replace("port = 8765", f"port = {port}"))
    preserved = (args.config, args.config.parent / "credentials.json")
    initial = hashes(preserved, root)
    evidence = {
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "source_commit": expected_commit,
        "label": label,
        "lifecycle": lifecycle,
        "scope": "owned isolated launchd fixture only; no GUI or production service access",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "installer_sha256": hashlib.sha256(
            (repository / "installer/install.py").read_bytes()
        ).hexdigest(),
        "checks": [],
        "passed": False,
    }

    def clients():
        observation = service_snapshot(service)
        for release in (old, new):
            try:
                value = installer.cli(release, args.config, "status", timeout=8)
                observation[release.name + "_client"] = {
                    "version": value.get("version"),
                    "dispatcher_active": value.get("dispatcher_active"),
                    "runtime_pid": value.get("runtime", {}).get("pid"),
                }
            except Exception as exc:
                observation[release.name + "_client"] = {"error_type": type(exc).__name__}
        return observation

    def fresh(expected, prior_pid=None):
        deadline = time.monotonic() + 30
        observations = []
        while time.monotonic() < deadline:
            observations.append(service_snapshot(service))
            try:
                health = installer.cli(new, args.config, "status", timeout=8)
                if (
                    health.get("version") == expected
                    and health.get("dispatcher_active")
                    and (prior_pid is None or health.get("runtime", {}).get("pid") != prior_pid)
                ):
                    return health["runtime"]["pid"], observations
            except Exception:
                pass
            time.sleep(0.25)
        raise RuntimeError("Isolated lifecycle readiness not confirmed within 30 seconds")

    stopped = threading.Event()
    samples = []

    def monitor():
        while not stopped.is_set() and len(samples) < 160:
            try:
                samples.append(service_snapshot(service))
            except Exception as exc:
                samples.append({"at": time.time(), "error_type": type(exc).__name__})
            stopped.wait(0.25)

    monitor_thread = None
    try:
        installer.activate(args, old)
        evidence["checks"].append("isolated RC14 starts")
        installer.activate(args, new)
        evidence["checks"].append("isolated candidate starts")
        if lifecycle:
            pid, _ = fresh(new_manifest["version"])
            subprocess.run(
                ["launchctl", "kickstart", "-k", service],
                check=True,
                capture_output=True,
                timeout=20,
            )
            restarted, observations = fresh(new_manifest["version"], pid)
            evidence["kickstart"] = {
                "old_pid": pid,
                "new_pid": restarted,
                "observations": observations,
            }
            subprocess.run(
                ["launchctl", "kill", "SIGKILL", service],
                check=True,
                capture_output=True,
                timeout=20,
            )
            recovered, observations = fresh(new_manifest["version"], restarted)
            evidence["keepalive"] = {
                "old_pid": restarted,
                "new_pid": recovered,
                "observations": observations,
            }
            evidence["checks"].append(
                "kickstart and SIGKILL/KeepAlive each prove a different healthy PID"
            )
        evidence["before_rollback"] = clients()
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
        try:
            installer.rollback(args)
            evidence["checks"].append("rollback readiness passed")
        finally:
            stopped.set()
            monitor_thread.join(timeout=4)
            evidence["readiness_launchd_observations"] = samples
            evidence["after_rollback_before_cleanup"] = clients()
        result = evidence["after_rollback_before_cleanup"]
        assert all(
            result[name + "_client"].get("version") == "0.8.0rc14"
            for name in ("previous", "candidate")
        )
        assert all(
            result[name + "_client"].get("dispatcher_active") is True
            for name in ("previous", "candidate")
        )
        evidence["passed"] = True
    except BaseException as exc:
        evidence["error_type"] = type(exc).__name__
        raise
    finally:
        stopped.set()
        if monitor_thread:
            monitor_thread.join(timeout=4)
        evidence["config_credentials_preserved"] = initial == hashes(preserved, root)
        try:
            cleanup_spec = importlib.util.spec_from_file_location(
                "rollback_cleanup", repository / "scripts/accept_macos_release.py"
            )
            cleanup = importlib.util.module_from_spec(cleanup_spec)
            cleanup_spec.loader.exec_module(cleanup)
            evidence.update(cleanup.stop_test_service(service))
        except BaseException as exc:
            evidence["passed"] = False
            evidence["cleanup_error_type"] = type(exc).__name__
            raise
        finally:
            if not evidence["config_credentials_preserved"]:
                evidence["passed"] = False
            (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--previous-release", type=Path, required=True)
    parser.add_argument("--candidate-release", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--lifecycle", action="store_true")
    options = parser.parse_args()
    probe(
        options.root,
        options.previous_release,
        options.candidate_release,
        options.expected_commit,
        lifecycle=options.lifecycle,
    )
