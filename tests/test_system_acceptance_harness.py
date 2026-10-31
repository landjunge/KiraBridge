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


def window_fixture(value):
    value.fixture = {"pid": 42, "started_at": 123.5}
    value.receipt = {
        "fixture_uuid": value.nonce,
        "state": "present",
        "phase": "ready",
        "pid": 42,
        "uid": os.getuid(),
        "start": "123.500007",  # Kernel token deliberately differs from AppKit launchDate.
        "window_id": 77,
    }
    return value


def window_row(identifier=77, **changes):
    return {
        "window_id": identifier,
        "owner_pid": 42,
        "application_start": "123.500000",
        "layer": 0,
        "on_screen": True,
        "revision": "a" * 64,
        **changes,
    }


def window_inventory(*rows, **changes):
    return {
        "windows": list(rows),
        "total": len(rows),
        "offset": 0,
        "truncated": False,
        "revision": "b" * 64,
        **changes,
    }


def test_exact_receipt_window_selected_among_other_owned_windows(harness_module, tmp_path):
    value = window_fixture(runner(harness_module, tmp_path))
    assert (
        harness_module.select_owned_window(
            window_inventory(window_row(88, layer=3), window_row()),
            value.fixture,
            value.receipt,
            value.nonce,
        )
        == window_row()
    )
    assert (
        harness_module.select_owned_window(
            window_inventory(window_row(88)), value.fixture, value.receipt, value.nonce
        )
        is None
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"fixture_uuid": "foreign"},
        {"pid": 99},
        {"pid": True},
        {"uid": -1},
        {"state": "unknown"},
        {"phase": "terminating"},
        {"start": "unknown"},
        {"window_id": None},
        {"window_id": True},
        {"window_id": 0},
        {"window_id": 2**32},
    ],
)
def test_window_receipt_binding_refuses(harness_module, tmp_path, changes):
    value = window_fixture(runner(harness_module, tmp_path))
    value.receipt.update(changes)
    with pytest.raises(harness_module.AcceptanceError):
        harness_module.select_owned_window(
            window_inventory(window_row()), value.fixture, value.receipt, value.nonce
        )


@pytest.mark.parametrize(
    "inventory",
    [
        window_inventory(window_row(), window_row()),
        window_inventory(window_row(), window_row(88), window_row(88)),
        window_inventory(window_row(owner_pid=99)),
        window_inventory(window_row(), window_row(88, owner_pid=99)),
        window_inventory(window_row(owner_pid=True)),
        window_inventory(window_row(application_start="123.500007")),
        window_inventory(window_row(layer=3)),
        window_inventory(window_row(on_screen=False)),
        window_inventory(window_row(revision="bad")),
        window_inventory(window_row(window_id=True)),
        window_inventory(window_row(), truncated=True),
        window_inventory(window_row(), total=2),
        window_inventory(window_row(), offset=1),
        window_inventory(window_row(), revision=None),
    ],
)
def test_window_inventory_refuses_incomplete_duplicate_or_foreign_identity(
    harness_module, tmp_path, inventory
):
    value = window_fixture(runner(harness_module, tmp_path))
    with pytest.raises(harness_module.AcceptanceError):
        harness_module.select_owned_window(inventory, value.fixture, value.receipt, value.nonce)


async def test_window_readiness_polls_only_missing_exact_id_then_inspects_and_focuses(
    harness_module, tmp_path, monkeypatch
):
    value = window_fixture(runner(harness_module, tmp_path))
    calls, sleeps = [], []
    inventories = [window_inventory(), window_inventory(window_row(88), window_row())]

    async def sleep(delay):
        sleeps.append(delay)

    async def call(operation, arguments):
        calls.append(operation)
        if operation == "windows.list":
            assert arguments == {
                "owner_pid": 42,
                "expected_start": "123.500000",
                "include_titles": False,
                "limit": 100,
            }
            return inventories.pop(0)
        if operation == "windows.inspect":
            assert arguments["window_id"] == 77 and arguments["expected_pid"] == 42
            return {"window": window_row()}
        assert operation == "app.focus" and arguments["expected_pid"] == 42
        return {}

    value.call = call
    monkeypatch.setattr(harness_module.asyncio, "sleep", sleep)
    assert (await value.windows())["window_id"] == 77
    assert calls == ["windows.list", "windows.list", "windows.inspect", "app.focus"]
    assert len(sleeps) == 1
    assert value.evidence["window_probes"][0]["row_count"] == 0
    assert [r["window_id"] for r in value.evidence["window_probes"][1]["owned_rows"]] == [
        88,
        77,
    ]


async def test_window_missing_deadline_never_selects_other_owned_window(
    harness_module, tmp_path, monkeypatch
):
    value = window_fixture(runner(harness_module, tmp_path))
    clock, calls = [0.0], []

    async def sleep(delay):
        clock[0] += delay

    async def call(operation, arguments):
        calls.append(operation)
        assert operation == "windows.list"
        return window_inventory(window_row(88))

    value.call = call
    monkeypatch.setattr(harness_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(harness_module.asyncio, "sleep", sleep)
    with pytest.raises(harness_module.AcceptanceError, match="77 missing before 8-second"):
        await value.windows()
    assert 8 <= clock[0] <= 8.001 and len(calls) <= 81
    assert set(calls) == {"windows.list"}


async def test_window_result_arriving_after_deadline_does_not_focus(
    harness_module, tmp_path, monkeypatch
):
    value = window_fixture(runner(harness_module, tmp_path))
    clock = [0.0]

    async def call(operation, arguments):
        assert operation == "windows.list"
        clock[0] = 9
        return window_inventory(window_row())

    async def sleep(delay):
        assert delay == 0

    value.call = call
    monkeypatch.setattr(harness_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(harness_module.asyncio, "sleep", sleep)
    with pytest.raises(harness_module.AcceptanceError, match="missing before 8-second"):
        await value.windows()


async def test_foreign_window_inventory_fails_without_poll_or_foreign_probe_data(
    harness_module, tmp_path
):
    value = window_fixture(runner(harness_module, tmp_path))
    calls = []

    async def call(operation, arguments):
        calls.append(operation)
        return window_inventory(window_row(999, owner_pid=99))

    value.call = call
    with pytest.raises(harness_module.AcceptanceError, match="foreign"):
        await value.windows()
    assert calls == ["windows.list"]
    assert value.evidence["window_probes"][0]["owned_rows"] == []
    assert "999" not in (value.root / "evidence.json").read_text()


async def test_capture_uses_same_exact_receipt_window_selector(harness_module, tmp_path):
    value = window_fixture(runner(harness_module, tmp_path))
    calls = []

    async def call(operation, arguments):
        calls.append(operation)
        if operation == "windows.list":
            return window_inventory(window_row(88), window_row())
        assert operation == "capture.window"
        assert arguments["window_id"] == 77 and arguments["expected_pid"] == 42
        raise LookupError("stop before synthetic capture effect")

    value.call = call
    with pytest.raises(LookupError, match="stop before"):
        await value.capture()
    assert calls == ["windows.list", "capture.window"]
