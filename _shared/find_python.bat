@echo off
rem Sets PYCMD to a working Python 3.8+ command (or leaves it empty if there is none).
rem Looks in this order: the "py" launcher, the usual per-user / all-users install folders, then "python" on PATH.
rem (Checking PATH last avoids the Microsoft Store "python" stub.)
set "PYCMD="

py -3 -c "import sys;sys.exit(sys.version_info<(3,8))" >nul 2>nul
if not errorlevel 1 set "PYCMD=py -3"
if defined PYCMD goto :eof

for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%~D\python.exe" "%%~D\python.exe" -c "import sys;sys.exit(sys.version_info<(3,8))" >nul 2>nul && set "PYCMD="%%~D\python.exe""
if defined PYCMD goto :eof

for /d %%D in ("%ProgramFiles%\Python3*") do if exist "%%~D\python.exe" "%%~D\python.exe" -c "import sys;sys.exit(sys.version_info<(3,8))" >nul 2>nul && set "PYCMD="%%~D\python.exe""
if defined PYCMD goto :eof

python -c "import sys;sys.exit(sys.version_info<(3,8))" >nul 2>nul
if not errorlevel 1 set "PYCMD=python"
goto :eof
