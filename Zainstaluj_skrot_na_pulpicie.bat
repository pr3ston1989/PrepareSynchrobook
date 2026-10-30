@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install_shortcut.ps1"
set "result=%ERRORLEVEL%"
pause
exit /b %result%
