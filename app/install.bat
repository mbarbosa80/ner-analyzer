@echo off
REM ===========================================================================
REM  NER Spatial Coverage Analyzer - installer (Windows)
REM
REM  Run this once, after unzipping. It needs NO internet, NO administrator
REM  rights and NO Python on the computer: the package carries its own Python
REM  runtime (the official python.org "embeddable package") and every Python
REM  package the application uses. The installer unpacks the runtime into
REM  .python\ inside this folder and installs the packages into it.
REM
REM  It touches nothing outside this folder. There is no registry entry, no
REM  service, no system-wide install: removing the folder removes the app.
REM
REM  Development checkouts without vendor\python\ fall back to the Python
REM  installed on the machine (3.11+) and a .venv\ folder - see the end.
REM
REM  Set NER_NOPAUSE=1 to run it without the "press any key" stops (automation).
REM
REM  (c) 2026 Marcelo Barbosa. Free software, GNU AGPL-3.0 - see LICENSE.txt and NOTICE.txt.
REM ===========================================================================
REM --- In an unzipped installation package the way in is setup.bat, which
REM     installs into a folder of its own and removes the package afterwards.
REM     Whoever opens install.bat there by habit is handed over to it. In the
REM     folder setup.bat installed (setup.bat is not copied there), in a
REM     development checkout (no MANIFEST.txt), or when setup.bat itself
REM     calls this script, install.bat installs in place as always. This
REM     runs before delayed expansion is switched on, which setup.bat must
REM     not inherit.
if defined NER_FROM_SETUP goto :install_here
if not exist "%~dp0setup.bat" goto :install_here
if not exist "%~dp0MANIFEST.txt" goto :install_here
echo.
echo   This is the installation package: handing over to setup.bat, which
echo   installs the application in its own folder and cleans up afterwards.
call "%~dp0setup.bat" %*
exit /b
:install_here
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set VER=unknown
if exist VERSION set /p VER=<VERSION

echo.
echo   NER Spatial Coverage Analyzer %VER% - installation
echo   ==================================================
echo.

echo %CD% | findstr /i "OneDrive Dropbox" >nul
if not errorlevel 1 (
  echo   [*] This folder is inside OneDrive or Dropbox. They sync files under
  echo       a running program, and the database needs file locks they do not
  echo       provide. Prefer a local folder such as C:\NER.
  echo.
)

REM --- Which runtime? The bundled one when the package carries it. ----------
set EMBED=
for %%F in ("vendor\python\python-3.12.*-embed-amd64.zip") do set EMBED=%%~F
if defined EMBED goto :embedded
goto :sysvenv


REM ===========================================================================
:embedded
REM ===========================================================================
echo   [1/6] Bundled Python runtime: %EMBED%

REM --- The C++ runtime. numpy, pandas and shapely carry their own copy of
REM     msvcp140.dll; PyMuPDF, OR-Tools and RapidFuzz expect the system one,
REM     which nearly every Windows already has (any Microsoft Visual C++
REM     Redistributable 2015-2022 puts it there). When it is missing, the
REM     installer places the copy numpy ships next to python.exe: an
REM     app-local runtime, which is how Microsoft says to deploy it without
REM     an installer. No administrator rights either way.
set VCRT=1
if not exist "%SystemRoot%\System32\msvcp140.dll" set VCRT=
if defined VCRT (
  echo   [2/6] Visual C++ runtime present on this computer.
) else (
  echo   [2/6] Visual C++ runtime ^(msvcp140.dll^) not found on this computer.
  echo         The copy bundled with the packages will be used instead.
)

REM --- Unpack the runtime ---------------------------------------------------
if exist ".python" (
  echo   [3/6] Removing the previous runtime...
  rmdir /s /q ".python" >nul 2>nul
  if exist ".python\python.exe" (
    echo   [X] The previous runtime is in use - the application is probably
    echo       running. Run stop.bat, then run this file again.
    goto :fail
  )
)
echo   [3/6] Unpacking the private Python runtime into .python\ ...
mkdir ".python"
tar -xf "%EMBED%" -C ".python" >nul 2>nul
set PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe
if not exist ".python\python.exe" (
  "%PS%" -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%CD%\%EMBED%' -DestinationPath '%CD%\.python' -Force"
)
if not exist ".python\python.exe" (
  echo   [X] Could not unpack %EMBED%. Is the zip complete? Check its .sha256.
  goto :fail
)

