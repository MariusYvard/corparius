@echo off
REM Double-click this file to start corparius on Windows. No terminal needed.
cd /d "%~dp0"
set "PYCMD="
where py >nul 2>nul && set "PYCMD=py -3"
if not defined PYCMD (
  where python >nul 2>nul && set "PYCMD=python"
)
if not defined PYCMD (
  echo.
  echo corparius needs Python 3.10 or newer, and it was not found on this PC.
  echo.
  echo   1. Install it from https://www.python.org/downloads/
  echo   2. On the first screen, tick "Add Python to PATH"
  echo   3. Double-click this file again.
  echo.
  pause
  exit /b 1
)
%PYCMD% start.py
echo.
pause
