@echo off
setlocal
set "ROOT=%~dp0.."
python "%ROOT%\scripts\verify_onboarding_candidates.py" %*
exit /b %ERRORLEVEL%
