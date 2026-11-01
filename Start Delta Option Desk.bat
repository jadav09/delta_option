@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=C:\Users\jadav\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PYTHON%" (
  echo Python runtime not found. Install Python 3.10 or later, then run: python server.py
  pause
  exit /b 1
)
start "Delta Option Desk server" "%PYTHON%" server.py
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8765/
