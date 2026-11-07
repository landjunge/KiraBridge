"""Bounded production Swift traversal with synthetic nodes; no desktop effects."""

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from kirabridge.platform_adapters.macos.control_models import AccessibilityInspectInput

APP = {"pid": 123, "expected_started_at": 123.0}
TOKEN = {
    "element_token": "a" * 32,
    "helper_pid": 456,
    "worker_generation": "00000000-0000-0000-0000-000000000001",
}


def test_legacy_inspect_remains_the_default_and_tree_is_opt_in():
    assert AccessibilityInspectInput(**APP).max_depth == 0
    tree = AccessibilityInspectInput(**APP, **TOKEN, max_depth=32)
    assert tree.max_nodes == 256
    assert tree.max_tree_bytes == 262144
    assert tree.tree_budget_ms == 1500


@pytest.mark.parametrize(
    "extra",
    [
        {"max_depth": -1},
        {"max_depth": 33},
        {"max_depth": True},
        {"max_nodes": 0},
        {"max_nodes": 513},
        {"max_tree_bytes": 16383},
        {"max_tree_bytes": 524289},
        {"tree_budget_ms": 49},
        {"tree_budget_ms": 5001},
        {"max_depth": 2, "offset": 1, "expected_revision": "b" * 64},
        {"max_depth": 2, "value_offset": 1, "expected_revision": "b" * 64},
        {"max_depth": 2, "expected_revision": "b" * 64},
    ],
)
def test_invalid_or_ambiguous_tree_limits_are_rejected(extra):
    with pytest.raises(ValidationError):
        AccessibilityInspectInput(**APP, **TOKEN, **extra)


@pytest.fixture(scope="module")
def tree_harness(tmp_path_factory):
    if sys.platform != "darwin" or not shutil.which("xcrun"):
        pytest.skip("Private synthetic Swift traversal requires Darwin SDK")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path_factory.mktemp("synthetic-accessibility-tree") / "tree-fixture"
    sources = [root / "tests/fixtures/desktop_bootstrap/AccessibilityTreeHarness.swift"]
    sources += [
        root / "integrations/desktop" / name
        for name in (
            "SystemControl.swift",
            "SystemBridge.swift",
            "SystemServices.swift",
            "SystemKeyboard.swift",
            "SystemShortcuts.swift",
            "SystemSpecialKeys.swift",
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
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return binary


def observation(harness, scenario):
    result = subprocess.run([str(harness), scenario], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    current = json.loads(result.stdout)
    assert all(
        current[key] == 0 for key in ("native_ui_calls", "permission_requests", "input_posts")
    )
    return current


def test_full_snapshot_covers_a_nested_workload_in_one_operation(tree_harness):
    result = observation(tree_harness, "full")
    tree = result["tree"]
    assert tree["node_count"] == 121
    assert tree["complete"] is True
    assert tree["snapshot_atomic"] is False
    assert tree["truncated_reasons"] == []
    assert result["legacy_internal_node_calls"] == 40
    assert any(node["title"] == "Add people" for node in tree["nodes"])
    assert tree["bytes"] == result["encoded_tree_bytes"] <= tree["max_tree_bytes"]
    assert result["individual_revisions_match"] is True


def test_cycles_and_shared_children_do_not_loop_or_repeat_nodes(tree_harness):
    result = observation(tree_harness, "cycle")
    assert result["reads"] == result["tree"]["node_count"] == 3
    assert result["tree"]["complete"] is True
    assert all(not row["children_truncated"] for row in result["tree"]["nodes"])


@pytest.mark.parametrize(
    "scenario,reason,count",
    [
        ("depth", "max_depth", 4),
        ("nodes", "max_nodes", 2),
        ("bytes", "max_tree_bytes", 1),
        ("time", "time_budget", 2),
    ],
)
def test_bounds_return_explicit_partial_frontiers(tree_harness, scenario, reason, count):
    tree = observation(tree_harness, scenario)["tree"]
    assert tree["complete"] is False
    assert reason in tree["truncated_reasons"]
    assert tree["node_count"] == count
    assert any(node["children_truncated"] for node in tree["nodes"])
    assert tree["bytes"] <= tree["max_tree_bytes"]
    assert all(node["element_token"] and node["revision"] for node in tree["nodes"])


@pytest.mark.parametrize(
    "scenario,error",
    [
        ("owner", "macos_target_changed"),
        ("changed", "macos_tree_changed"),
        ("unavailable", "macos_accessibility_unavailable"),
        ("root_time", "macos_tree_timeout"),
        ("childlimit", "macos_resource_limit"),
        ("heldlimit", "macos_resource_limit"),
        ("rootbytes", "macos_resource_limit"),
        ("invaliddepth", "invalid_arguments"),
    ],
)
def test_unknown_ownership_churn_and_unobservable_roots_fail_closed(tree_harness, scenario, error):
    assert observation(tree_harness, scenario)["error"] == error


def test_nested_secure_fields_never_read_or_export_values_or_hashes(tree_harness):
    result = observation(tree_harness, "secure")
    secure = [node for node in result["tree"]["nodes"] if node["secure_value_redacted"]]
    assert len(secure) == 1
    assert not {"value", "value_characters", "value_sha256"}.intersection(secure[0])
    assert result["value_reads"] == 2 * (result["tree"]["node_count"] - 1)


@pytest.mark.parametrize(
    "scenario,count",
    [("children_empty", 0), ("children_nil", 0), ("actions_empty", 0), ("actions_valid", 1)],
)
def test_observable_empty_children_and_valid_actions_decode(tree_harness, scenario, count):
    assert observation(tree_harness, "decode_" + scenario)["count"] == count


@pytest.mark.parametrize(
    "scenario,error",
    [
        ("children_scalar", "macos_accessibility_unavailable"),
        ("children_mixed", "macos_accessibility_unavailable"),
        ("children_large", "macos_resource_limit"),
        ("actions_nil", "macos_accessibility_unavailable"),
        ("actions_mixed", "macos_accessibility_unavailable"),
        ("actions_large", "macos_resource_limit"),
        ("actions_long", "macos_resource_limit"),
    ],
)
def test_malformed_or_excessive_native_arrays_do_not_claim_a_complete_tree(
    tree_harness, scenario, error
):
    assert observation(tree_harness, "decode_" + scenario)["error"] == error
