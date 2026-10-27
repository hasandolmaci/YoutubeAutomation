@echo off
cd /d "%~dp0"
echo Publishes PUBLIC videos only for channels with schedules enabled.
echo Keep this window open. Press Ctrl+C to stop.
call .venv\Scripts\python.exe scheduler.py
pause
