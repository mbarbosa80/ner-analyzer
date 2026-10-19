@echo off
REM ===========================================================================
REM  NER Spatial Coverage Analyzer - stop the server.
REM
REM  Stops only THIS folder's server (the windowless one started by
REM  autostart / server-start, or the console one started by start.bat).
REM  It never touches other Python programs on the computer.
REM ===========================================================================
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\server-stop.ps1"
if not defined NER_NOPAUSE pause