REM The ._pth file IS the runtime's search path: the standard library zip,
REM the runtime folder, the packages installed below, and this application.
REM It also isolates the runtime completely - no PYTHONPATH, no user
REM site-packages, nothing from any other Python on the machine.
> ".python\python312._pth" (
  echo python312.zip
  echo .
  echo Lib\site-packages
  echo ..\backend
  echo import site
)

.python\python.exe -c "import sys, sqlite3, ssl, ctypes; print('         Python ' + sys.version.split()[0] + ' runs from .python')"
if errorlevel 1 (
  echo   [X] The bundled Python could not start. A security policy on this
  echo       computer may be blocking programs in this folder. Try a folder
  echo       such as C:\NER, or ask the administrator about AppLocker.
  goto :fail
)
if exist "%PS%" "%PS%" -NoProfile -ExecutionPolicy Bypass -Command "$s = Get-AuthenticodeSignature '.python\python.exe'; if ($s.Status -eq 'Valid') { '         publisher: ' + $s.SignerCertificate.Subject.Split(',')[0].Replace('CN=','') } else { '         [*] python.exe signature: ' + $s.Status }"

REM --- The package manager, from the bundled wheel --------------------------
REM The embeddable runtime has no ensurepip. A wheel is a zip, and pip can run
REM straight out of its own wheel; it is loaded through runpy rather than as
REM "python pip.whl\pip" because pip refuses to install itself on Windows when
REM it sees "pip" as the program name (pip issue 1299). Run this way it is an
REM ordinary install: pip lands in .python\Lib\site-packages with its RECORD.
set PIPWHL=
for %%F in ("vendor\wheels\pip-*.whl") do set PIPWHL=%%~F
if not defined PIPWHL (
  echo   [X] vendor\wheels has no pip wheel. This package is incomplete.
  goto :fail
)
echo   [4/6] Installing the package manager...
.python\python.exe -s -c "import sys, runpy; sys.path.insert(0, sys.argv.pop(1)); runpy.run_module('pip', run_name='__main__', alter_sys=True)" "%PIPWHL%" install --quiet --no-warn-script-location --no-index --find-links vendor\wheels --ignore-installed pip
if errorlevel 1 (
  echo   [X] pip could not be installed into the runtime.
  goto :fail
)

REM --- The application packages, exactly the tested set ---------------------
set REQS=requirements-lock-win.txt
if not exist "%REQS%" (
  echo   [X] %REQS% is missing. This package is incomplete.
  goto :fail
)
REM -s and --ignore-installed (2.18.1): pip must see only this runtime. On one
REM machine a stray %%APPDATA%%\Python\Python312\site-packages (left by some
REM "pip install --user") made pip report pymupdf "already satisfied", nothing
REM was copied into .python\, and the server - which the ._pth file does keep
REM isolated - started without it. The three must see the same environment.
set PYTHONNOUSERSITE=1
echo   [5/6] Installing the application packages ^(%REQS%, no internet needed^)...
.python\python.exe -s -m pip install --no-warn-script-location --no-index --find-links vendor\wheels --no-deps --ignore-installed -r %REQS%
if errorlevel 1 (
  echo.
  echo   [X] Installation failed. The message above says why. The bundled
  echo       packages are built for the bundled Python 3.12 runtime, so a
  echo       failure here means an incomplete or damaged package: check the
  echo       zip against its .sha256 and unzip it again.
  goto :fail
)

if not defined VCRT (
  set VCSRC=
  for %%F in (".python\Lib\site-packages\numpy.libs\msvcp140-*.dll") do set VCSRC=%%~F
  if defined VCSRC (
    copy /y "!VCSRC!" ".python\msvcp140.dll" >nul
    echo         msvcp140.dll placed in .python\ ^(the copy numpy ships^).
  ) else (
    echo   [*] No bundled msvcp140.dll found. If the check below fails, install
    echo       the Microsoft Visual C++ Redistributable 2015-2022 ^(x64^).
  )
)

echo ok> ".python\.deps-installed"
set PY=.python\python.exe
goto :verify


