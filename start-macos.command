#!/bin/bash
# Double-click this file to start corparius on macOS. No terminal typing needed.
# (First time: right-click > Open, to get past Gatekeeper.)
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  python3 start.py
else
  echo
  echo "corparius needs Python 3.10 or newer, and it was not found."
  echo
  echo "  1. Install it from https://www.python.org/downloads/"
  echo "  2. Double-click this file again."
  echo
fi
echo
read -n 1 -s -r -p "Press any key to close this window."
echo
