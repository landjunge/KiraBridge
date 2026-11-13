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
        ({"origin": "http://127.0.0.1:8765"}, "invalid"),
        ({"origin": "http://127.0.0.1:8766"}, "invalid"),
        ({"origin": "http://127.0.0.1:8767"}, "invalid"),
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


def test_receipt_accepts_a_canonical_path_through_a_symlinked_alias(isolated_harness, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    receipt = _receipt(real)
    assert _run(isolated_harness, alias, "receipt:" + receipt) == "http://127.0.0.1:54321"


def test_receipt_rejects_a_login_file_outside_or_escaping_through_a_symlink(
    isolated_harness, tmp_path
):
    owned = tmp_path / "owned"
    owned.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (owned / "escape").symlink_to(outside, target_is_directory=True)
    assert (
        _run(
            isolated_harness,
            owned,
            "receipt:" + _receipt(tmp_path, login_file="/private/other/approval-login.html"),
        )
        == "invalid"
    )
    assert (
        _run(
            isolated_harness,
            owned,
            "receipt:" + _receipt(owned, login_file=str(owned / "escape/approval-login.html")),
        )
        == "invalid"
    )
    missing = json.dumps({"isolated": True, "origin": "http://127.0.0.1:54321"})
    assert _run(isolated_harness, owned, "receipt:" + missing) == "invalid"


def test_start_isolated_reads_one_line_and_owns_the_child(isolated_harness, tmp_path):
    line = _receipt(tmp_path)
    output = _run(isolated_harness, tmp_path, "start", line).splitlines()
    assert output[0] == "started http://127.0.0.1:54321 true"
    assert output[1] == "stopped false"


def test_start_isolated_keeps_draining_stderr_past_the_old_limit(isolated_harness, tmp_path):
    output = _run(isolated_harness, tmp_path, "stderr_flood", _receipt(tmp_path))
    assert output.splitlines() == [
        "started http://127.0.0.1:54321",
        "stopped",
    ]


def test_start_isolated_times_out_and_stops_the_child(isolated_harness, tmp_path):
    assert _run(isolated_harness, tmp_path, "timeout") == "timeout"


def test_start_isolated_fails_fast_on_eof_with_a_still_running_child(isolated_harness, tmp_path):
    output = _run(isolated_harness, tmp_path, "eof_live").splitlines()
    assert output[0].startswith("failed ")
    assert float(output[0].split()[1]) < 4


def test_start_isolated_fails_when_the_child_exits_without_a_receipt(isolated_harness, tmp_path):
    assert _run(isolated_harness, tmp_path, "eof") == "failed"


def test_owned_handle_is_adopted_before_receipt_validation(isolated_harness, tmp_path):
    assert _run(isolated_harness, tmp_path, "owned", '{"isolated":false}') == "failed true"


def test_isolated_child_environment_is_a_narrow_positive_allowlist(isolated_harness, tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    keys, pythonpath = _run(isolated_harness, tmp_path, "env", str(root)).split("|")
    allowed = set(keys.split(","))
    assert {"PATH", "HOME", "LANG"} <= allowed
    assert allowed <= {
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "USER",
        "LOGNAME",
        "SHELL",
        "PYTHONPATH",
        "PYTHONDONTWRITEBYTECODE",
    }
    assert "SECRET_MARKER" not in allowed
    assert "KIRABRIDGE_LOCAL_TOKEN" not in allowed
    assert "KIRABRIDGE_CONFIG" not in allowed
    assert pythonpath.endswith("/source/src")
