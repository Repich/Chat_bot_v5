@echo off
setlocal
set "INSTALL_ROOT=%~dp0"
"%INSTALL_ROOT%runtime\python.exe" "%INSTALL_ROOT%app\current\scripts\run_windows_supervisor.py" --install-root "%INSTALL_ROOT%" --port 7786
