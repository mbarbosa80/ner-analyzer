@echo off
REM ===========================================================================
REM  NER Spatial Coverage Analyzer - start the server in a console window.
REM
REM  The window IS the server: closing it stops the application. A browser
REM  opens at http://127.0.0.1:8000 once it is up (20-40 s on a cold start).
REM
REM    start.bat                 default port 8000
REM    start.bat --port 8080     another port
REM    start.bat --no-browser    do not open a browser
REM
REM  For a server with no window that comes back after a reboot, run
REM  autostart.bat once instead (see docs\INSTALL.html).
REM
REM  The interpreter is the private runtime install.bat built: .python\ (the
REM  bundled Python of an installation package) or .venv\ (a development
REM  checkout using the machine's Python).
REM ===========================================================================
setlocal
cd /d "%~dp0"
set PY=.python\python.exe
if not exist "%PY%" set PY=.venv\Scripts\python.exe
if not exist "%PY%" (
  echo Run install.bat first.
  if not defined NER_NOPAUSE pause
  exit /b 1
)
"%PY%" run.py %*
if errorlevel 1 (
  if not defined NER_NOPAUSE pause
)
