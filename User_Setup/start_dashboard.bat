@echo off
rem Visible-window mode (good for a first test). For normal use run install_user.vbs instead.
cd /d "%~dp0"
title Claude Token Dashboard - User

call "%~dp0ensure_python.bat"
if errorlevel 1 exit /b 1

title Claude Token Dashboard - User
%PYCMD% user.py
pause
