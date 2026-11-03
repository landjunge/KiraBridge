# Serialization boundary regression only; no subprocesses, installer or input.
param([string]$Runner=(Join-Path $PSScriptRoot '..\scripts\windows_guest_runner.ps1'))
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Runner syntax invalid' }
$assignment=$ast.Find({param($node)
    $node -is [Management.Automation.Language.AssignmentStatementAst] -and
    $node.Left.Extent.Text -eq '$quoted'
},$true)
if (-not $assignment) { throw 'Native argument serializer missing' }
$cases=@(
    @{arguments=@('/d','/c','exit 0'); expected='/d /c "exit 0"'},
    @{arguments=@('-m','pip','install','--no-index'); expected='-m pip install --no-index'},
    @{arguments=@(''); expected='""'},
    @{arguments=@('C:\folder with space\'); expected='"C:\folder with space\\"'}
)
foreach ($case in $cases) {
    $Arguments=$case.arguments
    Invoke-Expression $assignment.Extent.Text
    if (($quoted -join ' ') -cne $case.expected) {
        throw 'Process argument serialization differs from native command-line contract'
    }
}
foreach ($invalid in @('embedded"quote',"line`nbreak")) {
    $Arguments=@($invalid);$refused=$false
    try { Invoke-Expression $assignment.Extent.Text } catch { $refused=$true }
    if (-not $refused) { throw 'Unsupported command-line characters were accepted' }
}
@{passed=$true; cases=$cases.Count; unsupported_characters_refused=$true;
    native_windows_execution=$false}|ConvertTo-Json -Compress
