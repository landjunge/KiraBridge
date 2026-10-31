"""No live acceptance here: selectors, restoration and cleanup use synthetic state only."""

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def harness_module():
    path = Path(__file__).resolve().parents[1] / "scripts/accept_system_modules_macos.py"
    spec = importlib.util.spec_from_file_location("acceptance_harness_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def runner(module, tmp_path):
    value = module.Harness(
        SimpleNamespace(root=tmp_path / "private-test", app=tmp_path / "native.app")
    )
    value.root.mkdir(mode=0o700)
    return value


def test_live_fixture_flag_is_mandatory(harness_module, tmp_path):
    with pytest.raises(SystemExit):
        harness_module.parser().parse_args(
            ["--app", str(tmp_path), "--root", str(tmp_path / "new")]
        )


@pytest.mark.parametrize(
    "operation",
    [
        "system.permission_request",
        "notifications.post",
        "capture.display",
        "clipboard.write",
        "session.input",
    ],
)
def test_forbidden_effects_never_dispatch(harness_module, tmp_path, operation):
    with pytest.raises(harness_module.AcceptanceError):
        harness_module.authorize_owned(operation, {}, {"pid": 42}, tmp_path)


@pytest.mark.parametrize(
    "operation,arguments",
    [
        ("apps.quit", {"pid": 99}),
        ("accessibility.set", {"pid": 99}),
        ("capture.window", {"expected_pid": 99}),
        ("windows.list", {"owner_pid": 99}),
        ("preferences.write", {"key": "appearance"}),
        ("apps.launch", {"app_path": "/Applications/UserApp.app"}),
    ],
)
def test_foreign_app_window_and_preference_targets_refuse(
    harness_module, tmp_path, operation, arguments
):
    with pytest.raises(harness_module.AcceptanceError):
        harness_module.authorize_owned(
            operation, arguments, {"pid": 42}, tmp_path / "OwnedFixture.app"
        )


@pytest.mark.parametrize("original", [{"exists": False}, {"exists": True, "value": 2048}])
async def test_preference_write_reset_restores_original_presence_and_value(
    harness_module, tmp_path, original
):
    value = runner(harness_module, tmp_path)
    state = {"key": harness_module.KEY, "revision": "a" * 64, **original}
    calls = []

    async def call(operation, arguments):
        calls.append(operation)
        assert arguments["key"] == harness_module.KEY
        if operation == "preferences.write":
            state.update(exists=True, value=arguments["value"])
        elif operation == "preferences.reset":
            state.update(exists=False)
            state.pop("value", None)
        return {"preference": dict(state)}

    value.call = call
    assert (await value.preferences())["restored"] is True
    assert state["exists"] == original["exists"]
    assert state.get("value") == original.get("value")
    assert calls.count("preferences.reset") == 1


async def test_external_preference_change_is_not_overwritten(harness_module, tmp_path):
    value = runner(harness_module, tmp_path)
    value.preference_before = {"key": harness_module.KEY, "exists": True, "value": 2048}
    value.preference_written = 128
    calls = []

    async def call(operation, arguments):
        calls.append(operation)
        return {"preference": {"exists": True, "value": 999, "revision": "a" * 64}}

    value.call = call
    with pytest.raises(harness_module.AcceptanceError, match="changed externally"):
        await value.restore_preference()
    assert calls == ["preferences.read"]


async def test_unknown_launch_cleanup_is_honest_and_requests_only_owned_exit(
    harness_module, tmp_path
):
    value = runner(harness_module, tmp_path)
    value.launch_attempted = True
    await value.cleanup()
    assert (value.root / "fixture-exit.request").read_text() == value.nonce
    assert value.evidence["cleanup"]["complete"] is False
    assert value.evidence["cleanup"]["launch_identity_unconfirmed"] is True
    assert value.evidence["trace"] == []


async def test_foreign_receipt_does_not_authorize_cleanup_target(harness_module, tmp_path):
    value = runner(harness_module, tmp_path)
    value.launch_attempted = True
    value.fixture = {"pid": 42, "started_at": 1.0}
    (value.root / "fixture-state.json").write_text(
        json.dumps(
            {
                "fixture_uuid": value.nonce,
                "uid": os.getuid(),
                "pid": 99,
                "start": "1.000000",
            }
        )
    )
    await value.cleanup()
    assert value.receipt is None and value.evidence["trace"] == []
    assert value.evidence["cleanup"]["complete"] is False


def test_reused_pid_is_original_absence_but_unknown_is_not(harness_module):
    original = {"pid": 42, "start": "1.000000"}
    assert harness_module.original_absent(
        {"state": "present", "pid": 42, "start": "2.000000"}, original
    )
    assert not harness_module.original_absent({"state": "unknown", "pid": 42}, original)
    assert not harness_module.original_absent(
        {"state": "present", "pid": 42, "start": "1.000000"}, original
    )
    for value in (None, "invalid", "1", 1.0):
        assert not harness_module.original_absent(
            {"state": "present", "pid": 42, "start": value}, original
        )
    assert not harness_module.original_absent({"state": "present", "pid": 42}, original)
    assert not harness_module.original_absent({"state": "absent", "pid": 99}, original)
    assert not harness_module.original_absent(
        {"state": "present", "pid": 99, "start": "2.000000"}, original
    )


def test_capture_minimum_and_no_live_core_scope_are_explicit(harness_module, tmp_path):
    value = runner(harness_module, tmp_path)
    assert value.evidence["live_service_used"] is False
    assert value.evidence["capture_minimum_macos"] == "14.0"
    assert "Direct SystemModules" in value.evidence["scope"]
    assert "system.permission_request" not in harness_module.ALLOWED
