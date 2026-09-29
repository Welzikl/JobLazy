@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup-windows.ps1"
if errorlevel 1 (
  echo Setup did not finish. Read the message above.
  pause
  exit /b 1
)
echo Setup finished. Double-click Start JobLazy.cmd to open JobLazy.
pause
