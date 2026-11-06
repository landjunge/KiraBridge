"""Production AX batch planning and strict CF decoding with synthetic values."""

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def batch_harness(tmp_path_factory):
    if sys.platform != "darwin" or not shutil.which("xcrun"):
        pytest.skip("Private synthetic Swift AX batching requires Darwin SDK")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path_factory.mktemp("synthetic-accessibility-batch") / "batch-fixture"
    sources = [root / "tests/fixtures/desktop_bootstrap/AccessibilityBatchHarness.swift"]
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


@pytest.mark.parametrize("scenario", ["ordinary", "numeric_value", "missing_optional"])
def test_two_batches_preserve_individual_payload_revision_and_geometry(batch_harness, scenario):
    result = observation(batch_harness, scenario)
    assert result["matches_individual_summary"] is True
    assert result["baseline_attribute_calls"] == 13
    assert result["baseline_action_calls"] == 1
    assert result["batch_copy_calls"] == 2
    assert result["batch_action_calls"] == 1
    assert result["fallback_calls"] == 0
    assert result["summary"]["position"] == [12, 34]
    assert result["summary"]["size"] == [100, 50]
    assert result["batch_requested_attributes"][0] == ["AXRole", "AXSubrole"]
    assert "AXValue" in result["batch_requested_attributes"][1]


@pytest.mark.parametrize("scenario", ["secure_role", "secure_subrole", "secure_fallback"])
def test_secure_values_are_never_requested_by_batches_or_fallback(batch_harness, scenario):
    result = observation(batch_harness, scenario)
    assert result["matches_individual_summary"] is True
    assert result["baseline_attribute_calls"] == 12
    assert result["summary"]["secure_value_redacted"] is True
    assert not {"value", "value_sha256", "value_characters"}.intersection(result["summary"])
    assert all("AXValue" not in names for names in result["batch_requested_attributes"])
    assert result["fallback_value_reads"] == 0


@pytest.mark.parametrize(
    "scenario,copies",
    [("whole_not_implemented_first", 1), ("whole_not_implemented_second", 2)],
)
def test_whole_not_implemented_restarts_a_complete_fresh_scalar_observation(
    batch_harness, scenario, copies
):
    result = observation(batch_harness, scenario)
    assert result["matches_individual_summary"] is True
    assert result["batch_copy_calls"] == copies
    assert result["batch_action_calls"] == 0
    assert result["fallback_calls"] == 1
    assert result["fallback_attribute_calls"] == 13
    assert result["fallback_action_calls"] == 1
    assert result["fallback_value_reads"] == 1


@pytest.mark.parametrize(
    "scenario,copies",
    [
        ("missing_role", 1),
        ("bad_role_type", 1),
        ("bad_subrole_type", 1),
        ("classification_error", 1),
        ("classification_failure", 1),
        ("role_failure", 1),
        ("metadata_error", 2),
        ("title_failure", 2),
        ("value_failure", 2),
        ("description_cannot_complete", 2),
        ("identifier_invalid_element", 2),
        ("description_not_implemented", 2),
        ("slot_not_implemented", 2),
        ("whole_error", 1),
        ("whole_failure", 1),
        ("whole_metadata_failure", 2),
        ("whole_unsupported", 1),
        ("success_nil", 1),
        ("wrong_container", 1),
        ("wrong_count", 1),
        ("wrapped_success", 1),
    ],
)
def test_unobservable_or_malformed_batches_fail_closed_without_fallback(
    batch_harness, scenario, copies
):
    result = observation(batch_harness, scenario)
    assert result["error"] == "macos_accessibility_unavailable"
    assert result["batch_copy_calls"] == copies
    assert result["batch_action_calls"] == 0
    assert result["fallback_calls"] == 0
    if copies == 1:
        assert "AXValue" not in result["batch_requested_attributes"][0]


