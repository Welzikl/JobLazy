@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-windows.ps1"
if errorlevel 1 (
  echo JobLazy stopped. Read the message above or see docs\WINDOWS-QUICKSTART.md.
  pause
  exit /b 1
)
