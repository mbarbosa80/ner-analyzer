@echo off
REM ===========================================================================
REM  Start the application automatically when this user signs in, and keep
REM  it running.
REM
REM  Creates two per-user Windows Scheduled Tasks (no administrator rights):
REM
REM    "NER Spatial Coverage Analyzer"  at YOUR sign-in, starts the server with
REM                                     no console window (tools\serve.py, log
REM                                     in data\server.log)
REM    "NER Analyzer watchdog"          every two minutes, probes the server
REM                                     and starts it again if it stopped
REM                                     answering (log in data\watchdog.log)
REM
REM  The sign-in task is registered for the person signed in only (a trigger
REM  for every user of the computer is an administrator's to create, and was
REM  refused - "Access is denied" - on installations made without the rights).
REM  Should Windows refuse even that, the watchdog is still installed: it
REM  starts the server within two minutes of signing in, which is the same
REM  result a little later.
REM
REM  Run  autostart.bat remove  to undo both.
REM
REM  The interpreter is the private runtime install.bat built: .python\ (the
REM  bundled Python of an installation package) or .venv\ (a development
REM  checkout). pythonw.exe runs without a console window.
REM ===========================================================================
setlocal
cd /d "%~dp0"

set TASKNAME=NER Spatial Coverage Analyzer
set WATCHDOG=NER Analyzer watchdog

if /i "%~1"=="remove" (
  schtasks /delete /tn "%TASKNAME%" /f >nul 2>nul
  schtasks /delete /tn "%WATCHDOG%" /f >nul 2>nul
  echo Removed. The server no longer starts at sign-in, and the watchdog is gone.
  echo A server that is running now keeps running until stop.bat.
  if not defined NER_NOPAUSE pause
  exit /b 0
)

set PYW=%~dp0.python\pythonw.exe
if not exist "%PYW%" set PYW=%~dp0.venv\Scripts\pythonw.exe
if not exist "%PYW%" (
  echo Run install.bat first.
  if not defined NER_NOPAUSE pause
  exit /b 1
)

REM serve.py sends its output to data\server.log and exits quietly if the
REM port is already answering. The task is written as XML with a trigger for
REM this user only - see tools\signin-task.ps1 for why "schtasks /sc onlogon"
REM is not used.
set SIGNIN=1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\signin-task.ps1" -Name "%TASKNAME%" -Pythonw "%PYW%" -Script "%~dp0tools\serve.py"
if errorlevel 1 set SIGNIN=
if not defined SIGNIN (
  echo.
  echo  [*] Windows refused the sign-in task ^(message above^). The watchdog is
  echo      installed all the same: it starts the server within two minutes of
  echo      signing in.
  echo.
)

REM The watchdog: every two minutes, through a .vbs so no console flashes.
REM Installed whether or not the sign-in task was: it is the one that keeps
REM the server up, and on its own it also brings it up after a sign-in.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\watchdog-install.ps1"
if errorlevel 1 (
  if defined SIGNIN (echo Could not create the watchdog task. The sign-in task was created.) else (echo Could not create the watchdog task either. Nothing starts the server by itself: use start.bat.)
  if not defined NER_NOPAUSE pause
  exit /b 1
)

REM A task made with the Task Scheduler defaults is ended when a laptop goes
REM on battery, is never started on battery, and is ended after 72 hours. For
REM a server that is a silent death with nothing in the log. The sign-in task
REM is registered with those three already off; task-harden.ps1 turns them off
REM for the watchdog and confirms them on the sign-in task. If it cannot, the
REM tasks stay as they are and it says what to untick by hand.
if defined SIGNIN powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\task-harden.ps1" -Name "%TASKNAME%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\task-harden.ps1" -Name "%WATCHDOG%"

if not defined SIGNIN (
  echo.
  echo  Done, without the sign-in task: the watchdog starts the server within
  echo  two minutes of signing in, and brings it back if it ever stops answering.
  echo  Open http://127.0.0.1:8000 in a browser.
  echo.
  echo  To stop it:                           stop.bat
  echo  To undo the watchdog:                 autostart.bat remove
  echo.
  if not defined NER_NOPAUSE pause
  exit /b 0
)

echo.
echo  Done. The server will start automatically at sign-in, and the watchdog
echo  brings it back within two minutes if it ever stops answering.
echo  Open http://127.0.0.1:8000 in a browser.
echo.
echo  To start it now without signing out:  schtasks /run /tn "%TASKNAME%"
echo  To stop it:                           stop.bat
echo  To undo both tasks:                   autostart.bat remove
echo.
if not defined NER_NOPAUSE pause
