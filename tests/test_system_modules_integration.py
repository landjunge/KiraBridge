"""System operations share typed schemas, central policy, provider and task results."""

import asyncio
import base64
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from kirabridge.bridge_core.bridge import INPUTS
from kirabridge.bridge_core.models import BridgeError
from kirabridge.image_manager import image_task_result, validate_png
from kirabridge.operations import OPERATIONS
from kirabridge.platform_adapters.macos.control_models import (
    AccessibilitySetInput,
    ApplicationTargetInput,
)
from kirabridge.platform_adapters.macos.system_identity import installed_source_commit
from kirabridge.system_operations import SYSTEM_LEAVES, SYSTEM_READ_OPERATIONS

REV = "a" * 64
GEN = "00000000-0000-0000-0000-000000000001"
APP = {"pid": 222, "expected_started_at": 123.0}
WINDOW = {"window_id": 42, "expected_pid": 222, "expected_start": "123.000000"}
ELEMENT = {
    **APP,
    "element_token": "b" * 32,
    "helper_pid": 333,
    "worker_generation": GEN,
    "expected_revision": REV,
}
SAMPLES = {
    "keyboard.inspect": APP,
    "system.info": {},
    "system.processes": {},
    "system.process": {"pid": 222, "expected_start": "123.000000"},
    "system.signal": {"pid": 222, "expected_start": "123.000000", "signal": "TERM"},
    "system.permissions": {},
    "system.permission_request": {"resource": "accessibility"},
    "system.displays": {},
    "system.volumes": {},
    "apps.list": {},
    "apps.inspect": APP,
    "apps.quit": APP,
    "apps.launch": {},
    "app.focus": {"expected_pid": 222, "expected_start": "123.000000"},
    "windows.list": {},
    "windows.inspect": WINDOW,
    "windows.focus": {
        "expected_pid": 222,
        "expected_start": "123.000000",
        "ax_identifier": "owned-window",
    },
    "capture.window": {**WINDOW, "expected_revision": REV},
    "capture.display": {"display_id": 1, "expected_revision": REV},
    "notifications.status": {},
    "notifications.post": {"body": "Own synthetic test"},
    "preferences.read": {"key": "appearance"},
    "preferences.write": {"key": "appearance", "value": "dark", "expected_revision": REV},
    "preferences.reset": {"key": "appearance", "expected_revision": REV},
    "accessibility.status": {},
    "accessibility.inspect": APP,
    "accessibility.action": {**ELEMENT, "action": "press"},
    "accessibility.set": {**ELEMENT, "attribute": "focused", "value": True},
}


def native(bridge):
    probe = bridge.macos.capability_probe
    probe.facts.update(platform="darwin", os_version="15.7.4")
    probe.native_metadata = lambda: {
        "available": True,
        "revision": "fixture-v1",
        "keyboard_protocol": 1,
    }
    bridge.system_modules.execute = AsyncMock(return_value={"effect": "fixture_only"})


async def test_desktop_focus_waits_for_session_transaction_but_inspect_stays_readonly(bridge):
    native(bridge)
    observed = []

    async def running(evidence):
        observed.append(evidence["operation"])

    def task(operation):
        return {
            "id": "owned-system-test",
            "principal": "local",
            "operation": operation,
            "args": SAMPLES[operation],
        }

    assert bridge.desktop_input.lock is bridge.sessions.lock
    async with bridge.sessions.lock:
        focus = asyncio.create_task(bridge.execute(task("app.focus"), running, running))
        await asyncio.sleep(0)
        assert not focus.done() and not observed
        await asyncio.wait_for(bridge.execute(task("keyboard.inspect"), running, running), 1)
        assert observed == ["keyboard.inspect"]
    await focus
    assert observed == ["keyboard.inspect", "app.focus"]
    assert bridge.system_modules.execute.await_count == 2


