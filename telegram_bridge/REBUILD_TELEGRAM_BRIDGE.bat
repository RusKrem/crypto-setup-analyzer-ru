@echo off
setlocal
cd /d "%~dp0"
echo [INFO] Rebuilding Telegram Bridge from the current source...
call BUILD_TELEGRAM_BRIDGE.bat
exit /b %ERRORLEVEL%
