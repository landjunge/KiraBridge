; Compile the staged copy with Inno Setup 6.4 or later (ISCC.exe).
; Stable production AppId. Acceptance builds override all three defines below.
#ifndef KiraAppId
  #define KiraAppId "KiraBridge.Windows"
#endif
#ifndef KiraGroupName
  #define KiraGroupName "KiraBridge"
#endif
#ifndef KiraDefaultDirName
  #define KiraDefaultDirName "{localappdata}\Programs\KiraBridge"
#endif
#ifndef KiraOutputSuffix
  #define KiraOutputSuffix ""
#endif

[Setup]
AppId={#KiraAppId}
AppName=KiraBridge
AppVersion=0.8.0rc33
AppVerName=KiraBridge RC33
AppPublisher=Netzwerkpunkt
AppPublisherURL=https://github.com/landjunge/KiraBridge
VersionInfoVersion=0.8.0.33
DefaultDirName={#KiraDefaultDirName}
DefaultGroupName={#KiraGroupName}
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.22000
SetupIconFile=shell\KiraBridge.ico
UninstallDisplayIcon={app}\KiraBridge.ico
LicenseFile=LICENSE.txt
InfoBeforeFile=README-EN.txt
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
OutputDir=output
OutputBaseFilename=KiraBridge-0.8.0rc33-Windows-x64-Setup{#KiraOutputSuffix}
SetupLogging=yes
UninstallLogging=yes
CloseApplications=no
RestartApplications=no
AllowCancelDuringInstall=no
AlwaysRestart=no
Uninstallable=yes
UninstallLogMode=append

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"; InfoBeforeFile: "README-EN.txt"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"; InfoBeforeFile: "README-DE.txt"

[CustomMessages]
english.Launch=Start KiraBridge
german.Launch=KiraBridge starten
english.Configure=Configure KiraBridge
german.Configure=KiraBridge konfigurieren
english.LaunchNow=Start KiraBridge now
german.LaunchNow=KiraBridge jetzt starten
english.Remove=Uninstall KiraBridge
german.Remove=KiraBridge deinstallieren
english.SetupError=KiraBridge could not prepare the installation. Close its console and retry. Your data is preserved. See the Setup log for the lifecycle exit code.
german.SetupError=KiraBridge konnte die Installation nicht vorbereiten. Seine Konsole schließen und erneut versuchen. Ihre Daten bleiben erhalten. Der Setup-Log enthält den Lifecycle-Exitcode.
english.NewerVersion=A newer KiraBridge installation exists. Downgrading is blocked.
german.NewerVersion=Eine neuere KiraBridge-Installation ist vorhanden. Ein Downgrade wird abgelehnt.
english.KeepDirectory=Please upgrade KiraBridge in its existing installation directory.
german.KeepDirectory=Bitte KiraBridge im bestehenden Installationsverzeichnis aktualisieren.
english.UninstallBusy=KiraBridge could not prepare uninstallation. Close its console and retry. Configuration, credentials and task history remain preserved.
german.UninstallBusy=KiraBridge konnte die Deinstallation nicht vorbereiten. Seine Konsole schließen und erneut versuchen. Konfiguration, Zugangsdaten und Aufgabenverlauf bleiben erhalten.
english.RollbackError=Automatic recovery could not complete. Run Setup again with the same directory before starting KiraBridge. Your application data is preserved.
german.RollbackError=Die automatische Wiederherstellung konnte nicht abgeschlossen werden. Setup vor dem Start von KiraBridge im gleichen Verzeichnis erneut ausführen. Ihre Anwendungsdaten bleiben erhalten.
english.MaintenanceBusy=Another KiraBridge Setup or uninstaller is running, or the maintenance lock is unavailable. Close the other Setup and retry.
german.MaintenanceBusy=Ein anderes KiraBridge-Setup oder eine Deinstallation läuft bereits, oder die Wartungssperre ist nicht verfügbar. Das andere Setup schließen und erneut versuchen.

[Files]
; Temporary runtime remains available through DeinitializeSetup for rollback.
Source: "Runtime\*"; DestDir: "{tmp}\Runtime"; Flags: dontcopy recursesubdirs createallsubdirs
; Separate tracked maintenance runtime lets uninstall remove releases after
; its own application interpreter exits; Python has no global registration.
Source: "Runtime\*"; DestDir: "{app}\maintenance"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "shell\launch.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "shell\configure.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "shell\windows_launcher.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "shell\KiraBridge.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "README-DE.txt"; DestDir: "{app}"; Flags: ignoreversion
; Commit before Inno finalizes its uninstall log; never use [Run] for setup work.
Source: "README-EN.txt"; DestDir: "{app}"; Flags: ignoreversion; AfterInstall: CommitInstall

[Icons]
Name: "{group}\{cm:Launch}"; Filename: "{app}\launch.cmd"; IconFilename: "{app}\KiraBridge.ico"; WorkingDir: "{app}"
Name: "{group}\{cm:Configure}"; Filename: "{app}\configure.cmd"; IconFilename: "{app}\KiraBridge.ico"; WorkingDir: "{app}"
Name: "{group}\{cm:Remove}"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Uninstall\{#KiraAppId}_is1"; ValueType: dword; ValueName: "KiraInstallerSequence"; ValueData: "800033"; Flags: uninsdeletevalue

[Run]
; Optional user launch after successful setup, with no installation logic.
Filename: "{app}\launch.cmd"; Description: "{cm:LaunchNow}"; Flags: shellexec nowait postinstall skipifsilent unchecked

[UninstallDelete]
; The lifecycle helper has exited before Inno removes its singular lock file.
Type: files; Name: "{app}\.lifecycle.lock"

[Code]
var
  Prepared, InstallDone, UninstallPrepared, UninstallDone: Boolean;
  MaintenanceHandle: THandle;

function KiraCreateMutex(SecurityAttributes: Integer; InitialOwner: Boolean;
  Name: String): THandle;
  external 'CreateMutexW@kernel32.dll stdcall';
function KiraGetLastError: Cardinal;
  external 'GetLastError@kernel32.dll stdcall';
function KiraCloseHandle(Handle: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

procedure ReleaseMaintenance;
begin
  if MaintenanceHandle <> 0 then begin
    KiraCloseHandle(MaintenanceHandle);
    MaintenanceHandle := 0;
  end;
end;

function AcquireMaintenance: Boolean;
var
  ErrorCode: Cardinal;
begin
  // A non-inheritable handle holds the named object for the entire wizard,
  // including gaps between lifecycle subprocesses. Both Setup and Uninstall
  // use the same atomic create; no check-then-create window or waiting/replay.
  MaintenanceHandle := KiraCreateMutex(0, False,
    'Local\{#KiraAppId}.Maintenance.' + ExpandConstant('{username}'));
  ErrorCode := KiraGetLastError;
  Result := (MaintenanceHandle <> 0) and (ErrorCode <> 183);
  if not Result then begin
    ReleaseMaintenance;
    Log('KiraBridge maintenance mutex refused, error=' + IntToStr(ErrorCode));
    SuppressibleMsgBox(CustomMessage('MaintenanceBusy'), mbError, MB_OK, IDOK);
  end;
end;

function Quoted(const Value: String): String;
begin
  Result := '"' + Value + '"';
end;

function Lifecycle(const Action: String; const Maintenance: Boolean): Boolean;
var
  Base, Parameters, DataDir: String;
  ExitCode: Integer;
begin
  if Maintenance then
    Base := ExpandConstant('{app}\maintenance')
  else
    Base := ExpandConstant('{tmp}\Runtime');
  Parameters := '-I -B ' + Quoted(Base + '\windows_lifecycle.py') + ' ' + Action +
    ' --install-dir ' + Quoted(ExpandConstant('{app}'));
  if not Maintenance then
    Parameters := Parameters + ' --transaction ' + Quoted(ExpandConstant('{tmp}\transaction.json'));
  if Action = 'prepare' then begin
    Parameters := Parameters + ' --runtime-dir ' + Quoted(Base);
    DataDir := ExpandConstant('{param:DataDir|}');
    if DataDir <> '' then
      Parameters := Parameters + ' --data-dir ' + Quoted(DataDir);
  end;
  Result := ExecAndLogOutput(Base + '\python.exe', Parameters, Base, SW_SHOWNORMAL,
    ewWaitUntilTerminated, ExitCode, nil);
  Log('KiraBridge lifecycle ' + Action + ': launched=' + IntToStr(Ord(Result)) +
    ', exit=' + IntToStr(ExitCode));
  Result := Result and (ExitCode = 0);
end;

function InitializeSetup: Boolean;
var
  Sequence: Cardinal;
begin
  Result := AcquireMaintenance;
  if not Result then
    Exit;
  if RegQueryDWordValue(HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#KiraAppId}_is1',
    'KiraInstallerSequence', Sequence) and (Sequence > 800033) then begin
    SuppressibleMsgBox(CustomMessage('NewerVersion'), mbError, MB_OK, IDOK);
    Result := False;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  PreviousDir: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#KiraAppId}_is1',
    'InstallLocation', PreviousDir) and (PreviousDir <> '') and
    (CompareText(RemoveBackslashUnlessRoot(PreviousDir),
      RemoveBackslashUnlessRoot(ExpandConstant('{app}'))) <> 0) then begin
    Result := CustomMessage('KeepDirectory');
    Exit;
  end;
  if not Prepared then begin
    ExtractTemporaryFiles('{tmp}\Runtime\*');
    if not Lifecycle('prepare', False) then begin
      Result := CustomMessage('SetupError');
      Exit;
    end;
    Prepared := True;
  end;
end;

procedure CommitInstall;
begin
  if not Lifecycle('commit', False) then
    RaiseException(CustomMessage('SetupError'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssDone then begin
    if not Lifecycle('finalize', False) then
      RaiseException(CustomMessage('RollbackError'));
    InstallDone := True;
  end;
end;

procedure DeinitializeSetup;
begin
  try
    if Prepared and not InstallDone then
      if not Lifecycle('rollback', False) then
        SuppressibleMsgBox(CustomMessage('RollbackError'), mbError, MB_OK, IDOK);
  finally
    ReleaseMaintenance;
  end;
end;

function InitializeUninstall: Boolean;
begin
  Result := AcquireMaintenance;
  if not Result then
    Exit;
  Result := Lifecycle('preflight-uninstall', True);
  UninstallPrepared := Result;
  if not Result then
    SuppressibleMsgBox(CustomMessage('UninstallBusy'), mbError, MB_OK, IDOK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then begin
    if not Lifecycle('uninstall', True) then
      RaiseException(CustomMessage('UninstallBusy'));
    UninstallDone := True;
  end;
end;

procedure DeinitializeUninstall;
begin
  try
    if UninstallPrepared and not UninstallDone then
      Lifecycle('cancel-uninstall', True);
  finally
    ReleaseMaintenance;
  end;
end;
