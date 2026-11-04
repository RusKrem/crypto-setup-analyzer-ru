@echo off
setlocal
cd /d "%~dp0"
if exist TelegramBridge.exe del /f /q TelegramBridge.exe
call BUILD_TELEGRAM_BRIDGE.bat
