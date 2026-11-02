# Claude Token Dashboard (Admin + User, LAN)

Counts the Claude Code tokens used on each PC (from Claude Code's local logs) and lets one admin PC
fetch everyone's usage over the same Wi-Fi / LAN. No Anthropic API, no cloud.

- `User_Setup/` - install on every user PC. Shows that user's own usage: today, last 4 hours, daily, weekly, tokens per prompt.
- `Admin_Setup/` - install on one admin PC. Fetches all users, shows everybody's usage, CSV export.
- `clean_old_versions.bat` - run first on every PC when upgrading from an older copy.
- `_shared/` - source of the files that are copied into both setups (`common.css`, `report.js`, `find_python.bat`, `ensure_python.bat`).

Python 3.8+ is installed automatically on Windows if missing. See [README_FIRST.txt](README_FIRST.txt) for the step-by-step setup.

Security: requests are signed with HMAC (password never sent) and rate-limited, but data travels as plain HTTP on the LAN - use a network you trust.
Counts cover Claude Code only (VS Code extension / CLI), not claude.ai chats, mobile or Cowork.
