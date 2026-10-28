@echo off
REM Stop the analyzer. See server-stop.ps1 -- it targets this project's own
REM process by command line rather than killing every pythonw.exe on the box.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0server-stop.ps1"
