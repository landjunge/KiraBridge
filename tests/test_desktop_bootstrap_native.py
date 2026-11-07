"""Foundation-only Swift bootstrap fixtures; no AppKit, installed launcher or GUI."""

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def bootstrap_harness(tmp_path_factory):
    if sys.platform != "darwin" or not shutil.which("xcrun"):
        pytest.skip("Private Foundation process fixture requires Darwin Swift")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path_factory.mktemp("owned-bootstrap") / "bootstrap-fixture"
    # Compile the actual Foundation seam, excluding all AppKit/top-level app code.
    source = (root / "integrations/desktop/main.swift").read_text()
    assert source.count("// MARK: Desktop UI") == 1
    runtime = binary.parent / "DesktopRuntime.swift"
    runtime.write_text(source.split("// MARK: Desktop UI", 1)[0])
    compiled = subprocess.run(
        [
            "xcrun",
            "swiftc",
            "-swift-version",
            "5",
            "-parse-as-library",
            "-target",
            f"{platform.machine()}-apple-macosx12.0",
            str(runtime),
            str(root / "tests/fixtures/desktop_bootstrap/BootstrapHarness.swift"),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert compiled.returncode == 0, compiled.stderr
    return binary


@pytest.mark.parametrize("scenario", ["success", "stderr_pressure"])
def test_bootstrap_drains_both_owned_pipes(bootstrap_harness, scenario):
    result = subprocess.run(
        [str(bootstrap_harness), scenario], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["success"] is True
    assert observed["bytes"] == len(b'{"login_file":"private-fixture"}')
    assert observed["elapsed"] < 1.5


@pytest.mark.parametrize(
    "scenario,kind",
    [
        ("stdout_limit", "output_limit"),
        ("stderr_limit", "output_limit"),
        ("sleep", "timeout"),
        ("ignore_term", "timeout"),
        ("nonzero", "process_failed"),
    ],
)
def test_bootstrap_bounds_output_and_owns_termination(bootstrap_harness, scenario, kind):
    result = subprocess.run(
        [str(bootstrap_harness), scenario], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["success"] is False
    assert observed["kind"] == kind
    assert observed["cleanup_confirmed"] is True
    assert observed["elapsed"] < 1.5
