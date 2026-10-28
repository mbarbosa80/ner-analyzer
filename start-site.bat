@echo off
rem Serves the NER Analyzer website on this computer: http://localhost:8080
rem Close this window to stop it.
cd /d "%~dp0"
set PORT=8080
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
echo.
echo  NER Analyzer website  ^>  http://localhost:%PORT%
echo  Close this window to stop the site.
echo.
start "" "http://localhost:%PORT%/"
%PY% -m http.server %PORT% --bind 127.0.0.1
if errorlevel 1 (
  echo.
  echo  Python was not found or port %PORT% is busy. You can still open index.html directly.
  pause
)
