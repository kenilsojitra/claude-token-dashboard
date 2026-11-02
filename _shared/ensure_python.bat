@echo off
rem Makes sure Python 3.8+ is installed. If it is missing, downloads the official installer
rem from python.org and installs it silently for the current user (no admin needed) and
rem adds it to PATH. Needs internet only for this one-time download (about 25 MB).
rem Exit code 0 = Python is ready, 1 = could not install.
cd /d "%~dp0"
title Claude Token Dashboard - checking Python

call "%~dp0find_python.bat"
if defined PYCMD goto have

echo.
echo  ============================================================
echo   Python is not installed on this PC.
echo   Installing it now - one time only, about 1-2 minutes.
echo   Please wait and do not close this window.
echo  ============================================================
echo.

set "A=%PROCESSOR_ARCHITECTURE%"
if /i "%PROCESSOR_ARCHITEW6432%"=="AMD64" set "A=AMD64"
if /i "%PROCESSOR_ARCHITEW6432%"=="ARM64" set "A=ARM64"
set "PYURL=https://www.python.org/ftp/python/3.12.10/python-3.12.10.exe"
if /i "%A%"=="AMD64" set "PYURL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
if /i "%A%"=="ARM64" set "PYURL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-arm64.exe"
set "PYEXE=%TEMP%\ctd-python-installer.exe"
if exist "%PYEXE%" del /f /q "%PYEXE%" >nul 2>nul

echo  [1/3] Downloading Python ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -UseBasicParsing -Uri '%PYURL%' -OutFile '%PYEXE%' } catch { exit 1 }" >nul 2>nul
if not exist "%PYEXE%" curl.exe -L --fail -s -o "%PYEXE%" "%PYURL%"
if not exist "%PYEXE%" goto trywinget

echo  [2/3] Installing Python (and adding it to PATH) ...
start /wait "" "%PYEXE%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 InstallLauncherAllUsers=0 Include_test=0 Include_doc=0 Include_tcltk=0 Shortcuts=0 AssociateFiles=0
del /f /q "%PYEXE%" >nul 2>nul
call "%~dp0find_python.bat"
if defined PYCMD goto installed

:trywinget
echo  Trying Windows Package Manager (winget) ...
where winget >nul 2>nul
if errorlevel 1 goto failed
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
call "%~dp0find_python.bat"
if defined PYCMD goto installed

:failed
echo.
echo  ============================================================
echo   Python could NOT be installed automatically.
echo   - Check that this PC is connected to the internet and try again, or
echo   - install Python 3 by hand from https://www.python.org/downloads/
echo     (tick "Add python.exe to PATH"), then run this setup again.
echo  ============================================================
echo.
pause
exit /b 1

:installed
echo  [3/3] Python installed.
echo.
timeout /t 2 /nobreak >nul 2>nul

:have
exit /b 0
