@echo off
setlocal
set "INSTALL_ROOT=C:\Monitoring\WiiconChatBot_5"
cd /d "%INSTALL_ROOT%"
"%INSTALL_ROOT%\runtime\python.exe" "%INSTALL_ROOT%\app\current\scripts\request_update.py" --install-root "%INSTALL_ROOT%"
if errorlevel 1 (
  echo Failed to queue the update.
  pause
  exit /b 1
)
echo The supervisor will install the update and restart WIICON ChatBot 5 automatically.
timeout /t 3 /nobreak >nul
