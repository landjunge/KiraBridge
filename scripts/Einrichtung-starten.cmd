@echo off
setlocal
if not exist "%~dp0Einrichtung.ps1" (
  echo Die Einrichtung.ps1 fehlt. Bitte entpacke das vollstaendige KiraBridge-Windows-Paket.
  pause
  exit /b 1
)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0Einrichtung.ps1"
if errorlevel 1 (
  echo Die Einrichtung wurde nicht abgeschlossen. Vorhandene Instanzen und Daten bleiben erhalten.
  pause
  exit /b 1
)
exit /b 0
