@echo off
title Claude Token Dashboard - remove old copies
echo.
echo  ============================================================
echo   This stops EVERY running copy of the Claude Token Dashboard
echo   on this PC (old and new, admin and user) and removes their
echo   "start with Windows" shortcuts.
echo.
echo   Your saved counts (the data folders) are NOT deleted.
echo   Afterwards run install_admin.vbs / install_user.vbs again
echo   from the NEW Admin_Setup / User_Setup folders.
echo  ============================================================
echo.
pause

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$wrap = Get-CimInstance Win32_Process | Where-Object { (@('cmd.exe','wscript.exe') -contains $_.Name) -and ($_.CommandLine -match 'start_background\.bat|run_hidden\.vbs') };" ^
 "$wrap | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue };" ^
 "$py = Get-CimInstance Win32_Process | Where-Object { (@('python.exe','pythonw.exe','py.exe') -contains $_.Name) -and ($_.CommandLine -match '(user|admin|tracker)\.py') };" ^
 "$py | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue };" ^
 "$lnk = Get-ChildItem ([Environment]::GetFolderPath('Startup')) -Filter 'Claude Token Dashboard*.lnk' -ErrorAction SilentlyContinue;" ^
 "$lnk | Remove-Item -Force -ErrorAction SilentlyContinue;" ^
 "Write-Host ('Stopped ' + @($wrap).Count + ' launcher(s), ' + @($py).Count + ' tracker(s); removed ' + @($lnk).Count + ' startup shortcut(s).')"

echo.
echo  Done. Now install the NEW version (install_admin.vbs on the admin PC,
echo  install_user.vbs on each user PC).
echo.
pause
