@echo off
rem Runs the user tracker without a browser window. Started by run_hidden.vbs.
rem If it crashes it restarts after 30 seconds. uninstall_user.vbs ends it for good.
cd /d "%~dp0"
if not exist data mkdir data

call "%~dp0find_python.bat"
if not defined PYCMD (
  echo %date% %time% Python 3 not found - run install_user.vbs again >> data\user.log
  goto :eof
)

if exist data\user.log for %%F in (data\user.log) do if %%~zF GTR 1000000 move /y data\user.log data\user.log.old >nul 2>nul
echo [%date% %time%] starting: %PYCMD% >> data\user.log

:loop
%PYCMD% user.py --no-browser >> data\user.log 2>&1
if errorlevel 1 (
  ping -n 31 127.0.0.1 >nul
  goto loop
)
