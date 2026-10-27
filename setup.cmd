@echo off
setlocal
cd /d "%~dp0"
set "PYTHON312=py -3.12"
if not "%~1"=="" set PYTHON312="%~1"
%PYTHON312% -c "import sys; assert sys.version_info[:2] == (3, 12), 'Python 3.12 is required'"
if errorlevel 1 goto failed
where npm.cmd >nul 2>nul
if errorlevel 1 goto failed
%PYTHON312% -m venv .venv
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
%PYTHON312% -m venv .venv-tts
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
echo For a custom Python installation: setup.cmd "C:\Path\To\Python312\python.exe"
pause
exit /b 1
