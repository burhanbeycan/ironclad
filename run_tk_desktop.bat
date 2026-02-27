@echo off
setlocal enabledelayedexpansion

REM --- IRONCLAD Desktop (Tkinter) launcher ---
REM Creates .venv, installs deps, runs the native GUI.

cd /d "%~dp0"

if not exist ".venv" (
  python -m venv .venv
)

call ".venv\Scripts\activate.bat"

python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt

python run_desktop.py
