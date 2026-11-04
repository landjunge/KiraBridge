@echo off
set "KIRA_WINDOWS_PYTHON=%LOCALAPPDATA%\KiraBridgeDev\Python314\python.exe"
if exist "%LOCALAPPDATA%\KiraBridgeRC33\Runtime\Scripts\python.exe" (
  set "KIRA_WINDOWS_PYTHON=%LOCALAPPDATA%\KiraBridgeRC33\Runtime\Scripts\python.exe"
)
if not exist "%KIRA_WINDOWS_PYTHON%" (
  echo KiraBridge Windows preview requires the prepared Python installation.
  pause
  exit /b 1
)
"%KIRA_WINDOWS_PYTHON%" -I -c "import kirabridge,sys; sys.exit(0 if kirabridge.__version__ == '0.8.0rc33' else 1)"
if errorlevel 1 (
  echo Install the verified RC33 package before starting this desktop preview.
  pause
  exit /b 1
)
"%KIRA_WINDOWS_PYTHON%" -I -m kirabridge.windows_preview --transport http --port 8767 --state-dir "%LOCALAPPDATA%\KiraBridgePreviewRC33"
if errorlevel 1 pause
