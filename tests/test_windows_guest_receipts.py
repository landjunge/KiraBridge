"""Execute the real receipt functions in installed PowerShell, without guest effects."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_guest_receipt_state_machine_rejects_stale_or_unknown_attempts(tmp_path):
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is required for executable bootstrap control-flow checks")
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-File",
            str(root / "tests/fixtures/windows_guest/receipt_checks.ps1"),
            "-RunnerPath",
            str(root / "scripts/windows_guest_runner.ps1"),
            "-TempRoot",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip())
    assert report == {
        "scenarios": 7,
        "native_commands": 0,
        "receipt_replay_guards": "passed",
        "parser": "passed",
    }
