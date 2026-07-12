@echo off
setlocal
chcp 65001 >nul
set "INSTALL_ROOT=C:\Monitoring\WiiconChatBot_5"
cd /d "%INSTALL_ROOT%"
"%INSTALL_ROOT%\runtime\python.exe" "%INSTALL_ROOT%\app\current\scripts\request_update.py" --install-root "%INSTALL_ROOT%"
if errorlevel 1 (
  echo Не удалось поставить обновление в очередь.
  pause
  exit /b 1
)
echo Supervisor установит обновление и автоматически перезапустит WIICON ChatBot 5.
timeout /t 3 /nobreak >nul
