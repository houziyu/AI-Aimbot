@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please install requirements.txt in .venv first. See README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" main_ui.py
if errorlevel 1 pause
