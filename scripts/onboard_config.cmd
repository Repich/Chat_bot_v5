@echo off
setlocal
cd /d "%~dp0\.."
python scripts\onboard_config.py %*
exit /b %ERRORLEVEL%
