@echo off
rem BeamNG Radio - build BeamNGRadio.exe
rem Run by double-click or from cmd. The window always waits for a key at the end.
setlocal
cd /d "%~dp0"
echo === BeamNG Radio build ===

rem 1) find Python 3.11+ (py launcher first, then python)
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
%PY% --version
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.11+ from python.org and tick "Add python.exe to PATH".
    goto :fail
)

rem 2) virtual environment, so nothing pollutes the system Python
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment .venv ...
    %PY% -m venv .venv
    if errorlevel 1 goto :fail
)
call ".venv\Scripts\activate.bat"
if errorlevel 1 goto :fail

rem 3) dependencies (through python -m, so pip/pyinstaller do not need to be on PATH)
echo Installing dependencies ...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install failed. Check the internet connection and the messages above.
    goto :fail
)

rem 4) build the exe
echo Building exe with PyInstaller (spec: BeamNGRadio.spec) ...
python -m PyInstaller --noconfirm --clean BeamNGRadio.spec
if errorlevel 1 (
    echo [ERROR] PyInstaller failed. See the messages above.
    goto :fail
)
if not exist "dist\BeamNGRadio\BeamNGRadio.exe" (
    echo [ERROR] PyInstaller finished but dist\BeamNGRadio\BeamNGRadio.exe was not created.
    goto :fail
)

echo.
echo [OK] Done: dist\BeamNGRadio\BeamNGRadio.exe
echo      On the target PC VLC 64-bit must be installed (videolan.org).
goto :end

:fail
echo.
echo [FAILED] Build did not finish.

:end
echo.
pause
endlocal
