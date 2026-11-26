@echo off
cd /d "%~dp0"
echo === Thai Dub: installing ===
call "%~dp0findpy.bat"
if not defined PY ( pause & exit /b 1 )
echo Using: %PY%
%PY% --version
%PY% -m pip install --upgrade pip
%PY% -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
  echo.
  echo [ERROR] Install failed. Take a screenshot of this window and send it to Claude.
  pause & exit /b 1
)
echo.
echo === DONE. Now double-click run.bat ===
pause
