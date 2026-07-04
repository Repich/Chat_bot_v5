@echo off
setlocal
cd /d "%~dp0\.."
python scripts\trace_to_case.py %*
exit /b %ERRORLEVEL%
