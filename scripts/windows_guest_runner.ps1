param([Parameter(Mandatory=$true)][string]$BootstrapUrl)
$ErrorActionPreference = 'Stop'
$Base = $BootstrapUrl.TrimEnd('/')
if ($Base -notmatch '^http://10\.0\.2\.2:[0-9]{1,5}/[A-Za-z0-9_-]{16,128}$') {
    throw 'Invalid isolated bootstrap endpoint'
}
$Work = Join-Path $env:LOCALAPPDATA 'KiraBridgeDev'
New-Item -ItemType Directory -Force $Work | Out-Null
$Attempts = Join-Path $Work 'attempts'
New-Item -ItemType Directory -Force $Attempts | Out-Null
$Utf8 = New-Object System.Text.UTF8Encoding($false)

function Post-Json([string]$Route, [string]$Json) {
    $request = @{Method='Post'; Uri=($Base+'/'+$Route); Body=$Utf8.GetBytes($Json);
        ContentType='application/json; charset=utf-8'; TimeoutSec=30}
    Invoke-RestMethod @request | Out-Null
}
function Event([string]$Phase) {
    try { Post-Json 'events' (@{phase=$Phase; user=$env:USERNAME}|ConvertTo-Json -Compress) }
    catch { } # A report outage never repeats a native command.
}
function Digest([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function New-PrivateReceipt([string]$Path, [string]$Text) {
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try {
        $bytes=$Utf8.GetBytes($Text)
        $stream.Write($bytes,0,$bytes.Length)
        $stream.Flush($true) # Persist the attempt before any native command starts.
    }
    finally { $stream.Dispose() }
}
function Download-Verified($Entry, [string]$Root) {
    if ($Entry.path -notmatch '^(guest_runner\.ps1|source\.zip|python-installer\.exe|wheels/[A-Za-z0-9][A-Za-z0-9._+-]{0,200}\.whl)$' -or
        $Entry.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or [long]$Entry.bytes -le 0) {
        throw 'Invalid manifest file entry'
    }
    $target = Join-Path $Root $Entry.path
    New-Item -ItemType Directory -Force ([IO.Path]::GetDirectoryName($target)) | Out-Null
    if (Test-Path -LiteralPath $target) {
        if ((Digest $target) -ne $Entry.sha256.ToLowerInvariant() -or
            (Get-Item -LiteralPath $target).Length -ne [long]$Entry.bytes) {
            throw 'Existing staged file differs; explicit reconciliation required'
        }
        return $target
    }
    $temporary = $target+'.partial-'+[guid]::NewGuid().ToString('N')
    Invoke-WebRequest -UseBasicParsing -Uri ($Base+'/'+$Entry.path) -OutFile $temporary -TimeoutSec 240
    if ((Digest $temporary) -ne $Entry.sha256.ToLowerInvariant() -or
        (Get-Item -LiteralPath $temporary).Length -ne [long]$Entry.bytes) {
        throw 'Downloaded file digest or size mismatch'
    }
    [IO.File]::Move($temporary,$target)
    return $target
}
function Invoke-Bounded([string]$Program, [string[]]$Arguments, [string]$Name, [int]$Seconds) {
    $stdout=Join-Path $Work ($Name+'-stdout.txt')
    $stderr=Join-Path $Work ($Name+'-stderr.txt')
    if ((Test-Path $stdout) -or (Test-Path $stderr)) { throw 'Process evidence already exists' }
    $quoted = @($Arguments | ForEach-Object {
        if ($_ -match '["\r\n]') { throw 'Unsupported process argument' }
        '"'+$_+'"'
    })
    $process = Start-Process -FilePath $Program -ArgumentList $quoted -PassThru -WindowStyle Normal `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    if (-not $process.WaitForExit($Seconds*1000)) {
        Event ($Name+'_timeout_unknown_no_retry')
        throw 'Process timeout; original process may remain active, never replay automatically'
    }
    $process.WaitForExit()
    return @{exit_code=$process.ExitCode; pid=$process.Id; stdout=$stdout; stderr=$stderr}
}
function Log-Tail([string]$Path) {
    if (Test-Path $Path) {
        $text=[IO.File]::ReadAllText($Path)
        if ($text.Length -gt 64000) { return $text.Substring($text.Length-64000) }
        return $text
    }
    return ''
}
function Publish([string]$Id, [string]$Path) {
    Post-Json ('reports/'+$Id) ([IO.File]::ReadAllText($Path))
}
function Run-Once([string]$Name, [string[]]$Arguments, [int]$Seconds, [string]$Artifact) {
    $receipt=Join-Path $Attempts ($Name+'.json')
    $report=Join-Path $Work ($Name+'-report.json')
    if (Test-Path -LiteralPath $receipt) {
        Event ($Name+'_already_attempted_no_retry')
        $attempt=Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json
        if ($attempt.manifest_sha256 -cne $ManifestHash -or $attempt.phase -cne $Name) {
            throw 'Earlier attempt belongs to another payload; explicit reconciliation required'
        }
        if (-not (Test-Path -LiteralPath $report)) {
            throw 'Earlier attempt has no final report; explicit reconciliation required'
        }
        $earlier=Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
        if ($earlier.manifest_sha256 -cne $ManifestHash -or $earlier.phase -cne $Name) {
            throw 'Earlier report belongs to another payload; explicit reconciliation required'
        }
        Publish ($RunId+'-'+$Name) $report
        if ($null -eq $earlier.exit_code -or $earlier.exit_code -ne 0) {
            throw 'Earlier failed or uncertain acceptance blocks subsequent native checks'
        }
        return
    }
    New-PrivateReceipt $receipt (@{phase=$Name; started_at=[DateTime]::UtcNow.ToString('o');
        manifest_sha256=$ManifestHash; status='attempted_no_automatic_replay'}|ConvertTo-Json -Compress)
    try {
        $run=Invoke-Bounded $Python $Arguments $Name $Seconds
        $result=@{phase=$Name; exit_code=$run.exit_code; process_id=$run.pid;
            manifest_sha256=$ManifestHash; stdout=(Log-Tail $run.stdout); stderr=(Log-Tail $run.stderr)}
        if ($Artifact -and -not (Test-Path -LiteralPath $Artifact)) {
            throw 'Native acceptance artifact missing; do not repeat automatically'
        }
        if ($Artifact) {
            $result.artifact=Get-Content -LiteralPath $Artifact -Raw | ConvertFrom-Json
            $result.artifact_sha256=Digest $Artifact
        }
        $json=$result|ConvertTo-Json -Depth 80 -Compress
        New-PrivateReceipt $report $json
        Publish ($RunId+'-'+$Name) $report
        if ($run.exit_code -ne 0) {
            Event ($Name+'_failed_no_retry')
            throw 'Acceptance failed; stop subsequent native checks'
        }
    } catch {
        if (-not (Test-Path -LiteralPath $report)) {
            $failure=@{phase=$Name; status='unknown_or_failed_no_retry';
                manifest_sha256=$ManifestHash; error_type=$_.Exception.GetType().FullName;
                stdout=(Log-Tail (Join-Path $Work ($Name+'-stdout.txt')));
                stderr=(Log-Tail (Join-Path $Work ($Name+'-stderr.txt')))}
            $json=$failure|ConvertTo-Json -Compress
            New-PrivateReceipt $report $json
            try { Publish ($RunId+'-'+$Name) $report } catch { }
        }
        throw
    }
}

try {
    Event 'guest_runner_started'
    $manifestText=(Invoke-WebRequest -UseBasicParsing -Uri ($Base+'/manifest.json') -TimeoutSec 30).Content
    $manifest=$manifestText|ConvertFrom-Json
    if ($manifest.schema_version -ne 1 -or $manifest.python_version -notmatch '^\d+\.\d+\.\d+$') {
        throw 'Unsupported manifest'
    }
    $ManifestHash=([BitConverter]::ToString(
        [Security.Cryptography.SHA256]::Create().ComputeHash($Utf8.GetBytes($manifestText)))).Replace('-','').ToLowerInvariant()
    $Payload=Join-Path (Join-Path $Work 'payload') $ManifestHash
    New-Item -ItemType Directory -Force $Payload | Out-Null
    $entries=@{}
    foreach ($entry in $manifest.files) {
        if ($entries.ContainsKey($entry.path)) { throw 'Duplicate manifest path' }
        $entries[$entry.path]=$entry
        Download-Verified $entry $Payload | Out-Null
    }
    foreach ($required in @('guest_runner.ps1','source.zip','python-installer.exe')) {
        if (-not $entries.ContainsKey($required)) { throw 'Missing required manifest file' }
    }
    if ((Digest $PSCommandPath) -ne $entries['guest_runner.ps1'].sha256.ToLowerInvariant()) {
        throw 'Running guest bootstrap does not match the staged script'
    }
    Event 'all_payload_hashes_verified'
    $version=[Version]$manifest.python_version
    $PythonRoot=Join-Path $Work ('Python'+$version.Major+$version.Minor)
    $Python=Join-Path $PythonRoot 'python.exe'
    if (-not (Test-Path -LiteralPath $Python)) {
        $receipt=Join-Path $Attempts 'python-install.json'
        New-PrivateReceipt $receipt '{"phase":"python-install","status":"attempted"}'
        $installer=Join-Path $Payload 'python-installer.exe'
        $options=@('/quiet','InstallAllUsers=0',('TargetDir='+$PythonRoot),'PrependPath=0',
            'AppendPath=0','Include_launcher=0','InstallLauncherAllUsers=0','Include_test=0',
            'Include_doc=0','Include_pip=1','AssociateFiles=0','Shortcuts=0')
        $installed=Invoke-Bounded $installer $options 'python-install' 600
        if ($installed.exit_code -ne 0 -and $installed.exit_code -ne 3010) { throw 'Python installation failed' }
    }
    $actual=& $Python -I -c 'import platform; print(platform.python_version())'
    if ($LASTEXITCODE -ne 0 -or $actual.Trim() -ne $manifest.python_version) {
        throw 'Installed Python version differs from verified manifest'
    }
    foreach ($requirement in $manifest.requirements) {
        if ($requirement -notmatch '^[A-Za-z0-9_.-]+(\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9_.+!-]+$') {
            throw 'Unpinned requirement refused'
        }
    }
    if (@($manifest.requirements).Count -eq 0) { throw 'No pinned requirements' }
    $pipReceipt=Join-Path $Payload 'pip-completed.json'
    if (-not (Test-Path -LiteralPath $pipReceipt)) {
        $wheelhouse=Join-Path $Payload 'wheels'
        $options=@('-m','pip','install','--no-index','--find-links',$wheelhouse,
            '--disable-pip-version-check','--no-warn-script-location','--no-user')+@($manifest.requirements)
        $pip=Invoke-Bounded $Python $options ('pip-'+$ManifestHash.Substring(0,12)) 600
        if ($pip.exit_code -ne 0) { throw 'Offline dependency installation failed' }
        New-PrivateReceipt $pipReceipt '{"installed":true}'
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Source=Join-Path $Payload 'source'
    if (-not (Test-Path $Source)) {
        $archive=[IO.Compression.ZipFile]::OpenRead((Join-Path $Payload 'source.zip'))
        try {
            $prefix=[IO.Path]::GetFullPath($Source)+'\'
            foreach ($item in $archive.Entries) {
                $full=[IO.Path]::GetFullPath((Join-Path $Source $item.FullName))
                if (-not $full.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or
                    (($item.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000) {
                    throw 'Unsafe source archive entry'
                }
            }
        } finally { $archive.Dispose() }
        [IO.Compression.ZipFile]::ExtractToDirectory((Join-Path $Payload 'source.zip'),$Source)
    }
    if (-not (Test-Path (Join-Path $Source 'src\kirabridge'))) { throw 'Source archive layout invalid' }
    $env:PYTHONPATH=Join-Path $Source 'src'
    $env:PYTHONNOUSERSITE='1'
    Set-Location -LiteralPath $Source
    $runFile=Join-Path $Work 'run-id.txt'
    if (-not (Test-Path $runFile)) { New-PrivateReceipt $runFile ([guid]::NewGuid().ToString('N')) }
    $RunId=[IO.File]::ReadAllText($runFile).Trim()
    if ($RunId -notmatch '^[a-f0-9]{32}$') { throw 'Existing run identity invalid' }
    $baseTemp=Join-Path $Work ('pytest-tmp-'+$RunId)
    Run-Once 'core' @('-m','pytest','-q','--basetemp',$baseTemp,
        'tests/test_windows_core_native.py') 300 ''
    $keyboardOut=Join-Path $Work ('keyboard-'+$RunId+'.json')
    Run-Once 'keyboard' @('scripts/accept_windows_keyboard.py','--output',$keyboardOut) 180 $keyboardOut
    $mcpOut=Join-Path $Work ('mcp-'+$RunId+'.json')
    Run-Once 'mcp' @('scripts/accept_windows_mcp.py','--output',$mcpOut) 180 $mcpOut
    $previewOut=Join-Path $Work ('preview-'+$RunId+'.json')
    Run-Once 'preview' @('scripts/accept_windows_preview.py','--output',$previewOut) 180 $previewOut
    Event 'guest_checks_finished'
} catch {
    Event ('guest_runner_stopped_'+$_.Exception.GetType().Name)
    [IO.File]::WriteAllText((Join-Path $Work 'runner-status.txt'),
        ('failed_or_unknown_no_retry: '+$_.Exception.GetType().FullName),$Utf8)
    exit 1
}
