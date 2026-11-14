"""Production private terminal guards and Return lifecycle, with no UI/event access."""

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
def test_private_terminal_native_guards_without_ui(tmp_path):
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / "terminal-input"
    sources = [root / "tests/fixtures/desktop_bootstrap/TerminalInputHarness.swift"]
    sources += [
        root / "integrations/desktop" / name
        for name in (
            "SystemKeyboard.swift",
            "SystemSpecialKeys.swift",
            "SystemShortcuts.swift",
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
        "CoreAudio",
        "IOKit",
    ):
        command += ["-framework", framework]
    compiled = subprocess.run(command, capture_output=True, text=True, timeout=90)
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    observed = json.loads(result.stdout)
    assert observed["checks"] >= 60
    assert observed["simulated_posts"] == 4
    assert observed["softwrap_after_typing_unknown"] is True
    assert (
        observed["native_ui_calls"]
        == observed["event_posts"]
        == observed["permission_requests"]
        == 0
    )
