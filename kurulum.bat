@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

set "APP_NAME=PHANTOM Bot"
set "PYTHON_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
set "PYTHON_INSTALLER=%TEMP%\phantom_python_3.11.9.exe"
set "WEBVIEW2_URL=https://go.microsoft.com/fwlink/p/?LinkId=2124703"
set "WEBVIEW2_INSTALLER=%TEMP%\phantom_webview2_setup.exe"
set "VENV_DIR=%CD%\.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "AUTO_MODE=0"
if /i "%~1"=="/auto" set "AUTO_MODE=1"

if not exist "runtime\logs" mkdir "runtime\logs" >nul 2>&1
for /f "delims=" %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss" 2^>nul') do set "STAMP=%%T"
if not defined STAMP set "STAMP=manual"
set "LOG_FILE=%CD%\runtime\logs\kurulum_%STAMP%.log"

echo ========================================
echo  %APP_NAME% - Tek Tik Kurulum
echo ========================================
echo.
echo Log dosyasi:
echo %LOG_FILE%
echo.
echo [INFO] Kurulum basladi. Bu islem internet hizina gore uzun surebilir.
echo [INFO] Kurulum basladi. > "%LOG_FILE%"

call :find_python
if not defined PYTHON_EXE (
    call :install_python
    if errorlevel 1 goto fail
    call :find_python
)

if not defined PYTHON_EXE (
    echo [HATA] Python bulunamadi veya kurulamadi.
    echo [HATA] Python bulunamadi veya kurulamadi. >> "%LOG_FILE%"
    goto fail
)

echo [OK] Python bulundu: %PYTHON_EXE%
echo [OK] Python bulundu: %PYTHON_EXE% >> "%LOG_FILE%"

if not exist "%VENV_PY%" (
    echo.
    echo [INFO] Proje sanal ortami olusturuluyor: .venv
    call :run "%PYTHON_EXE%" -m venv "%VENV_DIR%"
    if errorlevel 1 goto fail
) else (
    echo [OK] Sanal ortam zaten var: .venv
    echo [OK] Sanal ortam zaten var: .venv >> "%LOG_FILE%"
)

if not exist "%VENV_PY%" (
    echo [HATA] .venv olusturuldu ama Python bulunamadi.
    echo [HATA] .venv olusturuldu ama Python bulunamadi. >> "%LOG_FILE%"
    goto fail
)

echo.
echo [INFO] Pip ve temel kurulum araclari guncelleniyor...
call :run "%VENV_PY%" -m pip install --upgrade --no-cache-dir pip setuptools wheel
if errorlevel 1 goto fail

call :install_torch
if errorlevel 1 goto fail

echo.
echo [INFO] Proje kutuphaneleri kuruluyor...
call :run "%VENV_PY%" -m pip install --upgrade --no-cache-dir numpy opencv-python mss keyboard pywin32 pywebview easyocr ultralytics
if errorlevel 1 goto fail

call :pywin32_postinstall

call :install_webview2

echo.
echo [INFO] Kurulum dogrulaniyor...
call :run "%VENV_PY%" -c "import cv2, easyocr, keyboard, mss, numpy, torch, webview, win32api, win32gui; from ultralytics import YOLO; from src.phantom.app.main import main; print('PHANTOM dependency check OK')"
if errorlevel 1 goto fail

echo.
echo ========================================
echo  [BASARILI] Kurulum tamamlandi.
echo  Artik PHANTOM.bat dosyasini acabilirsiniz.
echo ========================================
echo [BASARILI] Kurulum tamamlandi. >> "%LOG_FILE%"
if "%AUTO_MODE%"=="0" pause
exit /b 0

:find_python
set "PYTHON_EXE="
if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
    set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"
    exit /b 0
)
for /f "delims=" %%P in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do (
    if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
)
if defined PYTHON_EXE exit /b 0
python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,11) else 1)" >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do (
        if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
    )
)
exit /b 0

