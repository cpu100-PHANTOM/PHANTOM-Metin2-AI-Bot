@echo off
cd /d "%~dp0"
echo ========================================
echo  PHANTOM Bot - Kurulum Baslatiyor...
echo ========================================
echo.

:: ============================================
:: 1. PYTHON KONTROLU
:: ============================================
python --version >nul 2>&1
if %errorlevel% == 0 (
    echo [OK] Python zaten yuklu.
    python --version
    goto CHECK_CUDA
)

echo [!] Python bulunamadi. Indiriliyor...
echo.

set PYTHON_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
set PYTHON_INSTALLER=%TEMP%\python_installer.exe

echo Python indiriliyor...
powershell -Command "Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%PYTHON_INSTALLER%' -UseBasicParsing"

if not exist "%PYTHON_INSTALLER%" (
    echo [HATA] Python indirilemedi. Internet baglantinizi kontrol edin.
    pause
    exit /b 1
)

echo Python kuruluyor...
"%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1

if %errorlevel% neq 0 (
    echo [HATA] Python kurulumu basarisiz oldu.
    pause
    exit /b 1
)

echo [OK] Python basariyla kuruldu!
del /f /q "%PYTHON_INSTALLER%" >nul 2>&1

:: PATH'i yenile
for /f "tokens=*" %%i in ('powershell -Command "[Environment]::GetEnvironmentVariable(\"PATH\", \"User\")"') do set "PATH=%%i;%PATH%"
python -m ensurepip --upgrade >nul 2>&1
python -m pip install --upgrade pip >nul 2>&1

:: ============================================
:: 2. CUDA KONTROLU
:: ============================================
:CHECK_CUDA
echo.
echo ========================================
echo  CUDA Kontrolu Yapiliyor...
echo ========================================

:: Nvidia GPU var mi kontrol et
nvidia-smi >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] NVIDIA GPU bulunamadi. CUDA kurulmayacak.
    echo     Torch CPU modunda kurulacak.
    set CUDA_FOUND=0
    goto INSTALL_LIBS
)

echo [OK] NVIDIA GPU tespit edildi.

:: PyTorch CUDA surumu, sistemde tam CUDA Toolkit (nvcc) kurulu olmasini gerektirmez!
:: Sadece NVIDIA GPU olmasi ve suruculerin yuklu olmasi yeterlidir.
echo [OK] Sistem CUDA destekliyor. PyTorch CUDA (GPU) surumu yuklenecek.
set CUDA_FOUND=1
goto INSTALL_LIBS

:: ============================================
:: 3. KUTUPHANELER
:: ============================================
:INSTALL_LIBS
echo.
echo ========================================
echo  Kutuphaneler Kuruluyor...
echo ========================================
echo.

:: Torch: CUDA varsa GPU versiyonu, yoksa CPU
if "%CUDA_FOUND%"=="1" (
    echo [GPU] Torch CUDA 12.1 versiyonu kuruluyor...
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
) else (
    echo [CPU] Torch CPU versiyonu kuruluyor...
    pip install torch torchvision torchaudio
)

if %errorlevel% neq 0 (
    echo [HATA] Torch yuklenemedi.
    pause
    exit /b 1
)

:: Diger kutuphaneler
pip install opencv-python numpy mss keyboard ultralytics pywin32 pyglet easyocr pywebview

if %errorlevel% neq 0 (
    echo.
    echo [HATA] Bazi kutuphaneler yuklenemedi.
    pause
    exit /b 1
)

echo.
echo ========================================
if "%CUDA_FOUND%"=="1" (
    echo  [BASARILI] Kurulum tamamlandi! (GPU - CUDA 12.1)
) else (
    echo  [BASARILI] Kurulum tamamlandi! (CPU modu)
)
echo  Botu baslatmak icin PHANTOM.bat calistirin.
echo ========================================
pause
