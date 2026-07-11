@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
python "%SCRIPT_DIR%sync_wiic_bwiki.py" %*
exit /b %ERRORLEVEL%
