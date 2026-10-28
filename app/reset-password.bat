@echo off
REM ===========================================================================
REM  Forgot the password? Set a new one for an account of this installation.
REM
REM    reset-password.bat              -> lists the accounts and asks which one
REM    reset-password.bat marcelo      -> that account
REM
REM  Runs on this computer only, works with the app running. The account is
REM  enabled again if it was disabled and its open sessions are signed out.
REM  A colleague can also ask an administrator: Account ^& security ^> Reset
REM  password. Details: docs\MANUAL.html (Accounts) and tools\reset_password.py.
REM ===========================================================================
setlocal
cd /d "%~dp0"
set PYTHONNOUSERSITE=1
set PY=.python\python.exe
if not exist "%PY%" set PY=.venv\Scripts\python.exe
if not exist "%PY%" (
  echo Run install.bat first.
  if not defined NER_NOPAUSE pause
  exit /b 1
)
"%PY%" -s tools\reset_password.py %*
set RC=%ERRORLEVEL%
if not defined NER_NOPAUSE pause
exit /b %RC%
