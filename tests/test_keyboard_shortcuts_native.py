"""Pure injected AX-menu traversal/decoder/cache; no app or permission interaction."""

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which("xcrun"), reason="Darwin SDK required"
)
def test_native_menu_observation_decoder_and_cache_without_ui(tmp_path):
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / "shortcuts"
    sources = [root / "tests/fixtures/desktop_bootstrap/ShortcutsHarness.swift"]
    sources += [
        root / "integrations/desktop" / name
        for name in (
            "SystemShortcuts.swift",
            "SystemKeyboard.swift",
            "SystemControl.swift",
            "SystemBridge.swift",
            "SystemServices.swift",
        )
    ]
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
    ):
        command += ["-framework", framework]
    compiled = subprocess.run(command, capture_output=True, text=True, timeout=90)
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "decoder_cases": 22,
        "scan_cases": 6,
        "cache_cases": 12,
        "native_ui_calls": 0,
        "event_posts": 0,
        "permission_requests": 0,
    }
