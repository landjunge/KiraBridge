"""Private Swift framing fixtures, including a persistent real pipe without EOF."""

import json
import platform
import select
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def framing_harness(tmp_path_factory):
    if sys.platform != "darwin" or not shutil.which("xcrun"):
        pytest.skip("Private Swift framing fixture requires Darwin SDK")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path_factory.mktemp("owned-framing") / "framing-fixture"
    sources = [root / "tests/fixtures/desktop_bootstrap/FramingHarness.swift"]
    sources += [
        root / "integrations/desktop" / name
        for name in (
            "SystemBridge.swift",
            "SystemControl.swift",
            "SystemServices.swift",
            "SystemKeyboard.swift",
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
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    return binary


def observed(harness, mode):
    result = subprocess.run([str(harness), mode], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_native_frame_read_budget_is_buffered(framing_harness):
    current = observed(framing_harness, "budget")
    assert current["frames"] == [65535]
    assert current["reads"] <= 16


@pytest.mark.parametrize("mode", ["multiple", "fragmented"])
def test_frame_fragments_retain_order_and_utf8(framing_harness, mode):
    current = observed(framing_harness, mode)
    assert current["status"] == "eof"
    assert current["text"] == ["one", "Grüße", "last"]


@pytest.mark.parametrize(
    "mode,frames,status",
    [
        ("maximum", [65535], "eof"),
        ("oversize", [], "oversized"),
        ("prior_then_oversize", [5], "oversized"),
        ("empty", [], "eof"),
        ("partial", [], "eof"),
        ("empty_frames", [0, 0], "eof"),
        ("callback_failure", [3], "callback_failure"),
    ],
)
def test_native_frame_boundaries(framing_harness, mode, frames, status):
    current = observed(framing_harness, mode)
    assert current["frames"] == frames
    assert current["status"] == status


def test_short_frames_reply_while_the_input_pipe_stays_open(framing_harness):
    child = subprocess.Popen(
        [str(framing_harness), "pipe"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    try:
        child.stdin.write(b"{}\n")
        child.stdin.flush()
        assert select.select([child.stdout], [], [], 1.5)[0], (
            "Short LF frame waited for EOF/full read"
        )
        assert json.loads(child.stdout.readline()) == {"index": 1, "bytes": 2}
        assert child.poll() is None and not child.stdin.closed
        child.stdin.write(b"one\ntwo\n")
        child.stdin.flush()
        for index in (2, 3):
            assert select.select([child.stdout], [], [], 1.5)[0]
            assert json.loads(child.stdout.readline()) == {"index": index, "bytes": 3}
        child.stdin.close()
        assert child.wait(timeout=2) == 0
    finally:
        if child.poll() is None:
            child.kill()  # Only this explicitly started fixture, never a group.
            child.wait(timeout=2)
        for stream in (child.stdin, child.stdout, child.stderr):
            stream.close()
