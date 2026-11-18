@echo off
setlocal
cd /d "%~dp0.."
set "BRIDGE_DIR=%CD%\telegram_bridge"
set "VENV=%BRIDGE_DIR%\.venv"
set "PY=%VENV%\Scripts\python.exe"
if not exist "%PY%" py -3 -m venv "%VENV%"
if errorlevel 1 (echo [ERROR] Python environment setup failed.& pause & exit /b 1)
"%PY%" -m pip install --disable-pip-version-check pyinstaller
if errorlevel 1 (echo [ERROR] PyInstaller install failed.& pause & exit /b 1)
"%PY%" -m PyInstaller --noconfirm --clean --onefile --console --paths "%CD%" --name TelegramBridge --distpath "%BRIDGE_DIR%" --workpath "%BRIDGE_DIR%\build" --specpath "%BRIDGE_DIR%\build" "%BRIDGE_DIR%\bridge.py"
if errorlevel 1 (echo [ERROR] Build failed.& pause & exit /b 1)
echo [SUCCESS] %BRIDGE_DIR%\TelegramBridge.exe
pause
