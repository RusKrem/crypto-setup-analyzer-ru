@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "BRIDGE_DIR=%CD%\telegram_bridge"
set "VENV=%BRIDGE_DIR%\.venv"
set "PY=%VENV%\Scripts\python.exe"
set "EXE=%BRIDGE_DIR%\TelegramBridge.exe"

echo [SETUP] Crypto Setup Analyzer Telegram Bridge
if not exist "%PY%" (
    echo [SETUP] Creating dedicated bridge environment...
    py -3 -m venv "%VENV%"
    if errorlevel 1 (
        python -m venv "%VENV%"
        if errorlevel 1 (
            echo [ERROR] Could not create Python environment. Install Python 3 and retry.
            pause
            exit /b 1
        )
    )
)
if not exist "%PY%" (
    echo [ERROR] Bridge Python executable was not created.
    pause
    exit /b 1
)
if not exist "%EXE%" (
    echo [SETUP] Installing PyInstaller...
    "%PY%" -m pip install --disable-pip-version-check pyinstaller
    if errorlevel 1 (echo [ERROR] PyInstaller install failed.& pause & exit /b 1)
    echo [SETUP] Building standalone TelegramBridge.exe...
    "%PY%" -m PyInstaller --noconfirm --clean --onefile --console --paths "%CD%" --name TelegramBridge --distpath "%BRIDGE_DIR%" --workpath "%BRIDGE_DIR%\build" --specpath "%BRIDGE_DIR%\build" "%BRIDGE_DIR%\bridge.py"
    if errorlevel 1 (echo [ERROR] Build failed.& pause & exit /b 1)
)
if not exist "%EXE%" (echo [ERROR] TelegramBridge.exe not found.& pause & exit /b 1)
echo [INFO] Add ONLY this executable to hide.me VPN:
echo %EXE%
echo [INFO] Scanner stays on normal internet.
echo.
"%EXE%"
echo.
echo [STOP] Bridge exited with code %ERRORLEVEL%.
pause
