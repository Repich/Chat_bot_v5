@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 (
  echo.
  echo Установка завершилась ошибкой. Подробности указаны выше.
  pause
  exit /b 1
)
pause
