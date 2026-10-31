"""Typed process selectors and pure native guards; never signal a real process."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from kirabridge.platform_adapters.macos.system_models import SYSTEM_INPUTS
from kirabridge.platform_adapters.macos.system_services_models import SERVICE_INPUTS


@pytest.mark.parametrize(
    "operation,arguments",
    [
        ("system.processes", {"include_system": True, "offset": 0, "limit": 500}),
        ("system.processes", {"offset": 500, "expected_revision": "a" * 64}),
        ("system.process", {"pid": 123, "expected_start": "1700000000.123456"}),
        ("system.signal", {"pid": 123, "expected_start": "1700000000.123456", "signal": "TERM"}),
        ("system.signal", {"pid": 123, "expected_start": "1700000000.123456", "signal": "INT"}),
        ("system.signal", {"pid": 123, "expected_start": "1700000000.123456", "signal": "HUP"}),
        ("system.signal", {"pid": 123, "expected_start": "1700000000.123456", "signal": "KILL"}),
    ],
)
def test_service_models_use_existing_system_registry(operation, arguments):
    assert SYSTEM_INPUTS[operation] is SERVICE_INPUTS[operation]
    assert SERVICE_INPUTS[operation].model_validate(arguments)


@pytest.mark.parametrize(
    "operation,arguments",
    [
        ("system.processes", {"offset": 1}),
        ("system.processes", {"limit": 501}),
        ("system.processes", {"include_system": "yes"}),
        ("system.process", {"pid": -1, "expected_start": "1700000000.123456"}),
        ("system.process", {"pid": 0, "expected_start": "1700000000.123456"}),
        ("system.process", {"pid": 2**31, "expected_start": "1700000000.123456"}),
        ("system.process", {"pid": True, "expected_start": "1700000000.123456"}),
        ("system.process", {"pid": 123}),
        ("system.process", {"pid": 123, "expected_start": 1700000000.123456}),
        ("system.signal", {"pid": 123, "expected_start": "1700000000.123456", "signal": "USR1"}),
        (
            "system.signal",
            {"pid": 123, "expected_start": "1700000000.123456", "signal": "TERM", "group": True},
        ),
        (
            "system.signal",
            {"pid": 123, "expected_start": "1700000000.123456", "signal": "TERM", "uid": 0},
        ),
        (
            "system.signal",
            {
                "pid": 123,
                "expected_start": "1700000000.123456",
                "signal": "TERM",
                "_principal": "root",
            },
        ),
    ],
)
def test_invalid_process_ownership_group_and_identity_selectors_refuse(operation, arguments):
    with pytest.raises(ValidationError):
        SERVICE_INPUTS[operation].model_validate(arguments)


@pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which("xcrun"),
    reason="Public sysctl process metadata is macOS-only",
)
def test_native_process_primitive_guards_without_signals(tmp_path):
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / "service-guards"
    sources = [
        root / "tests/fixtures/system_services/main.swift",
        root / "integrations/desktop/SystemServices.swift",
        root / "integrations/desktop/SystemBridge.swift",
        root / "integrations/desktop/SystemControl.swift",
    ]
    command = ["xcrun", "swiftc", "-swift-version", "5", *map(str, sources), "-o", str(binary)]
    for framework in (
        "Cocoa",
        "ApplicationServices",
        "CryptoKit",
        "ScreenCaptureKit",
        "UserNotifications",
        "ImageIO",
        "UniformTypeIdentifiers",
        "SystemConfiguration",
    ):
        command.extend(["-framework", framework])
    compiled = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "signals_sent=0" in result.stdout
