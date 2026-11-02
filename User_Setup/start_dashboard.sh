#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  exec python3 user.py
elif command -v python >/dev/null 2>&1; then
  exec python user.py
else
  echo "Python 3 not found. Install it from https://www.python.org/downloads/"
  exit 1
fi
