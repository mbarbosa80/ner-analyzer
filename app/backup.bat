@echo off
REM ===========================================================================
REM  Back up everything the application knows: the database (a consistent
REM  copy, valid even while the server is running) and the uploaded documents.
REM
REM    backup.bat                            -> data\backup-YYYYMMDD-HHMMSS\
REM    backup.bat --to D:\NER-backups        -> a folder of your choice
REM    backup.bat --restore data\backup-...  -> put a backup back (server stopped)
REM
REM  Details: tools\backup.py and docs\INSTALL.html.
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
"%PY%" tools\backup.py %*
if not defined NER_NOPAUSE pause
