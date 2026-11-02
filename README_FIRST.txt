CLAUDE TOKEN DASHBOARD  -  Admin + User setup
=============================================

What it does
------------
* Every user PC counts its own Claude Code tokens (VS Code extension / CLI):
  today, last 4 hours, daily, weekly, lifetime, and tokens used per prompt.
* The admin PC fetches every user's data over the same Wi-Fi / LAN.
* A user sees ONLY his own usage. The admin sees everyone.
* No Anthropic API, no cloud, no internet. Everything stays inside your network.

Folders
-------
  Admin_Setup   -> for the admin PC only (one PC)
  User_Setup    -> for every user PC (the admin can share it - see below)

Python: NOTHING to install by hand. If a PC has no Python, the install step downloads the official
Python 3.12 from python.org, installs it for the current user (no admin rights needed) and adds it to
PATH by itself. It needs internet ONCE on that PC (about 25 MB) and Windows 10 / 11.
No internet on a PC? Install Python 3 on it from another PC's download, then run the install step again.

UPGRADING from an earlier copy / something does not connect?
-------------------------------------------------------------
Old copies keep running in the background and block the new ones (wrong password, dashboard not opening).
First double-click  clean_old_versions.bat  on every PC (admin and users). It stops all old copies.
Then do the steps below. Never run an OLD Admin_Setup together with a NEW User_Setup - use the same download for all.

STEP 1 - Admin PC (once)
------------------------
1. Unzip, open Admin_Setup, double-click  install_admin.vbs
2. The Admin dashboard opens in the browser. Create the admin password.
   (Later: log in with username  admin  and that password.)
3. Click "Download User Setup (to share)" -> send that User_Setup.zip to all users
   (pen drive, WhatsApp, e-mail, shared folder ...).

STEP 2 - Every user PC (once)
-----------------------------
1. Unzip User_Setup anywhere (keep the folder there), double-click  install_user.vbs
2. The user's own dashboard opens. The tab "Connection to admin" shows
   a User ID and a Password. The user gives these two to the admin.

STEP 3 - Admin connects the user
--------------------------------
In the Admin dashboard click "+ Add user", type the User ID and Password
(IP address is optional - the PC is found automatically on the same network),
click "Add & connect". The user's tab turns green: "Connected to admin".

From now on
-----------
* The admin PC fetches all users every 30 minutes, or any time with "Fetch" / "Fetch all now".
* If a user PC is off, the admin keeps the last fetched data and shows when it was fetched.
* Admin dashboard: all users side by side (today / 4h / 7 days / lifetime), click "Open" for
  one user's full daily, weekly and per-prompt details. "Export CSV" gives daily usage of everybody.

Good to know
------------
* Same Wi-Fi / LAN is required. If Windows asks about the firewall, choose "Allow access"
  (Private networks). If it still does not connect: right-click allow_firewall.bat -> Run as administrator
  (in both folders).
* Security: the password never travels over the network - every request is signed (HMAC) and
  checked on both sides, wrong attempts are rate-limited. The data itself is NOT encrypted on the LAN
  (plain HTTP), so use it on a network you trust.
* The admin can see the first ~100 characters of each prompt a user typed. The user is told this on his
  Connection tab. To hide prompt text, set "share_prompt_text": false in User_Setup\config.json.
* Counts come from Claude Code's logs on each PC. claude.ai chats, mobile and Cowork are not included.
  "Tokens" = input + output; tick "include cache tokens" to add cache read/write.
* Lifetime = what is still in the PC's Claude Code logs (old logs may be deleted by Claude Code).
* Forgot the admin password: open a terminal in Admin_Setup and run   python admin.py --reset-password
* A user can reset his password on his Connection tab - the admin then uses "Edit" and types the new one.
* Open the Admin dashboard from other PCs too: set "lan_access": true in Admin_Setup\config.json
  and restart. Users can then log in there with their own User ID + password (they see only their data).
