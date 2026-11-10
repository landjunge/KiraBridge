"""Production Swift snapshot seam with injected AX metadata; no UI or TCC calls."""

import base64
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import get_args

import pytest

from kirabridge.bridge_core.models import canonical
from kirabridge.keyboard_models import KeyboardTextInput, NamedKey
from kirabridge.keyboard_text import native_frame_bytes, plan_text


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
    text = "\ufeff" + "x" * 100000 + " e\u0301😀\r\n"
    request = KeyboardTextInput(
        target={
            "pid": 123,
            "expected_started_at": 123.0,
            "target_token": "a" * 32,
            "helper_pid": 11111111,
            "worker_generation": "00000000-0000-0000-0000-000000000000",
            "expected_revision": "b" * 64,
        },
        text=text,
    )
    plan = plan_text(request, task_id="stage_fixture", principal="fixture_owner")
    begin = plan.manifest
    begin["binding_json"] = canonical({k: v for k, v in begin.items() if k != "transfer_id"})
    with pytest.raises(ValueError, match="frame exceeds"):
        native_frame_bytes("keyboard.text", request.model_dump(), principal="fixture_owner")
    assert len(native_frame_bytes("keyboard.text.begin", begin, principal="fixture_owner")) <= 65536
    for packet in plan.chunks:
        assert (
            len(native_frame_bytes("keyboard.text.chunk", packet, principal="fixture_owner"))
            <= 65536
        )
    result = subprocess.run(
        [str(binary)],
        input=json.dumps(
            {
                "begin": begin,
                "chunks": plan.chunks,
                "expected_utf8_b64": base64.b64encode(text.encode()).decode(),
            }
        ),
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    observed = json.loads(result.stdout)
    assert observed["checks"] == 15
    assert observed["key_checks"] == 22
    assert observed["layout_checks"] == 53
    assert observed["extended_key_checks"] == 60
    assert observed["fn_navigation_checks"] == 60
    assert observed["text_checks"] == 27
    assert observed["stage_checks"] == 27
    assert observed["return_checks"] == 14
    assert observed["ax_checks"] == 16
    assert observed["windowless_checks"] == 10
    assert observed["windowless_checks"] == 10
    assert observed["layout_positions"] == {
        "com.apple.keylayout.US": {"z": 6, "Z": 6, "y": 16, "Y": 16},
        "com.apple.keylayout.German": {"z": 16, "Z": 16, "y": 6, "Y": 6},
    }
    assert set(observed["named_key_codes"]) == set(get_args(NamedKey))
    assert observed["field"]["value_sha256"] == hashlib.sha256("A😀e\u0301".encode()).hexdigest()
    assert (
        observed["native_ui_calls"]
        == observed["event_posts"]
        == observed["permission_requests"]
        == 0
    )