async def test_desktop_lock_timeout_does_not_dispatch_or_mark_running(bridge):
    native(bridge)
    bridge.desktop_input.timeout = 0.01
    running = AsyncMock()
    async with bridge.sessions.lock:
        with pytest.raises(BridgeError) as caught:
            await bridge.execute(
                {
                    "id": "owned-system-test",
                    "principal": "local",
                    "operation": "app.focus",
                    "args": SAMPLES["app.focus"],
                },
                running,
                running,
            )
    assert caught.value.code == "desktop_input_busy"
    running.assert_not_awaited()
    bridge.system_modules.execute.assert_not_awaited()


@pytest.mark.parametrize("operation", sorted(SYSTEM_LEAVES))
async def test_all_native_operations_share_existing_typed_authorized_dispatch(bridge, operation):
    native(bridge)
    arguments = dict(SAMPLES[operation])
    if operation == "apps.launch":
        app = Path(bridge.config.principals["local"].roots[0]) / "Owned.app"
        app.mkdir()
        arguments["app_path"] = str(app)
    events = []

    async def running(evidence):
        events.append(evidence)

    result = await bridge.execute(
        {
            "id": "owned-system-test",
            "principal": "local",
            "operation": operation,
            "args": arguments,
        },
        running,
        running,
    )
    assert result == {"effect": "fixture_only"}
    bridge.system_modules.execute.assert_awaited_once()
    invocation = bridge.system_modules.execute.await_args
    assert invocation.args[0] == operation
    assert invocation.kwargs == {"principal": "local", "task_id": "owned-system-test"}
    assert events[0]["effect_attempted"] == (operation not in SYSTEM_READ_OPERATIONS)


@pytest.mark.parametrize("operation", sorted(SYSTEM_LEAVES))
async def test_new_native_routes_do_not_bypass_missing_central_capability(bridge, operation):
    native(bridge)
    bridge.config.principals["local"].capabilities.remove(OPERATIONS[operation].capability)
    with pytest.raises(BridgeError):
        await bridge.execute(
            {
                "id": "denied",
                "principal": "local",
                "operation": operation,
                "args": SAMPLES[operation],
            },
            AsyncMock(),
            AsyncMock(),
        )
    bridge.system_modules.execute.assert_not_awaited()


async def test_missing_native_app_cannot_be_enabled_by_full_policy(bridge):
    native(bridge)
    bridge.macos.capability_probe.native_metadata = lambda: {
        "available": False,
        "reason": "missing_app",
    }
    with pytest.raises(BridgeError) as error:
        await bridge.execute(
            {"id": "missing", "principal": "local", "operation": "system.info", "args": {}},
            AsyncMock(),
            AsyncMock(),
        )
    assert error.value.code == "macos_capability_unavailable"
    bridge.system_modules.execute.assert_not_awaited()


def test_native_schemas_and_operation_properties_are_complete():
    assert set(SAMPLES) == set(SYSTEM_LEAVES)
    assert set(SYSTEM_LEAVES) <= set(INPUTS) <= set(OPERATIONS)
    for operation in SYSTEM_LEAVES:
        assert (OPERATIONS[operation].effect == "read") == (operation in SYSTEM_READ_OPERATIONS)


@pytest.mark.parametrize("pid", [0, -1, 2**31, 2**64, True])
def test_app_pid_model_never_reaches_native_integer_overflow(pid):
    with pytest.raises(ValidationError):
        ApplicationTargetInput(pid=pid, expected_started_at=123.0)


def test_element_mutation_requires_typed_value_and_exact_worker_generation():
    with pytest.raises(ValidationError):
        AccessibilitySetInput(
            **{**ELEMENT, "worker_generation": "other"}, attribute="focused", value=True
        )
    with pytest.raises(ValidationError):
        AccessibilitySetInput(**ELEMENT, attribute="focused", value="true")


@pytest.mark.parametrize("value", [[], None, 1, "wrong", {"source_commit": "wrong"}])
def test_installed_manifest_wrong_shapes_fail_closed(tmp_path, value):
    package = tmp_path / "release/source/.venv/lib/python3.11/site-packages/kirabridge/bridge.py"
    package.parent.mkdir(parents=True)
    package.write_text("fixture")
    (tmp_path / "release/release.json").write_text(json.dumps(value))
    assert installed_source_commit(package) == ""


