# A child-process/exit-code probe only. No installer, keys, VM actions or network.
# Run on Windows PowerShell 5.1 for the native regression proof. PowerShell 7 on
# macOS also checks syntax and the success/failure exit-code distinction, but
# cannot reproduce the Windows 5.1 Start-Process implementation defect.
param([string]$Runner = (Join-Path $PSScriptRoot '..\scripts\windows_guest_runner.ps1'))
$ErrorActionPreference='Stop'
$tokens=$null; $parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count) { throw 'Guest runner PowerShell syntax is invalid' }
$function=$ast.Find({param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Invoke-Bounded'
},$false)
if (-not $function) { throw 'Native process helper missing' }
Invoke-Expression $function.Extent.Text
function Event([string]$Phase) { }
$Work=Join-Path ([IO.Path]::GetTempPath()) ('KiraGuestProcessProbe-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $Work | Out-Null
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
$results=@()
try {
    foreach ($expected in @(0,17)) {
        if ($env:OS -eq 'Windows_NT') {
            $program=$env:ComSpec; $arguments=@('/d','/c',('exit '+$expected))
        } else {
            $program='/bin/sh'; $arguments=@('-c',('exit '+$expected))
        }
        $result=Invoke-Bounded $program $arguments ('exit-'+$expected) 15
        if ($result.exit_code -isnot [int] -or $result.exit_code -ne $expected) {
            throw 'Native process exit code was missing or misreported'
        }
        if (-not $script:LastProcessInfo.handle_retained) { throw 'Original handle was not retained' }
        $results+=@{expected=$expected; actual=$result.exit_code;
            handle_retained=$script:LastProcessInfo.handle_retained}
    }
    @{powershell_version=$PSVersionTable.PSVersion.ToString();
        native_windows=($env:OS -eq 'Windows_NT'); probes=$results; passed=$true}|
        ConvertTo-Json -Depth 5 -Compress
} finally {
    # Delete only files created by this probe in its unique temporary directory.
    Get-ChildItem -LiteralPath $Work -File | Remove-Item
    Remove-Item -LiteralPath $Work
}
