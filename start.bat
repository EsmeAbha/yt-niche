@echo off
REM Double-click to open Niche Studio in your browser.
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
if not exist config.yaml copy config.example.yaml config.yaml >nul
python -m streamlit run app.py --browser.gatherUsageStats false
pause
