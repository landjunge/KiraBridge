"""Explicitly isolated Live start: exact origin binding and owned child process."""

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def isolated_harness(tmp_path_factory):
    if sys.platform != "darwin" or not shutil.which("xcrun"):
        pytest.skip("Foundation isolated-start fixture requires Darwin Swift")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path_factory.mktemp("isolated-start") / "isolated-fixture"
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
            str(root / "tests/fixtures/desktop_bootstrap/IsolatedHarness.swift"),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    return binary


def _run(harness, directory, mode, line=None):
    arguments = [str(harness), str(directory), mode]
    if line is not None:
        arguments.append(line)
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _receipt(directory, **overrides):
    value = {
        "isolated": True,
        "origin": "http://127.0.0.1:54321",
        "login_file": str(directory / "approval-login.html"),
    }
    value.update(overrides)
    return json.dumps(value)


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({}, "http://127.0.0.1:54321"),
        ({"origin": "http://127.0.0.1:8766"}, "invalid"),
        ({"origin": "https://127.0.0.1:54321"}, "invalid"),
        ({"origin": "http://127.0.0.1"}, "invalid"),
        ({"origin": "http://localhost:54321"}, "invalid"),
        ({"origin": "http://192.168.1.5:54321"}, "invalid"),
        ({"origin": "http://user:pass@127.0.0.1:54321"}, "invalid"),
        ({"isolated": False}, "invalid"),
        ({"isolated": "yes"}, "invalid"),
    ],
)
def test_isolated_receipt_requires_exact_loopback_origin(
    isolated_harness, tmp_path, overrides, expected
):
    output = _run(isolated_harness, tmp_path, "receipt:" + _receipt(tmp_path, **overrides))
    assert output == expected


def test_isolated_receipt_keeps_the_login_file_inside_its_private_directory(
    isolated_harness, tmp_path
):
    outside = _receipt(tmp_path, login_file="/private/other/approval-login.html")
    assert _run(isolated_harness, tmp_path, "receipt:" + outside) == "invalid"
    missing = json.dumps({"isolated": True, "origin": "http://127.0.0.1:54321"})
    assert _run(isolated_harness, tmp_path, "receipt:" + missing) == "invalid"


def test_start_isolated_reads_one_line_and_owns_the_child(isolated_harness, tmp_path):
    line = _receipt(tmp_path)
    output = _run(isolated_harness, tmp_path, "start", line).splitlines()
    assert output[0] == "started http://127.0.0.1:54321 true"
    assert output[1] == "stopped false"


def test_start_isolated_times_out_and_stops_the_child(isolated_harness, tmp_path):
    assert _run(isolated_harness, tmp_path, "timeout") == "timeout"


def test_start_isolated_fails_when_the_child_exits_without_a_receipt(isolated_harness, tmp_path):
    assert _run(isolated_harness, tmp_path, "eof") == "failed"