REM ===========================================================================
:sysvenv
REM  No bundled runtime (a development checkout): use the machine's Python.
REM ===========================================================================
echo   [1/5] No bundled runtime in vendor\python - using the Python installed
echo         on this computer.
set PYEXE=
for %%C in ("py -3.12" "py -3" "python") do (
  if "!PYEXE!"=="" (
    %%~C -c "import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>nul
    if !errorlevel!==0 set PYEXE=%%~C
  )
)
if "%PYEXE%"=="" (
  echo   [X] Python 3.11 or newer was not found on this computer, and this
  echo       copy has no bundled runtime. Either use the installation package
  echo       ^(build_package.bat makes one that needs no Python^), or install
  echo       Python 3.12 ^(64-bit^) from https://www.python.org/downloads/windows/
  echo       ticking "Add python.exe to PATH", and run this file again.
  goto :fail
)
for /f "delims=" %%V in ('%PYEXE% -c "import sys;print(sys.version.split()[0])"') do set PYVER=%%V
echo         Python %PYVER% found.

for /f "delims=" %%A in ('%PYEXE% -c "import struct;print(struct.calcsize('P')*8)"') do set PYBITS=%%A
if not "%PYBITS%"=="64" (
  echo   [X] This is 32-bit Python. The packages are 64-bit.
  goto :fail
)
echo   [2/5] 64-bit confirmed.

if exist ".venv" (
  echo   [3/5] Removing the previous environment...
  rmdir /s /q ".venv"
)
echo   [3/5] Creating the private Python environment ^(.venv^)...
%PYEXE% -m venv .venv
if errorlevel 1 (
  echo   [X] Could not create the environment. If this folder is on a network
  echo       drive or inside OneDrive, copy it to a local folder such as
  echo       C:\NER and try again.
  goto :fail
)

echo   [4/5] Installing the application packages...
set INSTALLED=
set REQS=requirements-win.txt
if exist "requirements-lock-win.txt" set REQS=requirements-lock-win.txt
if exist "vendor\wheels\*.whl" (
  if "%PYVER:~0,4%"=="3.12" (
    echo         from the bundled copies - no internet needed ^(%REQS%^)
    .venv\Scripts\python.exe -s -m pip install --quiet --no-index --find-links vendor\wheels --upgrade pip >nul 2>nul
    .venv\Scripts\python.exe -s -m pip install --no-warn-script-location --no-index --find-links vendor\wheels --no-deps -r %REQS%
    if not errorlevel 1 set INSTALLED=1
  ) else (
    echo         the bundled packages are built for Python 3.12 and this is %PYVER%
  )
)
if not defined INSTALLED (
  echo         from the internet ^(this needs a connection^)...
  .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
  .venv\Scripts\python.exe -m pip install -r requirements-win.txt
  if errorlevel 1 (
    echo.
    echo   [X] Installation failed. The message above says why.
    goto :fail
  )
)
echo ok> ".venv\.deps-installed"
set PY=.venv\Scripts\python.exe
goto :verify


REM ===========================================================================
:verify
REM  Prove it actually works: load every component once.
REM ===========================================================================
if "%PY%"==".python\python.exe" (echo   [6/6] Checking the installation...) else (echo   [5/5] Checking the installation...)
%PY% -c "import fastapi,uvicorn,sqlalchemy,pymupdf,openpyxl,pandas,shapely,networkx,rapidfuzz,ortools;print('         all components load')"
if errorlevel 1 (
  echo.
  echo   [X] A component failed to load. Do not use this installation.
  echo       If the message above says "DLL load failed", the computer lacks
  echo       the Microsoft Visual C++ Redistributable 2015-2022 ^(x64^) -
  echo       vc_redist.x64.exe from microsoft.com - or a security policy
  echo       blocks programs in this folder.
  goto :fail
)
%PY% -s tools\check_env.py | findstr /b "RESULT MISSING"
if not exist "data" mkdir data

echo.
echo   ===========================================================
echo    Installed - version %VER%. Nothing was changed outside
echo    this folder.
echo.
echo    Start the application:  double-click  start.bat
echo    Then open               http://127.0.0.1:8000
echo.
echo    The first person to open it creates the administrator
echo    account. There is no default password.
echo.
echo    Full instructions:      docs\INSTALL.html
echo   ===========================================================
echo.
if not defined NER_NOPAUSE pause
exit /b 0

:fail
echo.
if not defined NER_NOPAUSE pause
exit /b 1