:install_python
echo.
echo [INFO] Uygun Python bulunamadi. Python 3.11.9 indiriliyor...
call :download "%PYTHON_URL%" "%PYTHON_INSTALLER%"
if errorlevel 1 (
    echo [HATA] Python indirilemedi. Internet baglantisini kontrol edin.
    echo [HATA] Python indirilemedi. >> "%LOG_FILE%"
    exit /b 1
)
if not exist "%PYTHON_INSTALLER%" (
    echo [HATA] Python kurulum dosyasi bulunamadi.
    echo [HATA] Python kurulum dosyasi bulunamadi. >> "%LOG_FILE%"
    exit /b 1
)
echo [INFO] Python sessiz modda kuruluyor...
echo [INFO] Python sessiz modda kuruluyor... >> "%LOG_FILE%"
start /wait "" "%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=1 Include_tcltk=1 Include_test=0 SimpleInstall=1
set "PY_INSTALL_EXIT=%ERRORLEVEL%"
del /f /q "%PYTHON_INSTALLER%" >nul 2>&1
if not "%PY_INSTALL_EXIT%"=="0" (
    echo [HATA] Python kurulumu basarisiz oldu. Kod: %PY_INSTALL_EXIT%
    echo [HATA] Python kurulumu basarisiz oldu. Kod: %PY_INSTALL_EXIT% >> "%LOG_FILE%"
    exit /b 1
)
exit /b 0

:install_torch
echo.
where nvidia-smi >nul 2>&1
if errorlevel 1 (
    echo [INFO] NVIDIA GPU bulunamadi. Torch CPU surumu kuruluyor.
    call :run "%VENV_PY%" -m pip install --upgrade --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
    if errorlevel 1 exit /b 1
    exit /b 0
)

echo [INFO] NVIDIA GPU bulundu. Torch CUDA 12.1 deneniyor.
call :run "%VENV_PY%" -m pip install --upgrade --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
if not errorlevel 1 exit /b 0

echo.
echo [UYARI] CUDA Torch kurulumu basarisiz oldu. CPU surumune geciliyor.
echo [UYARI] CUDA Torch kurulumu basarisiz oldu. CPU surumune geciliyor. >> "%LOG_FILE%"
call :run "%VENV_PY%" -m pip install --upgrade --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
exit /b %ERRORLEVEL%

:pywin32_postinstall
if exist "%VENV_DIR%\Scripts\pywin32_postinstall.py" (
    echo.
    echo [INFO] pywin32 son kurulum adimi calistiriliyor...
    call :run "%VENV_PY%" "%VENV_DIR%\Scripts\pywin32_postinstall.py" -install
    if errorlevel 1 (
        echo [UYARI] pywin32 postinstall tamamlanamadi; import testi yine de kontrol edecek.
        echo [UYARI] pywin32 postinstall tamamlanamadi. >> "%LOG_FILE%"
    )
)
exit /b 0

:install_webview2
echo.
echo [INFO] Microsoft WebView2 Runtime kontrol/kurulum deneniyor...
call :download "%WEBVIEW2_URL%" "%WEBVIEW2_INSTALLER%"
if errorlevel 1 (
    echo [UYARI] WebView2 indirilemedi. Windows'ta zaten kuruluysa sorun olmaz.
    echo [UYARI] WebView2 indirilemedi. >> "%LOG_FILE%"
    exit /b 0
)
if exist "%WEBVIEW2_INSTALLER%" (
    start /wait "" "%WEBVIEW2_INSTALLER%" /silent /install
    if errorlevel 1 (
        echo [UYARI] WebView2 kurulumu tamamlanamadi. Zaten kurulu olabilir.
        echo [UYARI] WebView2 kurulumu tamamlanamadi. >> "%LOG_FILE%"
    ) else (
        echo [OK] WebView2 Runtime hazir.
        echo [OK] WebView2 Runtime hazir. >> "%LOG_FILE%"
    )
    del /f /q "%WEBVIEW2_INSTALLER%" >nul 2>&1
)
exit /b 0

:download
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%~1' -OutFile '%~2' -UseBasicParsing" >> "%LOG_FILE%" 2>&1
exit /b %ERRORLEVEL%

:run
echo.
echo [RUN] %*
echo [RUN] %* >> "%LOG_FILE%"
%* >> "%LOG_FILE%" 2>&1
set "RUN_EXIT=%ERRORLEVEL%"
if not "%RUN_EXIT%"=="0" (
    echo [HATA] Komut basarisiz oldu. Kod: %RUN_EXIT%
    echo [HATA] Komut basarisiz oldu. Kod: %RUN_EXIT% >> "%LOG_FILE%"
    echo [INFO] Detay icin log dosyasina bakin:
    echo %LOG_FILE%
)
exit /b %RUN_EXIT%

:fail
echo.
echo ========================================
echo  [HATA] Kurulum tamamlanamadi.
echo  Detayli hata logu:
echo  %LOG_FILE%
echo ========================================
pause
exit /b 1
