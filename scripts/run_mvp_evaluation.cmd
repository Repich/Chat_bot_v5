@echo off
setlocal
cd /d "%~dp0\.."
python scripts\run_mvp_evaluation.py %*
exit /b %ERRORLEVEL%
