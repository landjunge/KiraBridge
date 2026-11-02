"""Production Swift snapshot seam with injected AX metadata; no UI or TCC calls."""

import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import get_args

import pytest

from kirabridge.keyboard_models import NamedKey


@pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which("xcrun"), reason="Darwin SDK required"
)
def test_keyboard_snapshot_guards_and_utf16_without_ui(tmp_path):
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / "keyboard-inspect"
    sources = [root / "tests/fixtures/desktop_bootstrap/KeyboardInspectHarness.swift"]
    sources += [
        root / "integrations/desktop" / name
        for name in (
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
    observed = json.loads(result.stdout)
    assert observed["checks"] == 15
    assert observed["key_checks"] == 22
    assert set(observed["named_key_codes"]) == set(get_args(NamedKey))
    assert observed["field"]["value_sha256"] == hashlib.sha256("A😀e\u0301".encode()).hexdigest()
    assert (
        observed["native_ui_calls"]
        == observed["event_posts"]
        == observed["permission_requests"]
        == 0
    )
