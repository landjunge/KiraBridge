"""Safe native failure details via in-memory workers; no app or input is started."""

import json

import pytest
from conftest import request
from test_macos_system_transport import COMMIT, CONTRACT, GENERATION, response, transport

from kirabridge.bridge_core.models import BridgeError, UncertainExecution

CASES = [
    ("windows.focus", "Window raise outcome is unknown", True, "window_raise"),
    ("windows.focus", "Window activation outcome is unknown", True, "application_activation"),
    (
        "windows.focus",
        "Application identity changed after window raise",
        True,
        "target_revalidation",
    ),
    (
        "keyboard.key",
        "Physical modifier/system key is unsupported",
        False,
        "physical_key_validation",
    ),
    (
        "keyboard.key",
        "Current input source/layout identity is invalid",
        False,
        "keyboard_layout_validation",
    ),
    (
        "keyboard.key",
        "Current keyboard layout exceeds its bounded limit",
        False,
        "keyboard_layout_validation",
    ),
    ("keyboard.inspect", "Keyboard app is not frontmost", False, "frontmost_check"),
    (
        "keyboard.inspect",
        "Exact focused window/field is unavailable",
        False,
        "focused_window_lookup",
    ),
]


@pytest.mark.parametrize("operation,message,unknown,stage", CASES)
async def test_validated_failure_keeps_safe_stage_and_helper_binding(
    monkeypatch, operation, message, unknown, stage
):
    code = "macos_focus_unknown" if operation == "windows.focus" else "keyboard_unsupported"
    worker, child, calls = transport(
        monkeypatch,
        lambda req, proc: response(
            req, proc, error={"code": code, "message": message, "effect_unknown": unknown}
        ),
    )
    try:
        with pytest.raises(BridgeError) as caught:
            await worker.request(operation, {}, principal="fixture-owner")
        assert caught.value.code == code
        assert isinstance(caught.value, UncertainExecution) is unknown
        detail = getattr(caught.value, "native_failure", None)
        assert detail is not None, "Validated native failure stage was discarded"
        observed = detail.model_dump()
        assert observed["stage"] == stage
        assert observed["operation"] == operation
        assert observed["backend_effect_unknown"] is unknown
        assert observed["helper_pid"] == child.pid
        assert observed["helper_generation"] == GENERATION
        assert observed["helper_source_commit"] == COMMIT
        assert observed["contract_binary_sha256"] == CONTRACT["binary_sha256"]
        assert observed["request_id"] == child.requests[0]["request_id"]
        assert message not in json.dumps(observed)
        assert len(calls) == len(child.requests) == 1
    finally:
        await worker.close()


@pytest.mark.parametrize(
    "message",
    ["private/path/token/example-secret", None, {"secret": "private/path/token/example-secret"}],
)
async def test_unrecognized_error_text_never_becomes_evidence(monkeypatch, message):
    private = "private/path/token/example-secret"
    worker, _, _ = transport(
        monkeypatch,
        lambda req, proc: response(
            req,
            proc,
            error={"code": "keyboard_unsupported", "message": message, "effect_unknown": False},
        ),
    )
    try:
        with pytest.raises(BridgeError) as caught:
            await worker.request("keyboard.key", {}, principal="fixture-owner")
        detail = getattr(caught.value, "native_failure", None)
        assert detail is not None
        assert detail.stage == "unspecified"
        assert private not in str(caught.value) + detail.model_dump_json()
        assert CONTRACT["executable"] not in detail.model_dump_json()
    finally:
        await worker.close()


async def test_known_message_cannot_classify_another_operation(monkeypatch):
    worker, _, _ = transport(
        monkeypatch,
        lambda req, proc: response(
            req,
            proc,
            error={
                "code": "macos_focus_unknown",
                "message": "Window raise outcome is unknown",
                "effect_unknown": True,
            },
        ),
    )
    try:
        with pytest.raises(UncertainExecution) as caught:
            await worker.request("keyboard.key", {}, principal="fixture-owner")
        assert caught.value.native_failure.stage == "unspecified"
    finally:
        await worker.close()


async def test_unbound_error_cannot_supply_trusted_failure_details(monkeypatch):
    worker, _, _ = transport(
        monkeypatch,
        lambda req, proc: response(
            req,
            proc,
            helper_delta={"pid": proc.pid + 1},
            error={
                "code": "macos_focus_unknown",
                "message": "Window raise outcome is unknown",
                "effect_unknown": True,
            },
        ),
    )
    try:
        with pytest.raises(UncertainExecution) as caught:
            await worker.request("windows.focus", {}, principal="fixture-owner")
        assert caught.value.code == "system_operation_unknown"
        assert getattr(caught.value, "native_failure", None) is None
    finally:
        await worker.close()


@pytest.mark.parametrize(
    "operation,code,message,unknown,arguments",
    [
        (
            "windows.focus",
            "macos_focus_unknown",
            "Window raise outcome is unknown",
            True,
            {"ax_identifier": "fixture-window", "expected_pid": 321, "expected_start": "1.0"},
        ),
        (
            "keyboard.key",
            "keyboard_unsupported",
            "Physical modifier/system key is unsupported",
            False,
            {
                "target": {
                    "pid": 321,
                    "expected_started_at": 1.0,
                    "target_token": "a" * 32,
                    "helper_pid": 123,
                    "worker_generation": GENERATION,
                    "expected_revision": "b" * 64,
                },
                "key": {"key_code": 56},
            },
        ),
    ],
)
async def test_native_failure_survives_task_readback_without_reclassification_or_retry(
    bridge, monkeypatch, operation, code, message, unknown, arguments
):
    # Exercise the real TaskManager/store with a test-only executor and an
    # in-memory child. No platform preflight, native child or OS input is run.
    worker, child, calls = transport(
        monkeypatch,
        lambda req, proc: response(
            req, proc, error={"code": code, "message": message, "effect_unknown": unknown}
        ),
    )
    bridge.config.principals["local"].capabilities.append("keyboard.execute")
    bridge.tasks.preflight = None

    async def execute(task, running, progress):
        await running({"effect_attempted": True, "automatic_retry": False})
        return await worker.request(operation, task["args"], principal=task["principal"])

    bridge.tasks.executor = execute
    value = request(operation, arguments, task_id="fixture-native-failure")
    token = bridge.security.grant("local", value)
    bridge.tasks.enqueue("local", value, token)
    task = bridge.store.claim(bridge.tasks.owner, bridge.config.lease_seconds, native_visible=False)
    assert task is not None
    try:
        await bridge.tasks._execute(task)
        observed = bridge.task("local", value.task_id)
        assert observed["state"] == "unknown"
        assert observed["finished"] is None
        assert observed["error"] == {"code": code}
        assert observed["evidence"]["native_failure"]["backend_effect_unknown"] is unknown
        assert observed["evidence"]["native_failure"]["helper_pid"] == child.pid
        assert observed["evidence"]["safe_to_retry"] is False
        assert observed["evidence"]["automatic_retry"] is False
        assert observed["evidence"]["last_observation"]["effect_attempted"] is True
        assert message not in json.dumps(observed)
        # Reusing the exact task/idem key only reads the original uncertainty.
        assert bridge.tasks.enqueue("local", value, "")["state"] == "unknown"
        with pytest.raises(BridgeError) as refused:
            bridge.tasks.retry("local", value.task_id, value, "")
        assert refused.value.code == "unsafe_retry"
        assert len(calls) == len(child.requests) == 1
    finally:
        await worker.close()
