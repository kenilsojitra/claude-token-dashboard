CLAUDE TOKEN DASHBOARD - USER SETUP
===================================
Counts the Claude Code tokens used on THIS PC and lets your admin see them.
You always see your own numbers on your own dashboard: today, last 4 hours, daily, weekly,
and how many tokens each prompt used.

INSTALL (once)
--------------
1. Keep this folder somewhere permanent (do not move/delete it later).
2. Double-click  install_user.vbs
   If this PC has no Python, it is downloaded and installed automatically (internet needed once,
   no admin rights needed, PATH is set for you). A black window shows the progress - just wait.
3. Your dashboard opens. Open the tab "Connection to admin", and give your
   User ID and Password to the admin. The admin adds you - the page turns green.
4. If Windows asks about the firewall, choose "Allow access" (Private networks).

DAILY USE
---------
Nothing. It runs hidden in the background and starts with Windows.
To look at your numbers: double-click  open_dashboard.vbs

REMOVE
------
Double-click  uninstall_user.vbs

WHAT THE ADMIN CAN SEE
----------------------
Your token counts (today, 4 hours, daily, weekly, lifetime), usage per model and project folder,
and the first ~100 characters of each prompt with the tokens it used.
Nothing else, and nothing goes to the internet.
To hide the prompt text: set  "share_prompt_text": false  in config.json (created on first start), restart.

FILES
-----
config.json  (created on first start): display_name, ports, share_prompt_text ...
data\        your counts, User ID/password, log (user.log)

IF THE DASHBOARD DOES NOT OPEN
------------------------------
1. Double-click  start_dashboard.bat  - it runs the tracker in a visible window and shows the exact error.
2. Or open  data\user.log  (last lines show what went wrong).
3. If you used an older version of this tool (folder "claude-token-dashboard"), run its
   uninstall_background.vbs first, so the old copy does not keep running.
