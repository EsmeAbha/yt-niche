@echo off
REM One-time setup: creates a Python environment and installs everything (all free).
cd /d "%~dp0"
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist config.yaml copy config.example.yaml config.yaml >nul
echo.
echo Done. Double-click start.bat to open Niche Studio.
pause
