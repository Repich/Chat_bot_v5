@echo off
setlocal
cd /d "%~dp0\.."
python scripts\ask.py %*
exit /b %ERRORLEVEL%

