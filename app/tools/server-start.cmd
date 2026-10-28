@echo off
REM Start the analyzer by hand (the scheduled task does this at logon).
REM Safe to run twice: serve.py exits quietly if the port is already serving.
REM Uses the private runtime install.bat built: .python\ (bundled Python of an
REM installation package) or .venv\ (a development checkout).
cd /d "%~dp0.."
set PYW=%CD%\.python\pythonw.exe
if not exist "%PYW%" set PYW=%CD%\.venv\Scripts\pythonw.exe
if not exist "%PYW%" (
  echo Run install.bat first.
  exit /b 1
)
REM Through the sign-in task when it exists. A process started with "start"
REM belongs to whoever ran this file: run from a remote or tool session, the
REM server dies the moment that session goes away, with nothing in the log
REM (17 Sep 2026). Started by the Task Scheduler it belongs to nobody's session.
set TASKNAME=NER Spatial Coverage Analyzer
schtasks /query /tn "%TASKNAME%" >nul 2>nul
if not errorlevel 1 (
  schtasks /run /tn "%TASKNAME%" >nul 2>nul
  if not errorlevel 1 (
    echo Starting through the scheduled task... give it 20-40 seconds, then open http://127.0.0.1:8000/
    echo Log: data\server.log
    exit /b 0
  )
)
start "" "%PYW%" "%CD%\tools\serve.py"
echo Starting... give it 20-40 seconds, then open http://127.0.0.1:8000/
echo Log: data\server.log
