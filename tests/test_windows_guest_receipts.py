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
    result = run_receipt_check(
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
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip())
    assert report == {
        "scenarios": 7,
        "native_commands": 0,
        "receipt_replay_guards": "passed",
        "parser": "passed",
    }


def run_receipt_check(command):
    """Keep the original budget and expose the last observed fixture boundary."""
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    except subprocess.TimeoutExpired as error:
        stderr = error.stderr or b""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        phases = [
            line.partition("receipt-check-phase:")[2].strip()
            for line in stderr.splitlines()
            if line.startswith("receipt-check-phase:")
        ]
        phase = phases[-1] if phases else "not_observed_before_fixture_start"
        pytest.fail(
            "PowerShell receipt check exceeded unchanged 30s budget; "
            "last fixture phase=" + phase + "; receipt guards not accepted"
        )


@pytest.mark.parametrize(
    "stderr,phase",
    [
        (None, "not_observed_before_fixture_start"),
        (b"receipt-check-phase:started\nreceipt-check-phase:parsed\n", "parsed"),
        ("receipt-check-phase:scenario-unknown\n", "scenario-unknown"),
    ],
)
def test_receipt_timeout_preserves_budget_and_reports_last_observed_phase(
    monkeypatch, stderr, phase
):
    calls = []

    def timeout(command, **kwargs):
        calls.append(kwargs)
        raise subprocess.TimeoutExpired(command, 30, stderr=stderr)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(pytest.fail.Exception, match="last fixture phase=" + phase):
        run_receipt_check(["fixture-host"])
    assert calls == [{"capture_output": True, "text": True, "timeout": 30, "check": False}]
