@echo off
setlocal
cd /d "%~dp0\.."
python scripts\export_skill_pack.py %*
