# Read-only process probes: no installer, key injection, VM actions or network.
# Keep every unique probe directory, raw log and JSON for original-run diagnosis.
param(
    [string]$Runner=(Join-Path $PSScriptRoot '..\scripts\windows_guest_runner.ps1'),
    [string]$Output,
    [string]$Python
)
$ErrorActionPreference='Stop'
$Work=Join-Path ([IO.Path]::GetTempPath()) ('KiraGuestProcessProbe-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $Work | Out-Null
if (-not $Output) { $Output=Join-Path $Work 'probe.json' }
$Utf8=New-Object Text.UTF8Encoding($false)
$evidence=[IO.File]::Open($Output,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
$script:LastProcessInfo=$null
$script:ProbeReport=@{state='started';passed=$false;probes=@();
    powershell_version=$PSVersionTable.PSVersion.ToString();
    native_windows=($env:OS -eq 'Windows_NT');probe_directory=$Work;output_path=$Output}

function Read-ProbeTail([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    try {
        $file=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
        try {
            $count=[int][Math]::Min(1024,$file.Length)
            $null=$file.Seek(-$count,[IO.SeekOrigin]::End)
            $bytes=New-Object byte[] $count
            $read=$file.Read($bytes,0,$count)
            return $Utf8.GetString($bytes,0,$read)
        } finally { $file.Dispose() }
    } catch { return '[not readable while original writer retains the file]' }
}
function Save-Probe {
    $script:ProbeReport.current_process=$script:LastProcessInfo
    $tails=@{}
    foreach ($engine in @('cmd','python')) {
        foreach ($code in @(0,17)) {
            foreach ($stream in @('stdout','stderr')) {
                $name=$engine+'-exit-'+$code+'-'+$stream
                $tails[$name]=Read-ProbeTail (Join-Path $Work ($name+'.txt'))
            }
        }
    }
    $script:ProbeReport.log_tails=$tails
    $bytes=$Utf8.GetBytes(($script:ProbeReport|ConvertTo-Json -Depth 16 -Compress))
    $evidence.Position=0;$evidence.SetLength(0)
    $evidence.Write($bytes,0,$bytes.Length);$evidence.Flush($true)
}
function Event([string]$Phase) {
    $script:ProbeReport.last_event=$Phase
    Save-Probe
}
if ($env:OS -ne 'Windows_NT') {
    function Start-Process {
        param($FilePath,$ArgumentList,[switch]$PassThru,$WindowStyle,
            $RedirectStandardOutput,$RedirectStandardError)
        Microsoft.PowerShell.Management\Start-Process -FilePath $FilePath `
            -ArgumentList $ArgumentList -PassThru `
            -RedirectStandardOutput $RedirectStandardOutput `
            -RedirectStandardError $RedirectStandardError
    }
}
$probeFailed=$false
try {
    Save-Probe
    $tokens=$null;$parseErrors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$tokens,[ref]$parseErrors)
    if ($parseErrors.Count) { throw 'Guest runner PowerShell syntax is invalid' }
    $function=$ast.Find({param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Invoke-Bounded'
    },$false)
    if (-not $function) { throw 'Native process helper missing' }
    Invoke-Expression $function.Extent.Text
    if (-not $Python) {
        if ($env:OS -eq 'Windows_NT') {
            $Python=Join-Path $env:LOCALAPPDATA 'KiraBridgeDev\Python314\python.exe'
        } else { $Python=(Get-Command python3 -CommandType Application | Select-Object -First 1).Source }
    }
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Installed Python missing' }
    $engineFailed=@{}
    foreach ($engine in @('cmd','python')) {
        foreach ($expected in @(0,17)) {
            if ($engineFailed[$engine]) {
                $script:ProbeReport.probes+=@{engine=$engine;expected=$expected;passed=$false;
                    state='not_started_after_prior_engine_failure'}
                continue
            }
            $step=$engine+'-exit-'+$expected
            $script:ProbeReport.state='running_'+$step
            $script:LastProcessInfo=$null
            Save-Probe
            try {
                if ($engine -eq 'python') {
                    $program=$Python;$arguments=@('-I','-c',('raise SystemExit('+$expected+')'))
                } elseif ($env:OS -eq 'Windows_NT') {
                    $program=$env:ComSpec;$arguments=@('/d','/c',('exit '+$expected))
                } else { $program='/bin/sh';$arguments=@('-c',('exit '+$expected)) }
                $result=Invoke-Bounded $program $arguments $step 15
                if ($result.exit_code -isnot [int] -or $result.exit_code -ne $expected) {
                    throw 'Native process exit code was missing or misreported'
                }
                if (-not $script:LastProcessInfo.handle_retained) { throw 'Original handle not retained' }
                $script:ProbeReport.probes+=@{engine=$engine;expected=$expected;
                    actual=$result.exit_code;passed=$true;state='completed';
                    handle_retained=$script:LastProcessInfo.handle_retained;
                    pid=$script:LastProcessInfo.pid;
                    creation_utc=$script:LastProcessInfo.creation_utc;
                    creation_filetime_100ns=$script:LastProcessInfo.creation_filetime_100ns}
            } catch {
                $probeFailed=$true;$engineFailed[$engine]=$true
                $script:ProbeReport.probes+=@{engine=$engine;expected=$expected;passed=$false;
                    state='failed_no_automatic_replay';process=$script:LastProcessInfo;
                    exception_type=$_.Exception.GetType().FullName;
                    script_line=$_.InvocationInfo.ScriptLineNumber}
            }
            Save-Probe
        }
    }
    if ($probeFailed) { $script:ProbeReport.state='failed_no_automatic_replay' }
    else { $script:ProbeReport.state='completed';$script:ProbeReport.passed=$true }
} catch {
    $probeFailed=$true
    $script:ProbeReport.state='failed_no_automatic_replay'
    $script:ProbeReport.passed=$false
    $script:ProbeReport.exception_type=$_.Exception.GetType().FullName
    $script:ProbeReport.script_line=$_.InvocationInfo.ScriptLineNumber
} finally {
    Save-Probe
    $evidence.Dispose()
}
# Final output only: both independent command parsers must pass before native
# keyboard acceptance. A failed engine is never retried, killed or hidden.
$script:ProbeReport|ConvertTo-Json -Depth 16 -Compress
if ($probeFailed) { exit 1 }
