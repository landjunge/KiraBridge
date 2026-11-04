param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Utf8 = New-Object System.Text.UTF8Encoding($false)
$PackageRoot = [IO.Path]::GetFullPath($PSScriptRoot)

function Assert-LocalFile([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'unsafe_package'
    }
    return $item
}
function Hash([string]$Path) {
    [void](Assert-LocalFile $Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Run-Python([string]$Python, [string[]]$Arguments) {
    & $Python -I -B @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'python_step_failed' }
}
function No-Reparse([string]$Path) {
    $current=[IO.Path]::GetFullPath($Path)
    if ($current.StartsWith('\\')) { throw 'unsafe_destination' }
    while ($current) {
        if ((Test-Path -LiteralPath $current) -and
            ((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'unsafe_destination'
        }
        $current=[IO.Path]::GetDirectoryName($current)
    }
}
function Write-New([string]$Path, [string]$Text) {
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try { $bytes=$Utf8.GetBytes($Text); $stream.Write($bytes,0,$bytes.Length); $stream.Flush($true) }
    finally { $stream.Dispose() }
}
try {
    Write-Host 'KiraBridge wird vorbereitet. Danach begleitet dich ein Fenster durch die Einrichtung.'
    Write-Host '1/4: Installationspaket pruefen ...'
    $checksums = @{}
    foreach ($line in [IO.File]::ReadAllLines((Join-Path $PackageRoot 'SHA256SUMS'))) {
        if ($line -cnotmatch '^([a-f0-9]{64})  ([A-Za-z0-9][A-Za-z0-9._+/-]{0,240})$') {
            throw 'unsafe_package'
        }
        $name=$Matches[2]; $expected=$Matches[1]
        if ($name.Contains('..') -or $checksums.ContainsKey($name)) { throw 'unsafe_package' }
        $path=Join-Path $PackageRoot $name
        if (-not [IO.Path]::GetFullPath($path).StartsWith($PackageRoot+[IO.Path]::DirectorySeparatorChar)) {
            throw 'unsafe_package'
        }
        # Inspect every ancestor so archive junctions cannot redirect an installer/wheel.
        $parent=[IO.Path]::GetDirectoryName($path)
        while ($parent.Length -ge $PackageRoot.Length) {
            if ((Get-Item -LiteralPath $parent -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'unsafe_package'
            }
            $parent=[IO.Path]::GetDirectoryName($parent)
        }
        if ((Hash $path) -cne $expected) { throw 'package_changed' }
        $checksums[$name]=$expected
    }
    foreach ($name in @('package.json','manifest.json','requirements-win.txt','python-installer.exe',
                        'Einrichtung-starten.cmd','Einrichtung.ps1')) {
        if (-not $checksums.ContainsKey($name)) { throw 'unsafe_package' }
    }
    $package=Get-Content -LiteralPath (Join-Path $PackageRoot 'package.json') -Raw | ConvertFrom-Json
    $manifest=Get-Content -LiteralPath (Join-Path $PackageRoot 'manifest.json') -Raw | ConvertFrom-Json
    if ($package.version -cnotmatch '^0\.8\.0rc[0-9]+\.dev[0-9]+$' -or
        $manifest.python_version -cne '3.14.10' -or $package.python_version -cne '3.14.10' -or
        $package.source_commit -cne $manifest.source_commit -or
        (Hash (Join-Path $PackageRoot 'manifest.json')) -cne $package.payload_manifest_sha256) {
        throw 'unsafe_package'
    }
    $wheelName='wheels/kirabridge-'+$package.version+'-py3-none-any.whl'
    if (-not $checksums.ContainsKey($wheelName)) { throw 'unsafe_package' }
    $Wheel=Join-Path $PackageRoot $wheelName
    if ($CheckOnly) {
        Write-Host 'Das Paket ist vollstaendig und unveraendert. Noch nichts installiert.'
        exit 0
    }
    if (-not $env:LOCALAPPDATA -or $env:LOCALAPPDATA.StartsWith('\\')) { throw 'unsafe_destination' }
    $Root=Join-Path $env:LOCALAPPDATA 'KiraBridgeWindows'
    $InstallRoot=Join-Path $Root $package.version
    $Runtime=Join-Path $InstallRoot 'Runtime'
    $Python=Join-Path $Root 'Python314\python.exe'
    foreach ($path in @($Root,$InstallRoot,$Runtime,[IO.Path]::GetDirectoryName($Python))) {
        $current=$path
        while ($current) {
            if (Test-Path -LiteralPath $current) {
                if ((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                    throw 'unsafe_destination'
                }
            }
            $current=[IO.Path]::GetDirectoryName($current)
        }
    }
    Write-Host '2/4: Python fuer diese Windows-Version vorbereiten ...'
    # The vendor installer has one per-user registration per Python minor
    # version. Reuse an exact compatible installation instead of invoking its
    # maintenance installer against a working KiraBridge/Python installation.
    $Candidates=@($Python,(Join-Path $env:LOCALAPPDATA 'KiraBridgeDev\Python314\python.exe'))
    $Registered=$false
    foreach ($registry in @('HKCU:\Software\Python\PythonCore\3.14\InstallPath',
                            'HKLM:\Software\Python\PythonCore\3.14\InstallPath')) {
        if (Test-Path -LiteralPath $registry) {
            $Registered=$true
            $directory=(Get-Item -LiteralPath $registry).GetValue('')
            if ($directory) { $Candidates+=Join-Path $directory 'python.exe' }
        }
    }
    foreach ($Candidate in $Candidates) {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            No-Reparse $Candidate
            & $Candidate -I -B -c 'import sys,struct,tkinter,venv; assert sys.version_info[:3]==(3,14,10) and struct.calcsize(''P'')==8' 2>$null
            if ($LASTEXITCODE -eq 0) { $Python=$Candidate; break }
        }
    }
    if (-not (Test-Path -LiteralPath $Python)) {
        if ($Registered) { throw 'existing_python' }
        if (Test-Path -LiteralPath ([IO.Path]::GetDirectoryName($Python))) {
            throw 'existing_installation'
        }
        New-Item -ItemType Directory -Force $Root | Out-Null
        $PythonAttempt=Join-Path $Root 'python-install-attempt.json'
        if (Test-Path -LiteralPath $PythonAttempt) { throw 'installation_pending' }
        Write-New $PythonAttempt (@{status='started_no_automatic_replay';
            installer_sha256=$checksums['python-installer.exe']}|ConvertTo-Json -Compress)
        $Installer=Join-Path $PackageRoot 'python-installer.exe'
        $arguments=@('/quiet','InstallAllUsers=0','TargetDir="'+[IO.Path]::GetDirectoryName($Python)+'"',
                     'Include_pip=1','Include_tcltk=1','Include_launcher=0','Include_test=0',
                     'Include_doc=0','Include_dev=0','Include_symbols=0','Include_debug=0',
                     'PrependPath=0','AssociateFiles=0','Shortcuts=0')
        $process=Start-Process -FilePath $Installer -ArgumentList $arguments -PassThru
        $handle=$process.Handle
        if (-not $process.WaitForExit(300000)) { throw 'installation_pending' }
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) { throw 'python_install_failed' }
    }
    Run-Python $Python @('-c', 'import sys,tkinter,venv; assert sys.version_info[:3]==(3,14,10)')
    Write-Host '3/4: KiraBridge ohne weitere Downloads installieren ...'
    $Marker=Join-Path $InstallRoot 'installed.json'
    if (Test-Path -LiteralPath $Runtime) {
        if (-not (Test-Path -LiteralPath $Marker)) { throw 'existing_installation' }
        $installed=Get-Content -LiteralPath $Marker -Raw | ConvertFrom-Json
        if ($installed.wheel_sha256 -cne $checksums[$wheelName]) { throw 'existing_installation' }
    } else {
        New-Item -ItemType Directory -Force $InstallRoot | Out-Null
        Write-New (Join-Path $InstallRoot 'install-attempt.json') (@{
            status='started_no_automatic_replay';wheel_sha256=$checksums[$wheelName]
        }|ConvertTo-Json -Compress)
        Run-Python $Python @('-m','venv',$Runtime)
        $RuntimePython=Join-Path $Runtime 'Scripts\python.exe'
        Run-Python $RuntimePython @('-m','pip','--isolated','install','--no-index',
            '--no-compile','--disable-pip-version-check','--find-links',(Join-Path $PackageRoot 'wheels'),
            '-r',(Join-Path $PackageRoot 'requirements-win.txt'))
        Write-New $Marker (@{version=$package.version;wheel_sha256=$checksums[$wheelName]}|ConvertTo-Json -Compress)
    }
    $RuntimePython=Join-Path $Runtime 'Scripts\python.exe'
    # Check every installed runtime .py byte before importing the GUI package.
    $verify=@'
import hashlib,pathlib,sys,sysconfig,zipfile
wheel=pathlib.Path(sys.argv[1]); root=pathlib.Path(sysconfig.get_path('purelib'))
with zipfile.ZipFile(wheel) as z:
    files={n:z.read(n) for n in z.namelist() if n.startswith('kirabridge/') and n.endswith('.py')}
actual={p.relative_to(root).as_posix():p for p in (root/'kirabridge').rglob('*.py')}
assert set(files)==set(actual)
assert all(hashlib.sha256(b).digest()==hashlib.sha256(actual[n].read_bytes()).digest() for n,b in files.items())
import kirabridge,tkinter
assert kirabridge.__version__==sys.argv[2]
'@
    Run-Python $RuntimePython @('-c',$verify,$Wheel,$package.version)
    Write-Host '4/4: Einrichtungsassistent oeffnen ...'
    $PythonW=Join-Path $Runtime 'Scripts\pythonw.exe'
    $Starter=Join-Path ([Environment]::GetFolderPath('Desktop')) 'KiraBridge einrichten.cmd'
    if (-not (Test-Path -LiteralPath $Starter)) {
        $line='@echo off'+"`r`n"+'"'+$PythonW+'" -I -B -m kirabridge.windows_setup'+"`r`n"
        Write-New $Starter $line
    }
    Start-Process -FilePath $PythonW -ArgumentList @('-I','-B','-m','kirabridge.windows_setup')
    Write-Host 'Das Einrichtungsfenster ist geoeffnet. Du kannst dieses Vorbereitungsfenster schliessen.'
    exit 0
} catch {
    # Installer/subprocess exceptions can contain private paths. Use only fixed messages.
    $code=$_.Exception.Message
    if ($code -eq 'package_changed' -or $code -eq 'unsafe_package') {
        Write-Host 'Das Paket ist unvollstaendig oder veraendert. Lade das vollstaendige ZIP erneut und entpacke es neu.'
    } elseif ($code -eq 'existing_installation') {
        Write-Host 'Hier liegt bereits eine andere oder unvollstaendige Einrichtung. Sie bleibt erhalten. Oeffne einen vorhandenen KiraBridge-Starter oder nutze einen neuen Paketordner.'
    } elseif ($code -eq 'installation_pending') {
        Write-Host 'Die Python-Installation ist noch nicht bestaetigt. Starte sie nicht erneut. Warte auf das vorhandene Installationsfenster.'
    } elseif ($code -eq 'existing_python') {
        Write-Host 'Es gibt bereits eine andere Python-3.14-Installation. Sie bleibt erhalten. Fuer dieses Paket wird Python 3.14.10 mit Tk benoetigt; lass die vorhandene Installation zuerst pruefen.'
    } else {
        Write-Host 'Die Vorbereitung konnte nicht abgeschlossen werden. Pruefe freien Speicher und den vollstaendig entpackten Paketordner. Bestehende KiraBridge-Versionen bleiben erhalten.'
    }
    exit 1
}
