"""Injected Caps Lock flags and state-route guards; never posts or sets OS state."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which("xcrun"), reason="Darwin SDK required"
)
def test_caps_lock_event_flags_without_os_input(tmp_path):
    root = Path(__file__).resolve().parents[1]
    sources = [root / "tests/fixtures/desktop_bootstrap/CapsEventFlagsHarness.swift"]
    sources += [
        root / "integrations/desktop" / name
        for name in (
            "SystemKeyboard.swift",
            "SystemSpecialKeys.swift",
            "SystemShortcuts.swift",
            "SystemBridge.swift",
            "SystemControl.swift",
            "SystemServices.swift",
        )
    ]
    binary = tmp_path / "caps-event-flags"
    command = [
        "xcrun",
        "swiftc",
        "-swift-version",
        "5",
        "-parse-as-library",
        "-target",
        "x86_64-apple-macosx12.0",
        *map(str, sources),
        "-o",
        str(binary),
    ]
    for framework in (
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
        command += ["-framework", framework]
    compiled = subprocess.run(command, capture_output=True, text=True, check=False, timeout=90)
    assert compiled.returncode == 0, compiled.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, check=False, timeout=5)
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(run.stdout) == {
        "checks": 270,
        "event_posts": 0,
        "os_writes": 0,
        "native_ui_calls": 0,
        "permission_requests": 0,
    }
