"""Optional real AX timing on one owned nonactivating fixture, with existing rights only."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import plistlib
import shutil
import statistics
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


def summary(values):
    ordered = sorted(values)
    return {
        "p50_ms": statistics.median(values),
        "p95_ms": ordered[(len(values) * 95 + 99) // 100 - 1],
    }


@contextmanager
def private_fixture(result):
    folder = Path(tempfile.mkdtemp(prefix="kirabridge-rc32-owned-ax-"))
    try:
        yield folder
    finally:
        if result.get("fixture_directory_preserved") != str(folder):
            shutil.rmtree(folder)


def run(output, rounds):
    if output.exists():
        raise RuntimeError("Use a new evidence output path; existing measurements are preserved")
    root = Path(__file__).resolve().parents[1]
    sources = [root / "tests/fixtures/desktop_bootstrap/AccessibilityTimingHarness.swift"]
    sources += [
        root / "integrations/desktop" / name
        for name in (
            "SystemControl.swift",
            "SystemBridge.swift",
            "SystemServices.swift",
            "SystemKeyboard.swift",
            "SystemShortcuts.swift",
            "SystemSpecialKeys.swift",
        )
    ]
    before = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    result = {
        "schema": "kirabridge.rc32.owned-ax-timing.v1",
        "source_sha256": before,
        "scope": "real native AX reads of one owned background fixture; no Cloud/Voice/input",
        "permission_requested": False,
        "input_posts": 0,
        "window_created": False,
    }
    with private_fixture(result) as folder:
        app = folder / "OwnedAXTiming.app"
        binary = app / "Contents/MacOS/OwnedAXTiming"
        binary.parent.mkdir(parents=True)
        command = [
            "xcrun",
            "swiftc",
            "-O",
            "-swift-version",
            "5",
            "-parse-as-library",
            "-target",
            f"{platform.machine()}-apple-macosx12.0",
            *map(str, sources),
            "-o",
            str(binary),
        ]
        for name in (
            "Cocoa",
            "ApplicationServices",
            "CryptoKit",
            "ScreenCaptureKit",
            "UserNotifications",
            "ImageIO",
            "UniformTypeIdentifiers",
            "SystemConfiguration",
            "Security",
            "CoreAudio",
            "IOKit",
        ):
            command += ["-framework", name]
        compiled = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if compiled.returncode:
            raise RuntimeError(compiled.stderr)
        (app / "Contents/Info.plist").write_bytes(
            plistlib.dumps(
                {
                    "CFBundleExecutable": "OwnedAXTiming",
                    "CFBundleIdentifier": "de.netzwerkpunkt.kirabridge.owned-ax-timing",
                    "CFBundlePackageType": "APPL",
                    "CFBundleVersion": "1",
                    "LSUIElement": True,
                }
            )
        )
        subprocess.run(
            ["codesign", "--force", "--sign", "-", str(app)], check=True, capture_output=True
        )
        result["binary_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
        probe = json.loads(subprocess.check_output([str(binary), "--probe"], text=True, timeout=10))
        result["initial_probe"] = probe
        launched = None
        target = None
        try:
            if not probe["trusted"]:
                result.update(status="not_run", reason="existing_accessibility_grant_unavailable")
            else:
                if probe["owned_other_pids"]:
                    raise RuntimeError("An owned fixture is already running")
                if any(
                    "com.apple.quarantine"
                    in subprocess.check_output(
                        ["/usr/bin/xattr", str(path)], text=True, timeout=10
                    ).splitlines()
                    for path in (app, binary)
                ):
                    raise RuntimeError(
                        "Quarantined fixture must not be launched during this benchmark"
                    )
                ready = folder / "ready.json"
                result.update(window_creation_attempted=True, window_created=None)
                launch = subprocess.run(
                    [str(binary), "--launch", str(ready)],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                result["launch_stderr"] = launch.stderr[-4096:]
                result["launch_returncode"] = launch.returncode
                assert launch.returncode == 0
                launched = json.loads(launch.stdout)
                result["launch_result"] = launched
                assert launched.get("launched"), launched
                assert not launched["active"] and launched["foreground_pid"] != launched["pid"]
                deadline = time.monotonic() + 10
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                target = json.loads(ready.read_text())
                assert (
                    target["pid"] == launched["pid"]
                    and target["started_at"] == launched["started_at"]
                    and target["window_count"] == 1
                    and not target["active"]
                )
                assert target["foreground_pid"] != launched["pid"]
                result.update(window_created=True, target=target)
                measured = subprocess.run(
                    [
                        str(binary),
                        "--measure",
                        str(launched["pid"]),
                        str(target["started_at"]),
                        str(rounds),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                assert measured.returncode == 0, measured.stderr
                result["measurement"] = json.loads(measured.stdout)
                result["status"] = "passed" if result["measurement"].get("passed") else "failed"
                if result["status"] == "passed":
                    assert result["measurement"]["nodes_per_round"] == 12
                    assert result["measurement"]["fixture_active"] is False
                    assert result["measurement"]["foreground_pid"] != launched["pid"]
                    result["summary"] = {
                        mode: summary(
                            [
                                s["timings"][mode]["wall_ms"]
                                for s in result["measurement"]["samples"]
                            ]
                        )
                        for mode in ("individual", "batched")
                    }
        except Exception as error:
            result.update(status="failed", error_type=type(error).__name__, error=str(error))
        finally:
            try:
                family = json.loads(
                    subprocess.check_output([str(binary), "--owned-status"], text=True, timeout=10)
                )
                # The unique private bundle had no other instance before its
                # one launch. Reconcile an uncertain launch without repeating it.
                assert len(family["applications"]) <= 1
                result["cleanup_inventory"] = family
                for owned in family["applications"]:
                    assert owned["started_at"] is not None
                    if launched and launched.get("launched"):
                        assert (
                            owned["pid"] == launched["pid"]
                            and owned["started_at"] == launched["started_at"]
                        )
                    stopped = json.loads(
                        subprocess.check_output(
                            [str(binary), "--stop", str(owned["pid"]), str(owned["started_at"])],
                            text=True,
                            timeout=10,
                        )
                    )
                    assert "error" not in stopped
                    result["owned_stop"] = stopped
                deadline = time.monotonic() + 3
                while True:
                    absent = json.loads(
                        subprocess.check_output(
                            [str(binary), "--owned-status"], text=True, timeout=10
                        )
                    )
                    if not absent["applications"] or time.monotonic() >= deadline:
                        break
                    time.sleep(0.02)
                assert not absent["applications"]
                result["independent_absence"] = absent
                uncertain_launch = result.get("window_creation_attempted") and not (
                    launched and launched.get("launched")
                )
                if uncertain_launch and not family["applications"]:
                    result.update(
                        status="cleanup_unknown",
                        pending_launch=True,
                        fixture_directory_preserved=str(folder),
                    )
                else:
                    result["owned_process_terminated"] = True
            except Exception as error:
                result.update(
                    status="cleanup_unknown",
                    cleanup_error=str(error),
                    fixture_directory_preserved=str(folder),
                )
            result["source_unchanged"] = before == {
                str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sources
            }
            if not result["source_unchanged"]:
                result.update(status="invalidated", reason="source_changed_during_measurement")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result.get(k) for k in ("status", "reason", "window_created", "summary")}))
    return result["status"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rounds", type=int, choices=range(10, 51), default=20)
    args = parser.parse_args()
    status = run(args.output, args.rounds)
    if status not in {"passed", "not_run"}:
        raise SystemExit(1)
