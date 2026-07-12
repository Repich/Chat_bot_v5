@echo off
setlocal
set "INSTALL_ROOT=C:\Monitoring\WiiconChatBot_5"
if not exist "%INSTALL_ROOT%\runtime\python.exe" (
  echo Python runtime not found: %INSTALL_ROOT%\runtime\python.exe
  exit /b 1
)
cd /d "%INSTALL_ROOT%"
"%INSTALL_ROOT%\runtime\python.exe" "%INSTALL_ROOT%\app\current\scripts\run_windows_supervisor.py" --install-root "%INSTALL_ROOT%" --port 7786 --public-host ms-1cmonitor
