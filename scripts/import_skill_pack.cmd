@echo off
setlocal
cd /d "%~dp0\.."
python scripts\import_skill_pack.py %*
