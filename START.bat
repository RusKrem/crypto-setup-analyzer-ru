@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "VENV_PY=%CD%\.venv\Scripts\python.exe"

rem Create the application environment, preferring Python 3.13.
if not exist "%VENV_PY%" (
    py -3.13 -m venv .venv
    if errorlevel 1 (
        python -m venv .venv
        if errorlevel 1 (
            echo [ERROR] Не удалось создать виртуальное окружение Python.
            pause
            exit /b 1
        )
    )
)
if not exist "%VENV_PY%" (
    echo [ERROR] Не найден Python в .venv. Удали повреждённую папку .venv и повтори запуск.
    pause
    exit /b 1
)

echo [SETUP] Проверяю и устанавливаю зависимости...
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Установка зависимостей завершилась с ошибкой. Приложение не будет запущено.
    pause
    exit /b 1
)

echo [START] Crypto Setup Analyzer RU
"%VENV_PY%" app.py
set "APP_EXIT=%ERRORLEVEL%"
echo.
echo [EXIT] Приложение завершилось с кодом %APP_EXIT%.
pause
exit /b %APP_EXIT%
