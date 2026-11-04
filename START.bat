@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Use the Python launcher when available so the venv is based on Python 3.13.
if not exist .venv (
    py -3.13 -m venv .venv
    if errorlevel 1 python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python app.py
pause
