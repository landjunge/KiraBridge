param([Parameter(Mandatory=$true)][string]$RunnerPath,
      [Parameter(Mandatory=$true)][string]$TempRoot)
$ErrorActionPreference='Stop'
$errors=$null
$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($RunnerPath,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Guest runner syntax invalid'}
$names=@('New-PrivateReceipt','Log-Tail','Run-Once')
foreach($name in $names){
    $node=$ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]},$false) |
        Where-Object Name -eq $name | Select-Object -First 1
    if(-not $node){throw ('Missing runner function '+$name)}
    . ([ScriptBlock]::Create($node.Extent.Text))
}
$Utf8=New-Object Text.UTF8Encoding($false)
function Assert($Condition,[string]$Message){if(-not $Condition){throw $Message}}
function Event([string]$Phase) { }
function Publish([string]$Id,[string]$Path){
    $script:Published++
    Assert (Test-Path -LiteralPath $Path) 'Report must exist before publication'
}
function Invoke-Bounded([string]$Program,[string[]]$Arguments,[string]$Name,[int]$Seconds){
    $script:Invoked++
    $attempt=Get-Content -LiteralPath (Join-Path $Attempts ($Name+'.json')) -Raw | ConvertFrom-Json
    Assert ($attempt.manifest_sha256 -ceq $ManifestHash) 'Launch preceded receipt persistence'
    if($script:SimulateUnknown){throw 'Simulated uncertain native timeout'}
    $stdout=Join-Path $Work ($Name+'-stdout.txt')
    $stderr=Join-Path $Work ($Name+'-stderr.txt')
    [IO.File]::WriteAllText($stdout,'fixture',$Utf8)
    [IO.File]::WriteAllText($stderr,'',$Utf8)
    return @{exit_code=0;pid=123;stdout=$stdout;stderr=$stderr}
}
function Scenario([string]$Name){
    $script:Work=Join-Path $TempRoot $Name
    $script:Attempts=Join-Path $Work 'attempts'
    New-Item -ItemType Directory -Force $Attempts | Out-Null
    $script:ManifestHash='a'*64
    $script:RunId='f'*32
    $script:Python='must-not-run-native.exe'
    $script:Invoked=0
    $script:Published=0
    $script:SimulateUnknown=$false
}
function Prior([string]$AttemptHash,[string]$ReportHash,[int]$ExitCode=0){
    New-PrivateReceipt (Join-Path $Attempts 'fixture.json') (
        @{phase='fixture';manifest_sha256=$AttemptHash}|ConvertTo-Json -Compress)
    New-PrivateReceipt (Join-Path $Work 'fixture-report.json') (
        @{phase='fixture';manifest_sha256=$ReportHash;exit_code=$ExitCode}|ConvertTo-Json -Compress)
}
function Must-Refuse {
    $caught=$false
    try {Run-Once 'fixture' @('unused') 1 ''} catch {$caught=$true}
    Assert $caught 'Expected reconciliation failure'
    Assert ($Invoked -eq 0) 'Refused prior evidence must never launch a native command'
}
Scenario 'fresh'
Run-Once 'fixture' @('unused') 1 ''
Assert ($Invoked -eq 1 -and $Published -eq 1) 'New acceptance did not run exactly once'
Run-Once 'fixture' @('unused') 1 ''
Assert ($Invoked -eq 1 -and $Published -eq 2) 'Same successful payload must only republish'
$ManifestHash='b'*64
$caught=$false
try {Run-Once 'fixture' @('unused') 1 ''} catch {$caught=$true}
Assert ($caught -and $Invoked -eq 1 -and $Published -eq 2) 'Changed payload inherited prior success'
Scenario 'stale-attempt'
Prior ('b'*64) $ManifestHash
Must-Refuse
Assert ($Published -eq 0) 'Stale attempt must not publish as current'
Scenario 'stale-report'
Prior $ManifestHash ('b'*64)
Must-Refuse
Assert ($Published -eq 0) 'Stale report must not publish as current'
Scenario 'failed'
Prior $ManifestHash $ManifestHash 1
Must-Refuse
Scenario 'missing-report'
New-PrivateReceipt (Join-Path $Attempts 'fixture.json') (
    @{phase='fixture';manifest_sha256=$ManifestHash}|ConvertTo-Json -Compress)
Must-Refuse
Scenario 'unknown'
$SimulateUnknown=$true
$caught=$false
try {Run-Once 'fixture' @('unused') 1 ''} catch {$caught=$true}
Assert ($caught -and $Invoked -eq 1) 'Unknown native attempt unexpectedly succeeded'
$caught=$false
try {Run-Once 'fixture' @('unused') 1 ''} catch {$caught=$true}
Assert ($caught -and $Invoked -eq 1) 'Unknown native command was automatically replayed'
Scenario 'exclusive-write'
$path=Join-Path $Work 'receipt.json'
New-PrivateReceipt $path '{"first":true}'
$caught=$false
try {New-PrivateReceipt $path '{"second":true}'} catch {$caught=$true}
Assert ($caught -and [IO.File]::ReadAllText($path) -ceq '{"first":true}') 'Receipt overwritten'
'{"scenarios":7,"native_commands":0,"receipt_replay_guards":"passed","parser":"passed"}'
