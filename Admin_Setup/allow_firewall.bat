@echo off
rem OPTIONAL. Only needed if user PCs are not found automatically (UDP 18767 blocked),
rem or if you turned on "lan_access" in config.json (dashboard reachable from other PCs).
rem Right-click this file -> "Run as administrator".
net session >nul 2>&1
if not %errorlevel%==0 (
  echo Please right-click this file and choose "Run as administrator".
  pause
  exit /b 1
)
netsh advfirewall firewall delete rule name="Claude Token Dashboard (Admin discovery)" >nul 2>&1
netsh advfirewall firewall delete rule name="Claude Token Dashboard (Admin web)" >nul 2>&1
netsh advfirewall firewall add rule name="Claude Token Dashboard (Admin discovery)" dir=in action=allow protocol=UDP localport=18767 profile=private,domain
netsh advfirewall firewall add rule name="Claude Token Dashboard (Admin web)" dir=in action=allow protocol=TCP localport=18800-18819 profile=private,domain
echo.
echo Done.
pause
