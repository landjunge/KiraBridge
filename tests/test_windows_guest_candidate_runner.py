"""Execute the real Run-Once function with synthetic children under local PowerShell.

These are portable orchestration tests, never Windows/Win32 acceptance.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PWSH = shutil.which("pwsh")
RUNNER = Path(__file__).parents[1] / "scripts/windows_guest_runner.ps1"
pytestmark = pytest.mark.skipif(not PWSH, reason="Local PowerShell required; no download")

DRIVER = r"""
param([string]$Runner, [string]$WorkRoot, [string]$Case)
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Runner syntax error' }
$functions=$ast.FindAll({param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -in @('Run-Once','New-PrivateReceipt')},$true)
foreach ($function in $functions) { Invoke-Expression $function.Extent.Text }
$Work=$WorkRoot; $Attempts=Join-Path $Work 'attempts'
New-Item -ItemType Directory $Attempts | Out-Null
$Utf8=New-Object System.Text.UTF8Encoding($false)
$ManifestHash='a'*64; $manifest=@{source_commit='c'*40}; $RunId='d'*32
$CandidateVersion='0.8.0rc39'; $Python='synthetic-not-started'
if ($Case -eq 'legacy') { $CandidateVersion='' }
$script:NativeCalls=0; $script:Observations=0; $script:Publishes=0
$script:Context=@{candidate_version='0.8.0rc39';source_commit='c'*40;
    inventory_sha256='b'*64;evidence_platform='win32';runtime_module_count=2;
    runtime_module_sha256=@{fixture='e'*64};harness_sha256=@{fixture='f'*64};
    version_file_sha256=@{fixture='1'*64}}
$script:CandidateEvidence=$script:Context
function Observe-Candidate([string]$Phase) {
    if (-not $CandidateVersion) { return $null }
    $script:Observations++
    $value=$script:Context.Clone()
    if (($Case -eq 'changed-before' -and $Phase -like '*before') -or
        ($Case -eq 'changed-after' -and $Phase -like '*after')) {
        $value.inventory_sha256='2'*64
    }
    return $value
}
function Invoke-Bounded($Program,$Arguments,$Name,$Seconds) {
    $script:NativeCalls++
    if ($Case -eq 'unknown') { throw 'Synthetic lost native result' }
    $code=0; if ($Case -eq 'failed') { $code=1 }
    return @{exit_code=$code;pid=123;stdout='synthetic';stderr='synthetic'}
}
function Log-Tail($Path) { return 'Synthetic fixture: no Windows test executed' }
function Event($Phase) { }
function Publish($Id,$Path) { $script:Publishes++ }
if ($Case -eq 'earlier-unbound') {
    New-PrivateReceipt (Join-Path $Attempts 'core.json') (@{
        phase='core';manifest_sha256=$ManifestHash}|ConvertTo-Json -Compress)
    New-PrivateReceipt (Join-Path $Work 'core-report.json') (@{
        phase='core';manifest_sha256=$ManifestHash;exit_code=0;process_id=123
    }|ConvertTo-Json -Compress)
}
$firstError=$false; $secondError=$false
try { Run-Once 'core' @('fixture') 1 '' } catch { $firstError=$true }
$reportPath=Join-Path $Work 'core-report.json'
$firstBytes=[IO.File]::ReadAllText($reportPath)
try { Run-Once 'core' @('fixture') 1 '' } catch { $secondError=$true }
$report=Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
@{native_calls=$script:NativeCalls;observations=$script:Observations;
  publishes=$script:Publishes;first_error=$firstError;second_error=$secondError;
  report_unchanged=($firstBytes -ceq [IO.File]::ReadAllText($reportPath));
  report=$report}|ConvertTo-Json -Depth 80 -Compress
"""


@pytest.mark.parametrize(
    "case,calls,error",
    [
        ("success", 1, False),
        ("legacy", 1, False),
        ("changed-before", 0, True),
        ("changed-after", 1, True),
        ("earlier-unbound", 0, True),
        ("failed", 1, True),
        ("unknown", 1, True),
    ],
)
def test_actual_runner_at_most_once_and_source_change_boundaries(tmp_path, case, calls, error):
    driver = tmp_path / "drive-fixture.ps1"
    driver.write_text(DRIVER)
    result = subprocess.run(
        [
            PWSH,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(driver),
            "-Runner",
            str(RUNNER),
            "-WorkRoot",
            str(tmp_path),
            "-Case",
            case,
        ],
        capture_output=True,
        text=True,
        timeout=25,
        check=True,
    )
    value = json.loads(result.stdout)
    assert value["native_calls"] == calls
    assert value["first_error"] is error and value["second_error"] is error
    assert value["report_unchanged"]
    if case == "success":
        assert value["observations"] == 2 and value["publishes"] == 2
        assert value["report"]["evidence_platform"] == "win32"  # Mocked, explicitly synthetic.
        assert value["report"]["source_commit"] == "c" * 40
        assert value["report"]["harness_sha256"] == {"fixture": "f" * 64}
    elif case == "legacy":
        assert value["observations"] == 0
        assert "candidate_version" not in value["report"]
    elif case in {"changed-before", "changed-after", "unknown"}:
        assert value["report"]["status"] == "unknown_or_failed_no_retry"
