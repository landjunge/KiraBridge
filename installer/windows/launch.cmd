@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0."
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0windows_launcher.ps1" -Action Run -InstallDir "%~dp0."
set "KIRA_LAUNCH_EXIT=%ERRORLEVEL%"
if not "%KIRA_LAUNCH_EXIT%"=="0" pause
exit /b %KIRA_LAUNCH_EXIT%