def test_installed_manifest_pins_commit_and_missing_manifest_is_not_dev(tmp_path):
    package = tmp_path / "release/source/.venv/lib/python3.11/site-packages/kirabridge/bridge.py"
    package.parent.mkdir(parents=True)
    package.write_text("fixture")
    assert installed_source_commit(package) == ""
    manifest = tmp_path / "release/release.json"
    manifest.write_text(json.dumps({"source_commit": "a" * 40}))
    assert installed_source_commit(package) == "a" * 40
    manifest.write_text("[" * 2000 + "]" * 2000)
    assert installed_source_commit(package) == ""


@pytest.mark.parametrize("operation", ["capture.window", "capture.display"])
def test_native_capture_uses_the_existing_validated_mcp_image_result(operation):
    data = (Path(__file__).parent / "fixtures/images/own-rgb-32x24.png").read_bytes()
    width, height = validate_png(data)
    task = {
        "id": "owned-image",
        "operation": operation,
        "state": "completed",
        "result": {
            "mime_type": "image/png",
            "image_data": base64.b64encode(data).decode(),
            "bytes": len(data),
            "width": width,
            "height": height,
            "content_sha256": hashlib.sha256(data).hexdigest(),
        },
    }
    response = image_task_result(task)
    assert "image_data" not in response.structuredContent["result"]
    assert response.content[1].type == "image"


def test_installed_native_contract_pins_both_local_bundle_and_binary(tmp_path):
    from kirabridge.platform_adapters.macos.system_identity import installed_native_contract

    root = tmp_path / "release"
    package = root / "source/.venv/lib/python3.11/site-packages/kirabridge/bridge.py"
    package.parent.mkdir(parents=True)
    package.write_text("fixture")
    manifest = root / "release.json"
    manifest.write_text(json.dumps({"source_commit": "a" * 40}))
    assert installed_native_contract(package) == {"expected_commit": ""}
    descriptor = {
        "schema": "kirabridge.native-app.v1",
        "path": "native/KiraBridge.app",
        "protocol": 1,
        "source_commit": "a" * 40,
        "binary_sha256": "b" * 64,
    }
    manifest.write_text(json.dumps({"source_commit": "a" * 40, "native_app": descriptor}))
    assert installed_native_contract(package) == {
        "app_path": root / "native/KiraBridge.app",
        "expected_commit": "a" * 40,
        "expected_binary_sha256": "b" * 64,
    }
    descriptor["path"] = "../../untrusted.app"
    manifest.write_text(json.dumps({"source_commit": "a" * 40, "native_app": descriptor}))
    assert installed_native_contract(package) == {"expected_commit": ""}


async def test_system_report_is_fixed_argv_and_retains_existing_output_ranges(bridge):
    native(bridge)
    bridge.macos.capability_probe.executable = lambda path: True
    bridge.terminal.execute = AsyncMock(
        return_value={
            "exit_code": 0,
            "timed_out": False,
            "terminated": False,
            "stdout": "{}",
            "stderr": "",
            "output_ranges": {"streams": {"stdout": {"bytes": 2, "complete": True}}},
        }
    )
    result = await bridge.execute(
        {
            "id": "owned-report",
            "principal": "local",
            "operation": "system.report",
            "args": {"report": "software"},
        },
        AsyncMock(),
        AsyncMock(),
    )
    assert result["success"] is True
    assert result["full_output"]["task_id"] == "owned-report"
    call = bridge.terminal.execute.await_args
    args = call.args[2]
    assert args.argv == [
        "/usr/sbin/system_profiler",
        "-json",
        "-detailLevel",
        "basic",
        "SPSoftwareDataType",
    ]
    assert call.kwargs["allow_any_executable"] is False
    assert result["output_ranges"]["streams"]["stdout"]["complete"]
    bridge.system_modules.execute.assert_not_awaited()


@pytest.mark.parametrize(
    "payload", [{"report": "software;echo BAD"}, {"report": "software", "argv": ["/bin/sh"]}]
)
def test_system_reports_cannot_supply_arbitrary_commands(payload):
    from kirabridge.system_reports import SystemReportInput

    with pytest.raises(ValidationError):
        SystemReportInput.model_validate(payload)
