@echo off
REM Genealogy Workbench -- double-click to start.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating a private Python environment. This happens once and takes a minute...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 (
    echo.
    echo  Could not create the environment. Install Python 3.10+ from python.org
    echo  and make sure "Add Python to PATH" is ticked during setup.
    echo.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
  echo Installing dependencies...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet
)

echo Starting Genealogy Workbench...
".venv\Scripts\python.exe" -m app.server
pause