@pytest.mark.parametrize(
    "scenario,error,copies,actions",
    [
        ("prepare_failure", "mock_prepare_failed", 0, 0),
        ("copy_deadline", "deadline", 1, 0),
        ("actions_error", "macos_accessibility_unavailable", 2, 1),
    ],
)
def test_deadline_preparation_and_actions_errors_do_not_trigger_scalar_replay(
    batch_harness, scenario, error, copies, actions
):
    result = observation(batch_harness, scenario)
    assert result["error"] == error
    assert result["batch_copy_calls"] == copies
    assert result["batch_action_calls"] == actions
    assert result["fallback_calls"] == 0


def test_each_summary_fetches_new_values_and_revisions_without_a_value_cache(batch_harness):
    result = observation(batch_harness, "fresh_calls")
    assert result["summary"]["title"] == "synthetic title"
    assert result["second_summary"]["title"] == "new synthetic title"
    assert result["fresh_revision_changed"] is True
    assert result["batch_copy_calls"] == 4
    assert result["batch_action_calls"] == 2


def test_unsupported_metadata_reclassifies_a_now_secure_field_in_fresh_fallback(batch_harness):
    result = observation(batch_harness, "fallback_new_secure")
    assert "AXValue" in result["batch_requested_attributes"][1]
    assert result["batch_copy_calls"] == 2
    assert result["batch_action_calls"] == 0
    assert result["fallback_calls"] == 1
    assert result["fallback_attribute_calls"] == 12
    assert result["fallback_value_reads"] == 0
    assert result["summary"]["secure_value_redacted"] is True
    assert not {"value", "value_sha256", "value_characters"}.intersection(result["summary"])


def test_unimplemented_actions_are_omitted_without_replaying_the_scalar_summary(batch_harness):
    result = observation(batch_harness, "actions_not_implemented")
    assert result["matches_individual_summary"] is True
    assert "actions" not in result["summary"]
    assert result["batch_copy_calls"] == 2
    assert result["batch_action_calls"] == 1
    assert result["fallback_calls"] == 0


@pytest.mark.parametrize(
    "scenario,unavailable",
    [
        ("optional_description_failure", ["AXDescription"]),
        ("optional_identifier_failure", ["AXIdentifier"]),
        ("optional_both_failure", ["AXDescription", "AXIdentifier"]),
        ("optional_failure_fallback", ["AXDescription", "AXIdentifier"]),
        ("secure_optional_failure", ["AXDescription", "AXIdentifier"]),
    ],
)
def test_optional_cocoa_metadata_failure_preserves_observation_and_revision(
    batch_harness, scenario, unavailable
):
    result = observation(batch_harness, scenario)
    summary = result["summary"]
    assert result["matches_individual_summary"] is True
    assert summary["unavailable_metadata"] == unavailable
    assert summary["position"] == [12, 34]
    assert summary["size"] == [100, 50]
    assert summary["actions"] == ["AXPress"]
    assert result["batch_copy_calls"] == 2
    assert result["fallback_calls"] == (scenario == "optional_failure_fallback")
    if scenario == "secure_optional_failure":
        assert summary["secure_value_redacted"] is True
        assert not {"value", "value_sha256", "value_characters"}.intersection(summary)
        assert all("AXValue" not in names for names in result["batch_requested_attributes"])
    else:
        assert summary["value_characters"] == len("synthetic value")


def test_metadata_recovery_changes_revision_even_when_the_observed_text_is_empty(batch_harness):
    result = observation(batch_harness, "optional_failure_recovery")
    assert result["summary"]["description"] == result["second_summary"]["description"] == ""
    assert result["summary"]["identifier"] == result["second_summary"]["identifier"] == ""
    assert "unavailable_metadata" in result["summary"]
    assert "unavailable_metadata" not in result["second_summary"]
    assert result["recovery_revision_changed"] is True
    assert result["recovery_matches_scalar"] is True


@pytest.mark.parametrize(
    "scenario",
    [
        "classification_failure",
        "role_failure",
        "title_failure",
        "value_failure",
        "description_cannot_complete",
        "identifier_invalid_element",
        "description_not_implemented",
    ],
)
def test_scalar_decoder_keeps_nonoptional_and_transport_errors_fatal(batch_harness, scenario):
    result = observation(batch_harness, scenario)
    assert result["baseline_error"] == "macos_accessibility_unavailable"
    assert result["error"] == "macos_accessibility_unavailable"
    assert "summary" not in result
