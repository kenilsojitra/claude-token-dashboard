@echo off
rem Runs the admin server without a browser window. Started by run_hidden.vbs.
rem If it crashes it restarts after 30 seconds. uninstall_admin.vbs ends it for good.
cd /d "%~dp0"
if not exist data mkdir data

call "%~dp0find_python.bat"
if not defined PYCMD (
  echo %date% %time% Python 3 not found - run install_admin.vbs again >> data\admin.log
  goto :eof
)

if exist data\admin.log for %%F in (data\admin.log) do if %%~zF GTR 1000000 move /y data\admin.log data\admin.log.old >nul 2>nul
echo [%date% %time%] starting: %PYCMD% >> data\admin.log

:loop
%PYCMD% admin.py --no-browser >> data\admin.log 2>&1
if errorlevel 1 (
  ping -n 31 127.0.0.1 >nul
  goto loop
)
