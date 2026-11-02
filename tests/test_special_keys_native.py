"""Native system-key planning, event construction and guards without OS input."""

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def run_native_harness(tmp_path, harness):
    root = Path(__file__).resolve().parents[1]
    sources = [root / "tests/fixtures/desktop_bootstrap" / harness]
    sources += [
        root / "integrations/desktop" / name
        for name in (
            "SystemSpecialKeys.swift",
            "SystemKeyboard.swift",
            "SystemShortcuts.swift",
            "SystemControl.swift",
            "SystemBridge.swift",
            "SystemServices.swift",
        )
    ]
    # Other team members can edit their own native files while this narrow
    # harness runs; compile one immutable observation of all dependencies.
    pinned = tmp_path / "sources"
    pinned.mkdir()
    for source in sources:
        shutil.copy2(source, pinned / source.name)
    sources = [pinned / source.name for source in sources]
    binary = tmp_path / "system-special-keys"
    command = [
        "xcrun",
        "swiftc",
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
        "Carbon",
    ):
        command += ["-framework", name]
    compiled = subprocess.run(command, capture_output=True, text=True, timeout=90)
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which("xcrun"), reason="Darwin SDK required"
)
def test_system_key_contract_without_hardware_changes(tmp_path):
    receipt = run_native_harness(tmp_path, "SpecialKeysHarness.swift")
    assert receipt["checks"] >= 40
    assert receipt["system_event_types"] == 19
    assert receipt["simulated_posts"] == 6
    assert all(
        receipt[key] == 0
        for key in ("real_event_posts", "real_hardware_writes", "permission_requests")
    )


@pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which("xcrun"), reason="Darwin SDK required"
)
def test_system_key_observation_delta_without_os_input(tmp_path):
    receipt = run_native_harness(tmp_path, "SpecialKeysDeltaHarness.swift")
    assert receipt["checks"] >= 12
    assert receipt["real_event_posts"] == receipt["permission_requests"] == 0
