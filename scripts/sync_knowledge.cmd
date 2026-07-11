@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
python "%SCRIPT_DIR%sync_knowledge.py" %*
exit /b %ERRORLEVEL%
