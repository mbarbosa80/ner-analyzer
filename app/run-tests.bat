@echo off
REM ===========================================================================
REM  Run the application's own test suite on this installation.
REM
REM  Around 800 tests, one to two minutes. All of them passing means the
REM  installation is sound: every component loads, the rules compute what the
REM  manual says, the exports have the shape the manual describes.
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
"%PY%" -m pytest tests -q %*
set RC=%errorlevel%
echo.
if "%RC%"=="0" (echo   All tests passed.) else (echo   Some tests FAILED - see above. Exit code %RC%.)
if not defined NER_NOPAUSE pause
exit /b %RC%
