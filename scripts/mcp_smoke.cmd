@echo off
setlocal
cd /d "%~dp0\.."
python scripts\mcp_smoke.py %*
exit /b %ERRORLEVEL%

