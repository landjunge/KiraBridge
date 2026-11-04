@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0."
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0windows_launcher.ps1" -Action Configure -InstallDir "%~dp0."
set "KIRA_CONFIG_EXIT=%ERRORLEVEL%"
if not "%KIRA_CONFIG_EXIT%"=="0" pause
exit /b %KIRA_CONFIG_EXIT%
