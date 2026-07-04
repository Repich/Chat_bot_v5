@echo off
setlocal
cd /d "%~dp0\.."
python scripts\run_regression.py %*
exit /b %ERRORLEVEL%
