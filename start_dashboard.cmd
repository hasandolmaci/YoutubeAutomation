@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe initialize.py
if errorlevel 1 goto failed
cd dashboard
call npm.cmd run start
:failed
pause
