@echo off
REM ===========================================================================
REM  Build the installation package of THIS installation.
REM
REM  Run this on the machine where you develop. It produces one .zip in the
REM  dist folder containing the application, the compiled screens, the
REM  manuals, the tests, every Python package it needs AND the Python runtime
REM  itself (the official python.org embeddable package) -- so the computer
REM  that receives it needs no internet and no Python at all.
REM
REM  It carries NO data: no projects, no drawings, no accounts, no passwords.
REM  That is deliberate; tools\make_package.py refuses to build otherwise.
REM
REM  This machine DOES need internet, once, to fetch the packages and the
REM  runtime to bundle (about 110 MB). Both are cached under vendor\ and
REM  checked against the pinned versions on every build.
REM  The version comes from the VERSION file: dist\ner-analyzer-<version>-windows.zip
REM
REM    build_package.bat            fetch the packages, then build
REM    build_package.bat --keep     reuse the packages already in vendor\wheels
REM ===========================================================================
setlocal
cd /d "%~dp0"

set VER=unknown
if exist VERSION set /p VER=<VERSION

echo.
echo   Building the installation package - version %VER%
echo   ================================================
echo.

set PY=.python\python.exe
if not exist "%PY%" set PY=.venv\Scripts\python.exe
if not exist "%PY%" (
  echo   [X] Run install.bat first - this needs the local environment.
  goto :fail
)
if not exist "backend\app\static\index.html" (
  echo   [X] The compiled screens are missing. Build them first:
  echo         cd frontend
  echo         npm install
  echo         npm run build
  goto :fail
)
echo   [1/3] Compiled screens found.

if /i "%~1"=="--keep" (
  if exist "vendor\wheels\*.whl" (
    echo   [2/3] Reusing the packages already in vendor\wheels.
    goto :build
  )
  echo   [2/3] vendor\wheels is empty - fetching.
)

echo   [2/3] Fetching the Windows packages to bundle ^(about 100 MB, one to
echo         three minutes^)...
if exist "vendor\wheels" rmdir /s /q "vendor\wheels"
mkdir "vendor\wheels"
REM Built for CPython 3.12 on 64-bit Windows: the bundled runtime.
REM requirements-lock-win.txt is the exact tested set, pip included (the
REM installer bootstraps pip from that wheel).
if not exist "requirements-lock-win.txt" (
  echo   [X] requirements-lock-win.txt is missing.
  goto :fail
)
"%PY%" -m pip download -r requirements-lock-win.txt --no-deps -d vendor\wheels ^
  --platform win_amd64 --python-version 3.12 --implementation cp --only-binary=:all: -q
if errorlevel 1 (
  echo   [X] Could not fetch the packages. Check the internet connection.
  goto :fail
)

:build
echo   [3/3] Fetching the runtime if needed, checking, writing the package...
"%PY%" tools\make_package.py --wheels vendor\wheels --out dist
if errorlevel 1 (
  echo   [X] Packaging refused. The message above says what it found.
  goto :fail
)

echo.
echo   Done. The .zip and its .sha256 are in the dist folder.
echo   Copy the .zip to the other computer, unzip it anywhere ^(Downloads is
echo   fine^), right-click setup.bat ^> Run as administrator - or, without
echo   administrator rights, double-click setup-noadmin.bat: it installs,
echo   starts the server and removes the installation files.
echo   Instructions: docs\INSTALL.html
echo.
if not defined NER_NOPAUSE pause
exit /b 0

:fail
echo.
if not defined NER_NOPAUSE pause
exit /b 1
