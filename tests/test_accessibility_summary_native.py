"""Mocked AX reads from production Swift; no AX element, permission or UI API invoked."""

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def accessibility_harness(tmp_path_factory):
    if sys.platform != "darwin" or not shutil.which("xcrun"):
        pytest.skip("Private Swift summary fixture requires Darwin SDK")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path_factory.mktemp("mock-accessibility") / "summary-fixture"
    sources = [root / "tests/fixtures/desktop_bootstrap/AccessibilityHarness.swift"]
    sources += [
        root / "integrations/desktop" / name
        for name in (
            "SystemControl.swift",
            "SystemBridge.swift",
            "SystemServices.swift",
            "SystemKeyboard.swift",
            "SystemShortcuts.swift",
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


def observation(harness, scenario):
    result = subprocess.run([str(harness), scenario], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_summary_sets_timeout_before_any_attribute(accessibility_harness):
    current = observation(accessibility_harness, "ordinary")
    assert current["prepared"] is True
    assert current["premature"] is False


def test_summary_fetches_each_attribute_once(accessibility_harness):
    current = observation(accessibility_harness, "ordinary")
    assert current["reads"]
    assert all(count == 1 for count in current["reads"].values())


def test_summary_truncation_uses_the_observed_text(accessibility_harness):
    current = observation(accessibility_harness, "flapping")["summary"]
    assert current["title"] == current["description"] == "short"
    assert current["title_truncated"] is current["description_truncated"] is False


def test_timeout_failure_prevents_all_reads(accessibility_harness):
    current = observation(accessibility_harness, "timeout_failure")
    assert current["error"] == "mock_timeout_failed"
    assert not current["reads"]


def test_secure_summary_does_not_fetch_value(accessibility_harness):
    current = observation(accessibility_harness, "secure")
    assert current["summary"]["secure_value_redacted"] is True
    assert "AXValue" not in current["reads"]


def test_missing_role_is_an_observation_error(accessibility_harness):
    current = observation(accessibility_harness, "missing_role")
    assert current["error"] == "macos_accessibility_unavailable"
    assert "AXValue" not in current["reads"]


@pytest.mark.parametrize("scenario", ["focus", "hidden"])
def test_catalog_revision_preserves_full_snapshot_semantics(accessibility_harness, scenario):
    assert observation(accessibility_harness, scenario)["error"] == "macos_catalog_changed"


def test_catalog_continuation_accepts_unchanged_metadata(accessibility_harness):
    current = observation(accessibility_harness, "catalog")
    assert current == {"success": True, "page_count": 1}
