CLAUDE TOKEN DASHBOARD - ADMIN SETUP
====================================
Run this on ONE PC. It collects every user's Claude Code token usage over the local network.

INSTALL (once)
--------------
1. Double-click  install_admin.vbs
   If this PC has no Python, it is downloaded and installed automatically (internet needed once,
   no admin rights needed, PATH is set for you). A black window shows the progress - just wait.
2. Admin dashboard opens. First time: create the admin password. Login name is  admin.
3. "Download User Setup (to share)" gives you User_Setup.zip for your users.
   (It is also the folder User_Setup next to Admin_Setup.)
4. For each user: "+ Add user" -> User ID + Password shown on that user's PC.
   IP address is optional if the user PC is on the same network (it announces itself).

DAILY USE
---------
Runs hidden in the background and starts with Windows. Open it with  open_admin.vbs
Remove it with  uninstall_admin.vbs

THE ADMIN PC MUST BE ON for fetching to happen (every 30 minutes, set fetch_interval_minutes in config.json).

config.json (created on first start)
-----------------------------------
port                   dashboard port (default 18800)
lan_access             true = also open the dashboard from other PCs (http://<admin-ip>:18800/)
                       users can then log in with their own User ID + password and see only their data
fetch_interval_minutes how often all users are fetched
default_user_port      18766 (the port user PCs listen on)

Forgot the admin password? In this folder run:   python admin.py --reset-password

Problems? Look at data\admin.log. Users not found? Add their IP address manually, or run
allow_firewall.bat as administrator (and on the user PCs too).

IF THE DASHBOARD DOES NOT OPEN
------------------------------
Double-click  start_admin.bat  - it runs the server in a visible window and shows the exact error.
Or open  data\admin.log. If you used an older version of this tool, run its uninstall_background.vbs first.
