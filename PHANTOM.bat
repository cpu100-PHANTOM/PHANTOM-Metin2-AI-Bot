@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

net session >nul 2>&1
if %errorLevel% neq 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "VENV_PYW=%~dp0.venv\Scripts\pythonw.exe"
set "DEPS_CHECK=import certifi, cv2, easyocr, keyboard, mss, numpy, torch, webview, win32api, win32gui; from ultralytics import YOLO"
set "READY_PY="

if exist "%VENV_PY%" goto runtime_selected

call :find_ready_python
if not defined READY_PY goto run_setup

set "VENV_PY=%READY_PY%"
call :set_pythonw
echo [OK] Hazir Python ortami bulundu: %VENV_PY%
goto runtime_selected

:run_setup
echo [INFO] Hazir kurulum bulunamadi. kurulum.bat mevcut paketleri kontrol edecek...
call "%~dp0kurulum.bat" /auto

:runtime_selected

if not exist "%VENV_PY%" (
    echo [HATA] Sanal ortam bulunamadi. Once kurulum.bat dosyasini calistirin.
    pause
    exit /b 1
)
if not exist "%VENV_PYW%" set "VENV_PYW=%VENV_PY%"

set "PYTHONUTF8=1"
"%VENV_PY%" -c "%DEPS_CHECK%" >nul 2>&1
if not errorlevel 1 goto deps_ready

call :find_ready_python
if not defined READY_PY goto repair_setup

set "VENV_PY=%READY_PY%"
call :set_pythonw
echo [OK] Yerel sanal ortam eksik/bozuk; hazir Python ortami kullaniliyor: %VENV_PY%
goto deps_ready

:repair_setup
echo [INFO] Eksik veya bozuk kutuphane bulundu. kurulum.bat mevcut paketleri kontrol edecek...
call "%~dp0kurulum.bat" /auto

:deps_ready

"%VENV_PY%" -c "%DEPS_CHECK%" >nul 2>&1
if errorlevel 1 (
    echo [HATA] Gerekli kutuphaneler hala eksik. Once kurulum.bat dosyasini tamamlayin.
    echo [INFO] Detay icin runtime\logs klasorundeki en yeni kurulum loguna bakin.
    pause
    exit /b 1
)

"%VENV_PY%" -c "from src.phantom.captcha.solver import _easyocr_models_ready; raise SystemExit(0 if _easyocr_models_ready() else 1)" >nul 2>&1
if errorlevel 1 (
    echo [INFO] EasyOCR model cache eksik. kurulum.bat calistiriliyor...
    call "%~dp0kurulum.bat" /auto
)

"%VENV_PY%" -c "from src.phantom.captcha.solver import _easyocr_models_ready; raise SystemExit(0 if _easyocr_models_ready() else 1)" >nul 2>&1
if errorlevel 1 (
    echo [HATA] EasyOCR model cache hazirlanamadi. Once kurulum.bat dosyasini tamamlayin.
    echo [INFO] Detay icin runtime\logs klasorundeki en yeni kurulum loguna bakin.
    pause
    exit /b 1
)

set "PHANTOM_GUI_LAUNCH=1"
start "" /D "%~dp0" "%VENV_PYW%" "%~dp0metin_bot_webview.py"
exit /b 0

:find_ready_python
set "READY_PY="
if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
    call :check_python "%LocalAppData%\Programs\Python\Python311\python.exe"
    if defined READY_PY exit /b 0
)
for /f "delims=" %%P in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do (
    if not defined READY_PY call :check_python "%%P"
)
if defined READY_PY exit /b 0
for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do (
    if not defined READY_PY call :check_python "%%P"
)
if defined READY_PY exit /b 0
for /f "delims=" %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$roots=@('%~dp0..',(Join-Path $env:USERPROFILE 'Downloads')); foreach($root in $roots){ if(-not (Test-Path $root)){ continue }; foreach($f in (Get-ChildItem -Path $root -Filter python.exe -Recurse -ErrorAction SilentlyContinue)){ $p=$f.FullName; if($p -like '*\.venv\Scripts\python.exe' -and $p -like '*PHANTOM*'){ Write-Output $p } } }" 2^>nul') do (
    if not defined READY_PY call :check_python "%%P"
)
exit /b 0

:check_python
if not exist "%~1" exit /b 0
"%~1" -c "%DEPS_CHECK%" >nul 2>&1
if not errorlevel 1 set "READY_PY=%~1"
exit /b 0

:set_pythonw
set "VENV_PYW=%VENV_PY%"
for %%D in ("%VENV_PY%") do if exist "%%~dpDpythonw.exe" set "VENV_PYW=%%~dpDpythonw.exe"
exit /b 0
