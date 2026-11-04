@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Сначала запусти START.bat и установи зависимости приложения.
  pause
  exit /b 1
)
.venv\Scripts\python.exe run_swing_backtest.py --symbol GTCUSDT --interval 15m --days 30
pause
