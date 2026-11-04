param(
    [ValidateSet('Run', 'Configure', 'Status')]
    [string]$Action = 'Run',
    [Parameter(Mandatory = $true)]
    [string]$InstallDir
)

Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'

function Assert-LocalPlainPath([string]$Path) {
    if ($Path -notmatch '^[A-Za-z]:\\' -or $Path.Substring(2).Contains(':')) {
        throw 'Installation requires a local drive / Lokales Laufwerk erforderlich.'
    }
    $candidate = $Path
    while ($candidate) {
        $item = Get-Item -LiteralPath $candidate -Force -ErrorAction Stop
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'Linked installation paths are refused / Verknuepfte Pfade nicht erlaubt.'
        }
        $parent = [IO.Directory]::GetParent($candidate)
        if ($null -eq $parent) { break }
        $candidate = $parent.FullName
    }
}

function Read-Status([string]$Python, [string]$Lifecycle, [string]$Root) {
    $lines = & $Python '-I' '-B' $Lifecycle 'status' '--install-dir' $Root
    if ($LASTEXITCODE -ne 0) {
        throw 'Cannot read configuration / Konfiguration konnte nicht gelesen werden.'
    }
    return (($lines -join [Environment]::NewLine) | ConvertFrom-Json)
}

function Show-Configuration([string]$Python, [string]$Lifecycle, [string]$Root) {
    $status = Read-Status $Python $Lifecycle $Root
    $configuredPort = [int]$status.port
    if ($configuredPort -lt 1024 -or $configuredPort -gt 65535) {
        throw 'Invalid saved port; configuration preserved / Ungueltiger Port bleibt erhalten.'
    }

    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [Windows.Forms.Application]::EnableVisualStyles()
    $form = New-Object Windows.Forms.Form
    $form.Text = 'KiraBridge - Konfiguration / Settings'
    $form.StartPosition = 'CenterScreen'
    $form.ClientSize = New-Object Drawing.Size(540, 255)
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false

    $description = New-Object Windows.Forms.Label
    $description.Location = New-Object Drawing.Point(18, 16)
    $description.Size = New-Object Drawing.Size(505, 40)
    $description.Text = "MCP: $($status.endpoint)`r`nAenderungen gelten beim naechsten Start / Changes apply on next start."
    $form.Controls.Add($description)

    $portLabel = New-Object Windows.Forms.Label
    $portLabel.Location = New-Object Drawing.Point(18, 71)
    $portLabel.Size = New-Object Drawing.Size(180, 24)
    $portLabel.Text = 'Port (1024-65535):'
    $form.Controls.Add($portLabel)
    $port = New-Object Windows.Forms.NumericUpDown
    $port.Location = New-Object Drawing.Point(205, 68)
    $port.Size = New-Object Drawing.Size(115, 24)
    $port.Minimum = 1024
    $port.Maximum = 65535
    $port.Value = $configuredPort
    $form.Controls.Add($port)

    $dataLabel = New-Object Windows.Forms.Label
    $dataLabel.Location = New-Object Drawing.Point(18, 113)
    $dataLabel.Size = New-Object Drawing.Size(505, 37)
    $dataLabel.Text = "Daten und Zugang bleiben erhalten / Data and credentials are preserved.`r`nOrdner / Folder:"
    $form.Controls.Add($dataLabel)
    $data = New-Object Windows.Forms.TextBox
    $data.Location = New-Object Drawing.Point(18, 154)
    $data.Size = New-Object Drawing.Size(505, 24)
    $data.ReadOnly = $true
    $data.Text = [string]$status.data_dir
    $form.Controls.Add($data)

    $save = New-Object Windows.Forms.Button
    $save.Location = New-Object Drawing.Point(255, 207)
    $save.Size = New-Object Drawing.Size(135, 30)
    $save.Text = 'Speichern / Save'
    $form.Controls.Add($save)
    $cancel = New-Object Windows.Forms.Button
    $cancel.Location = New-Object Drawing.Point(399, 207)
    $cancel.Size = New-Object Drawing.Size(124, 30)
    $cancel.Text = 'Abbrechen / Cancel'
    $cancel.DialogResult = [Windows.Forms.DialogResult]::Cancel
    $form.Controls.Add($cancel)
    $form.AcceptButton = $save
    $form.CancelButton = $cancel
    $save.Add_Click({
        $save.Enabled = $false
        try {
            $null = & $Python '-I' '-B' $Lifecycle 'configure' '--install-dir' $Root '--port' ([string][int]$port.Value)
            if ($LASTEXITCODE -ne 0) {
                throw 'Configuration refused / Konfiguration abgelehnt.'
            }
            $form.DialogResult = [Windows.Forms.DialogResult]::OK
            $form.Close()
        } catch {
            [void][Windows.Forms.MessageBox]::Show(
                'Speichern fehlgeschlagen. Bitte KiraBridge schliessen und erneut versuchen. / Could not save. Close KiraBridge and try again.',
                'KiraBridge', [Windows.Forms.MessageBoxButtons]::OK,
                [Windows.Forms.MessageBoxIcon]::Error)
        } finally {
            $save.Enabled = $true
        }
    })
    try { [void]$form.ShowDialog() } finally { $form.Dispose() }
}

try {
    $root = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
    Assert-LocalPlainPath $root
    $pointerPath = Join-Path $root 'current.json'
    Assert-LocalPlainPath $pointerPath
    if ((Get-Item -LiteralPath $pointerPath).Length -gt 65536) {
        throw 'Invalid installation pointer / Ungueltige Installationsdaten.'
    }
    $pointer = Get-Content -LiteralPath $pointerPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (($pointer.schema -isnot [int] -and $pointer.schema -isnot [long]) -or
        $pointer.schema -ne 1 -or $pointer.release -isnot [string] -or
        $pointer.release -notmatch '^[a-f0-9]{16,64}$') {
        throw 'Invalid installation pointer / Ungueltige Installationsdaten.'
    }
    $runtime = Join-Path $root ('releases\' + $pointer.release + '\Runtime')
    $python = Join-Path $runtime 'python.exe'
    $lifecycle = Join-Path $runtime 'windows_lifecycle.py'
    Assert-LocalPlainPath $python
    Assert-LocalPlainPath $lifecycle
    Set-Location -LiteralPath $root
    if ($Action -eq 'Configure') {
        Show-Configuration $python $lifecycle $root
        exit 0
    }
    $command = if ($Action -eq 'Status') { 'status' } else { 'run' }
    & $python '-I' '-B' $lifecycle $command '--install-dir' $root
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine('KiraBridge konnte nicht gestartet werden / KiraBridge could not start.')
    [Console]::Error.WriteLine('Setup erneut ausfuehren oder Installationspfad pruefen. / Run Setup again or check the installation path.')
    exit 1
}
