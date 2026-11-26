@echo off
cd /d "%~dp0"
call "%~dp0findpy.bat"
if not defined PY ( pause & exit /b 1 )
%PY% "%~dp0thai_dub.py" --thai %*
pause
