@echo off
REM DeleteBackground launcher for Windows.
REM Creates a local virtual environment on first run, installs dependencies,
REM then starts the FastAPI server and opens the browser.

setlocal
set "ROOT=%~dp0"
set "VENV=%ROOT%.venv"
set "PY=python"

if not exist "%VENV%\Scripts\python.exe" (
  echo [DeleteBackground] Creating virtual environment in .venv ...
  %PY% -m venv "%VENV%" || goto :fail
  "%VENV%\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
  "%VENV%\Scripts\python.exe" -m pip install -r "%ROOT%requirements.txt" || goto :fail
)

set "HOST=%DBG_HOST%"
if "%HOST%"=="" set "HOST=127.0.0.1"
set "PORT=%DBG_PORT%"
if "%PORT%"=="" set "PORT=8765"

echo [DeleteBackground] Starting on http://%HOST%:%PORT%
start "" "http://%HOST%:%PORT%"
"%VENV%\Scripts\python.exe" -m uvicorn app.main:app --host %HOST% --port %PORT%
exit /b 0

:fail
echo [DeleteBackground] Setup failed.
exit /b 1
