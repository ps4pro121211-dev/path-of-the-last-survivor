@echo off
rem Finds a working Python and stores the command in PY
set "PY="
py -3.12 --version >nul 2>nul && set "PY=py -3.12"
if not defined PY py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
if defined PY goto :eof
echo.
echo ============================================================
echo  [ERROR] Python is not installed.
echo.
echo  1. Download Python 3.12 (the page will open now)
echo  2. When installing, CHECK the box "Add python.exe to PATH"
echo  3. Run install.bat again
echo ============================================================
start "" "https://www.python.org/downloads/release/python-3128/"
