"""Compile the real Foundation host boundary; no AppKit or installed CLI effects."""

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def family_host(tmp_path_factory):
    if sys.platform != "darwin" or not shutil.which("xcrun"):
        pytest.skip("Native Foundation fixture requires macOS Swift")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path_factory.mktemp("family-host") / "fixture"
    result = subprocess.run(
        [
            "xcrun",
            "swiftc",
            "-swift-version",
            "5",
            "-parse-as-library",
            "-target",
            f"{platform.machine()}-apple-macosx12.0",
            str(root / "integrations/desktop/FamilySwitchLogic.swift"),
            str(root / "tests/fixtures/desktop_bootstrap/FamilySwitchHarness.swift"),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return binary


def invoke(binary, *args):
    result = subprocess.run([str(binary), *args], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def good_receipt():
    return {
        "success": True,
        "active_product": "threaddesk",
        "visible_family_windows": 1,
        "actual_outer_bounds": {"x": -100, "y": 24, "width": 940, "height": 664},
    }


@pytest.mark.parametrize(
    "change",
    [
        {},
        {"success": 1},
        {"success": False},
        {"active_product": "tollgate"},
        {"visible_family_windows": True},
        {"visible_family_windows": 2},
        {"actual_outer_bounds": {"x": 0, "y": 0, "width": 0, "height": 664}},
        {"actual_outer_bounds": {"x": 0, "y": 0, "width": 940, "height": -1}},
        {"actual_outer_bounds": {"x": "NaN", "y": 0, "width": 940, "height": 664}},
        {"actual_outer_bounds": {"x": 0, "y": 1e300, "width": 940, "height": 664}},
        {"error": None},
        {"error": {"code": "failed", "message": "refused"}},
        {"execution_outcome_unknown": True},
        {"execution_outcome_unknown": 1},
        {"execution_outcome_unknown": None},
        {"execution_outcome_unknown": False},
    ],
)
def test_success_requires_exact_abi_receipt(family_host, change):
    value = {**good_receipt(), **change}
    expected = "focused" if change in ({}, {"execution_outcome_unknown": False}) else "uncertain"
    # Large finite coordinates remain finite; the native broker owns clamping.
    if change.get("actual_outer_bounds", {}).get("y") == 1e300:
        expected = "focused"
    assert invoke(family_host, "outcome", "0", "threaddesk", json.dumps(value)) == expected


@pytest.mark.parametrize(
    "payload,expected",
    [
        (
            {
                "success": False,
                "error": {"code": "denied", "message": "refused"},
                "execution_outcome_unknown": False,
            },
            "failed",
        ),
        (
            {
                "success": False,
                "error": {"code": "unknown", "message": "inspect"},
                "execution_outcome_unknown": True,
            },
            "uncertain",
        ),
        (good_receipt(), "uncertain"),
        ({}, "uncertain"),
        ({"success": False, "execution_outcome_unknown": False}, "uncertain"),
    ],
)
def test_nonzero_exit_never_claims_success_or_loses_unknown(family_host, payload, expected):
    assert invoke(family_host, "outcome", "2", "threaddesk", json.dumps(payload)) == expected


@pytest.mark.parametrize("raw", ["not json", '"scalar"', "[]", "null", '{"success":true'])
def test_malformed_receipt_remains_unknown(family_host, raw):
    assert invoke(family_host, "outcome", "0", "threaddesk", raw) == "uncertain"


@pytest.mark.parametrize("text", ["focused", 'quote";\\\n', "</script>\u2028\u2029", "", "😀"])
def test_callback_scalars_escape_without_objc_exception(family_host, text):
    assert json.loads(invoke(family_host, "quote", text)) == text


@pytest.mark.parametrize(
    "change",
    [
        {},
        {"sameView": False},
        {"mainFrame": False},
        {"scheme": "https"},
        {"host": "localhost"},
        {"host": "example.invalid"},
        {"port": 8767},
        {"body": {"id": "call", "appId": "shell"}},
        {"body": {"id": "call", "appId": "threaddesk", "path": "/Applications/Other.app"}},
        {"body": {"id": "", "appId": "threaddesk"}},
        {"body": {"id": "x" * 129, "appId": "threaddesk"}},
    ],
)
def test_only_bound_main_view_frame_origin_and_catalog_request_is_admitted(family_host, change):
    value = {
        "sameView": True,
        "mainFrame": True,
        "scheme": "http",
        "host": "127.0.0.1",
        "port": 8766,
        "body": {"id": "call", "appId": "threaddesk"},
        **change,
    }
    assert invoke(family_host, "admit", json.dumps(value)) == ("true" if not change else "false")
