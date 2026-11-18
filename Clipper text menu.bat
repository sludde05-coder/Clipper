@echo off
rem The old text menu, for those who prefer it. The Clipper app (Clipper.bat) does everything this does.
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist ".venv\Scripts\python.exe" (
  echo The clipper is not installed yet. Double-click install.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m clipper %*
if "%~1"=="" pause
