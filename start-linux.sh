#!/bin/bash
# Start corparius on Linux: ./start-linux.sh  (or double-click if your file
# manager runs scripts). No terminal typing beyond this needed.
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  python3 start.py
else
  echo
  echo "corparius needs Python 3.10 or newer, and it was not found."
  echo "Install it with your package manager, e.g. sudo apt install python3, then run this again."
  echo
fi
