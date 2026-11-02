@echo off
rem OPTIONAL. Only needed if the admin PC cannot connect because the Windows firewall blocks it.
rem Right-click this file -> "Run as administrator".
net session >nul 2>&1
if not %errorlevel%==0 (
  echo Please right-click this file and choose "Run as administrator".
  pause
  exit /b 1
)
netsh advfirewall firewall delete rule name="Claude Token Dashboard (User)" >nul 2>&1
netsh advfirewall firewall add rule name="Claude Token Dashboard (User)" dir=in action=allow protocol=TCP localport=18766-18785 profile=private,domain
echo.
echo Done. The admin PC can now reach this PC on the local network (ports 18766-18785).
pause
