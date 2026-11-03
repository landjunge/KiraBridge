@echo off
set "KIRA_WINDOWS_PYTHON=%LOCALAPPDATA%\KiraBridgeDev\Python314\python.exe"
if not exist "%KIRA_WINDOWS_PYTHON%" (
  echo KiraBridge Windows preview requires the prepared Python installation.
  pause
  exit /b 1
)
"%KIRA_WINDOWS_PYTHON%" -m kirabridge.windows_preview --transport http --port 8765
if errorlevel 1 pause
