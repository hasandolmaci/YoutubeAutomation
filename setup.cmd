@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto failed
where npm.cmd >nul 2>nul
if errorlevel 1 goto failed
py -3.12 -m venv .venv
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
py -3.12 -m venv .venv-tts
if errorlevel 1 goto failed
.venv-tts\Scripts\python.exe -m pip install -r requirements-tts.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe initialize.py
if errorlevel 1 goto failed
pushd dashboard
call npm.cmd ci
if errorlevel 1 goto npmfailed
call npm.cmd run build
if errorlevel 1 goto npmfailed
popd
echo Setup complete. Read README.md to add your credentials and backgrounds.
pause
exit /b 0
:npmfailed
popd
:failed
echo Setup stopped. Install Python 3.12 and Node.js 20.9 or newer; see README.md.
pause
exit /b 1
