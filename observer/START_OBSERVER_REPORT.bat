@echo off
setlocal
cd /d "%~dp0.."
py -3 observer\report.py --hours 24
if errorlevel 1 python observer\report.py --hours 24
pause
