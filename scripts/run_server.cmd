@echo off
setlocal
cd /d "%~dp0\.."
python scripts\run_server.py %*
exit /b %ERRORLEVEL%

