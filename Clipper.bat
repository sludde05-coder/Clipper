@echo off
rem Double-click this to open the Clipper app.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo The clipper is not installed yet. Double-click install.bat first.
  pause
  exit /b 1
)
rem Quick check that everything is installed (e.g. after updating the files without re-running the installer).
".venv\Scripts\python.exe" -c "import clipper.app" 2>nul
if errorlevel 1 (
  echo Clipper needs a quick update of its parts. Double-click install.bat, then try again.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m clipper app
