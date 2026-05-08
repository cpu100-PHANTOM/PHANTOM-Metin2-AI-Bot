@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

net session >nul 2>&1
if %errorLevel% neq 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo [INFO] Kurulum bulunamadi. kurulum.bat calistiriliyor...
    call "%~dp0kurulum.bat" /auto
)

if not exist "%VENV_PY%" (
    echo [HATA] Sanal ortam bulunamadi. Once kurulum.bat dosyasini calistirin.
    pause
    exit /b 1
)

set "PYTHONUTF8=1"
"%VENV_PY%" "%~dp0metin_bot_webview.py"
if errorlevel 1 (
    echo.
    echo [HATA] PHANTOM calisirken hata olustu.
    echo runtime\logs klasorundeki loglari kontrol edin.
    pause
)
