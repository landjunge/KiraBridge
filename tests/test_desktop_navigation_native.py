"""URL decisions from production Foundation code, without loading any URL or UI."""

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def navigation_harness(tmp_path_factory):
    if sys.platform != "darwin" or not shutil.which("xcrun"):
        pytest.skip("Foundation URL fixture requires Darwin Swift")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path_factory.mktemp("navigation-policy") / "navigation-fixture"
    source = (root / "integrations/desktop/main.swift").read_text()
    assert source.count("// MARK: Desktop UI") == 1
    runtime = binary.parent / "DesktopRuntime.swift"
    runtime.write_text(source.split("// MARK: Desktop UI", 1)[0])
    result = subprocess.run(
        [
            "xcrun",
            "swiftc",
            "-swift-version",
            "5",
            "-parse-as-library",
            "-target",
            f"{platform.machine()}-apple-macosx12.0",
            str(runtime),
            str(root / "tests/fixtures/desktop_bootstrap/NavigationHarness.swift"),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize(
    "url,mode,expected",
    [
        ("http://127.0.0.1:8766/", "automatic", "allow"),
        ("http://127.0.0.1:8766/login", "automatic", "allow"),
        ("http://127.0.0.1:8766/protocol?stream=1", "automatic", "allow"),
        ("file:///private/owned/approval-login.html", "automatic", "allow"),
        ("file:///private/owned/approval-login.html#login", "automatic", "allow"),
        ("file:///private/custom-config/approval-login.html", "custom", "allow"),
        ("file:///private/owned/approval-login.html", "untrusted", "deny"),
        ("nil", "automatic", "deny"),
        ("http://127.0.0.1:8767/", "automatic", "deny"),
        ("https://127.0.0.1:8766/", "automatic", "deny"),
        ("http://localhost:8766/", "automatic", "deny"),
        ("http://[::1]:8766/", "automatic", "deny"),
        ("file:///private/owned/console-credentials.json", "automatic", "deny"),
        ("file://other-host/private/owned/approval-login.html", "automatic", "deny"),
        ("file:///private/owned/other/../approval-login.html", "automatic", "deny"),
        ("file:///private/owned/approval-login.html?ignored=1", "automatic", "deny"),
        ("http://user:pass@127.0.0.1:8766/", "activated", "deny"),
        ("https://example.invalid/", "automatic", "deny"),
        ("https://example.invalid/", "activated", "external"),
        ("javascript:alert(1)", "activated", "deny"),
        (
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
            "activated",
            "external",
        ),
        (
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
            "automatic",
            "deny",
        ),
        (
            "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
            "activated",
            "external",
        ),
        (
            "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
            "activated",
            "external",
        ),
        (
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",
            "activated",
            "external",
        ),
        (
            "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
            "activated",
            "deny",
        ),
        ("data:text/html,private-fixture", "automatic", "deny"),
        ("about:blank", "automatic", "deny"),
        ("http://127.0.0.1:8766/protocol", "popup", "true"),
        ("http://127.0.0.1:8766/protocol?stream=1", "popup", "true"),
        ("https://127.0.0.1:8766/protocol", "popup", "false"),
        ("ssh://127.0.0.1:8766/protocol", "popup", "false"),
        ("http://127.0.0.1:8767/protocol", "popup", "false"),
        ("http://127.0.0.1:8766/", "popup", "false"),
        ("/private/custom-config/approval-login.html", "openfiles-custom", "true"),
        ("/private/owned/approval-login.html", "openfiles", "true"),
        ("/private/owned/approval-login.html", "openfiles-custom", "false"),
        ("/private/custom-config/approval-login.html", "openfiles", "false"),
        ("/private/owned/approval-login.html", "openfiles-untrusted", "false"),
    ],
)
def test_exact_desktop_navigation_contract(navigation_harness, url, mode, expected):
    result = subprocess.run(
        [str(navigation_harness), url, mode], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


@pytest.mark.parametrize(
    "url,mode,port,expected",
    [
        ("http://127.0.0.1:54321/", "automatic", "54321", "allow"),
        ("http://127.0.0.1:54321/live", "automatic", "54321", "allow"),
        ("http://127.0.0.1:54321/protocol?stream=1", "popup", "54321", "true"),
        ("http://127.0.0.1:8766/", "automatic", "54321", "deny"),
        ("http://127.0.0.1:8766/protocol", "popup", "54321", "false"),
        ("http://127.0.0.1:8767/", "automatic", "54321", "deny"),
        ("http://localhost:54321/", "automatic", "54321", "deny"),
        ("https://127.0.0.1:54321/", "automatic", "54321", "deny"),
        ("http://127.0.0.1:54321/", "automatic", "8766", "deny"),
        ("http://user:pass@127.0.0.1:54321/", "automatic", "54321", "deny"),
        ("https://example.invalid/", "automatic", "54321", "deny"),
    ],
)
def test_isolated_origin_binds_exactly_one_loopback_port(
    navigation_harness, url, mode, port, expected
):
    result = subprocess.run(
        [str(navigation_harness), url, mode, port], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ({"login_file": "/private/custom/approval-login.html"}, "accepted"),
        ({"login_file": "/private/default/approval-login.html"}, "accepted"),
        ({"login_file": "relative/approval-login.html"}, "invalid"),
        ({"login_file": "file:///private/custom/approval-login.html"}, "invalid"),
        ({"login_file": "/private/custom/console-credentials.json"}, "invalid"),
        ({"login_file": "/private/custom/approval-login.html/"}, "invalid"),
        ({"login_file": "/private/\x00/approval-login.html"}, "invalid"),
        ({"login_file": 42}, "invalid"),
        ({}, "invalid"),
        ([], "invalid"),
    ],
)
def test_only_owned_bootstrap_receipt_can_select_login_path(navigation_harness, value, expected):
    result = subprocess.run(
        [str(navigation_harness), json.dumps(value), "receipt"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


@pytest.mark.parametrize(
    "path,mode,expected",
    [
        ("/private/custom-config/approval-login.html", "sequence-custom", True),
        ("/private/foreign/approval-login.html", "sequence-foreign", False),
        ("/private/custom-config/approval-login.html", "sequence-failure", False),
    ],
)
def test_early_open_event_waits_for_own_receipt(navigation_harness, path, mode, expected):
    result = subprocess.run(
        [str(navigation_harness), path, mode], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["before"] == observed["before_loads"] == 0
    assert observed["replies"] == [expected]
    assert observed["loads"] == (
        [] if mode == "sequence-failure" else ["/private/custom-config/approval-login.html"]
    )


def test_pending_open_event_queue_is_bounded(navigation_harness):
    result = subprocess.run(
        [
            str(navigation_harness),
            "/private/custom-config/approval-login.html",
            "sequence-overflow",
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    current = json.loads(result.stdout)
    assert current["before"] == 1
    assert current["before_loads"] == 0
    assert current["replies"].count(True) == 16
    assert current["replies"].count(False) == 1
    assert current["loads"] == ["/private/custom-config/approval-login.html"]
