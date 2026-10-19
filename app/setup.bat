@echo off
REM ===========================================================================
REM  NER Spatial Coverage Analyzer - one-step setup (Windows)
REM
REM  Run this file after unzipping the package (right-click > Run as
REM  administrator; a plain double-click asks Windows for the rights itself).
REM  It does in one go what install.bat, autostart.bat and start.bat do one
REM  after the other, and then removes the installation files - the unzipped
REM  package and the zip it came from - leaving only the application, running,
REM  in its own folder:
REM
REM      %LOCALAPPDATA%\Programs\ner-analyzer
REM      (that is C:\Users\<you>\AppData\Local\Programs\ner-analyzer)
REM
REM    setup.bat                        install there
REM    setup.bat D:\Apps\ner-analyzer   install in another folder
REM    setup.bat --no-services          install and clean up, but register no
REM                                     scheduled task and start nothing
REM    setup.bat --keep-installer       do not delete the package and the zip
REM    setup.bat --no-admin             install for this account only, without
REM                                     asking for administrator rights (a managed
REM                                     computer where they cannot be granted);
REM                                     setup-noadmin.bat does the same by double-click
REM
REM  What it does, in order:
REM    0. checks it runs with administrator rights, and as the person signed
REM       in: an administrator account typed into the prompt would install
REM       into ITS profile, where the person at the keyboard cannot use it.
REM       Nothing below actually needs the rights - the folder, the tasks and
REM       the data are all per user - so when they are refused, or with
REM       --no-admin, the installation goes on for this account only;
REM    1. a previous installation in the target is backed up and REPLACED:
REM       its database is copied (backup.bat, into data\backup-...), the server
REM       is stopped, the old installation is moved aside to
REM       <target>.previous, and its data\ is moved back into the new one;
REM    2. copies the package into the target folder;
REM    3. install.bat there - the bundled Python into .python\, the packages
REM       from vendor\wheels, and the check that every component loads;
REM    4. autostart.bat there - the sign-in task and the watchdog, both set to
REM       survive a laptop on battery - and starts the server through that
REM       task, so it belongs to no window and to no session;
REM    5. waits for http://127.0.0.1:8000/healthz, puts an "NER Analyzer"
REM       shortcut on the desktop and opens the browser;
REM    6. removes vendor\ from the target (about 100 MB of installation payload
REM       the running application never reads), then, once this window has
REM       closed, every file of the unzipped package and the zip itself.
REM
REM  If anything fails after the old installation was moved aside, it is put
REM  back where it was. The data is never deleted: it moves with the
REM  installation, and the backup sits inside it.
REM
REM  No internet and no Python on the machine are needed.
REM  Set NER_NOPAUSE=1 to run it without the final "press any key".
REM
REM  (c) 2026 Marcelo Barbosa. Free software, GNU AGPL-3.0 - see LICENSE.txt and NOTICE.txt.
REM ===========================================================================
setlocal
set "SRC=%~dp0"
set "SRC=%SRC:~0,-1%"
cd /d "%SRC%"
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
set "USER_NOPAUSE=%NER_NOPAUSE%"
set "URL=http://127.0.0.1:8000"
set "TASKNAME=NER Spatial Coverage Analyzer"
set "WATCHDOG=NER Analyzer watchdog"

set VER=unknown
if exist VERSION set /p VER=<VERSION

echo.
echo   NER Spatial Coverage Analyzer %VER% - setup
echo   ============================================
echo.

REM --- Arguments -------------------------------------------------------------
set "ARGS=%*"
set "TARGET="
set "SERVICES=1"
set "KEEP="
set "NOADMIN="
:args
if "%~1"=="" goto :args_done
if /i "%~1"=="--no-services" (set "SERVICES=" & shift & goto :args)
if /i "%~1"=="--keep-installer" (set "KEEP=1" & shift & goto :args)
if /i "%~1"=="--no-admin" (set "NOADMIN=1" & shift & goto :args)
if /i "%~1"=="--help" goto :usage
if /i "%~1"=="-h" goto :usage
if /i "%~1"=="/?" goto :usage
set "TARGET=%~1"
shift
goto :args
:args_done
if not defined TARGET set "TARGET=%LOCALAPPDATA%\Programs\ner-analyzer"
if "%TARGET:~-1%"=="\" set "TARGET=%TARGET:~0,-1%"
set "PREV=%TARGET%.previous"

REM --- This must be a built package, not a development checkout -------------
if not exist "MANIFEST.txt" (
  echo   [X] MANIFEST.txt is missing: this folder is not an installation package.
  echo       setup.bat runs from the unzipped ner-analyzer-^<version^>-windows.zip.
  echo       To install a development checkout in place, use install.bat.
  goto :fail
)
set "EMBED="
for %%F in ("vendor\python\python-3.12.*-embed-amd64.zip") do set "EMBED=%%~F"
if not defined EMBED (
  echo   [X] vendor\python has no Python runtime zip. This package is incomplete
  echo       ^(or was built with --without-python^). Use install.bat instead.
  goto :fail
)
for %%F in (install.bat autostart.bat start.bat stop.bat backup.bat VERSION) do (
  if not exist "%%F" (
    echo   [X] %%F is missing. This package is incomplete: check the zip against
    echo       its .sha256 and unzip it again.
    goto :fail
  )
)

REM --- Administrator rights --------------------------------------------------
REM fltmc answers only in an elevated window. Without the rights, ask Windows
REM for them: the same script starts again in an elevated window, and this one
REM ends. NER_SKIP_ADMIN=1 skips the check (automated tests only); --no-admin
REM skips the request and installs for this account only - the same result as
REM answering "yes" when the rights are refused. Nothing in the installation
REM needs them: the folder is the person's own, the scheduled tasks are
REM per-user (one for this account's sign-in, one every two minutes), the server listens on
REM 127.0.0.1 only. The rights were asked for because, on some machines, a
REM double-click without them was refused by policy before the script ran;
REM where they cannot be granted at all (a managed laptop), this is the way.
if defined NER_SKIP_ADMIN goto :admin_ok
if defined NOADMIN goto :noadmin
fltmc >nul 2>nul
if not errorlevel 1 goto :admin_ok
echo   Administrator rights are needed. Windows will ask for them now...
set "NER_SELF=%~f0"
set "NER_ARGS=%ARGS%"
"%PS%" -NoProfile -ExecutionPolicy Bypass -Command "$a = @{ FilePath = $env:NER_SELF; Verb = 'RunAs' }; if ($env:NER_ARGS) { $a.ArgumentList = $env:NER_ARGS }; try { Start-Process @a -ErrorAction Stop; exit 0 } catch { exit 1 }"
if errorlevel 1 goto :no_rights
echo   The setup continues in the new window. This one can be closed.
exit /b 0
:no_rights
echo.
echo   [X] The administrator rights were not granted.
if defined USER_NOPAUSE goto :fail_noadmin
echo       On a computer where they cannot be granted ^(a managed laptop^), the
echo       application can still be installed for this account only, in your own
echo       profile: no file outside it, no service, nothing for other accounts.
echo.
choice /c YN /n /m "       Install without administrator rights, for this account only? [Y/N] "
if errorlevel 2 goto :fail_noadmin
goto :noadmin
:fail_noadmin
echo       Nothing was installed. Right-click setup.bat and choose "Run as
echo       administrator", or double-click setup-noadmin.bat to install for this
echo       account only.
goto :fail
:noadmin
echo   Installing without administrator rights, for this account only.
echo   Everything - the application, its scheduled tasks, its data - lives in
echo   your own profile ^(%LOCALAPPDATA%^); nothing is written outside it.
echo.
:admin_ok

REM --- ...and as the person signed in -----------------------------------------
REM When the account at the keyboard is not an administrator, Windows asks for
REM an administrator's name and password, and the window then runs as THAT
REM account: the application would land in its profile and its sign-in task
REM would run for it. Refuse, and say why. (Remote Desktop leaves the console
REM user empty; then there is nothing to compare.)
set "WHO=%TEMP%\ner-setup-who-%RANDOM%.txt"
"%PS%" -NoProfile -ExecutionPolicy Bypass -Command "try { $c = (Get-CimInstance Win32_ComputerSystem).UserName } catch { $c = $null }; $w = [Security.Principal.WindowsIdentity]::GetCurrent().Name; if ($c -and ($c -ne $w)) { Set-Content -LiteralPath $env:WHO -Value ($c + ' ' + $w) -Encoding ASCII }" >nul 2>nul
set "WHOLINE="
if exist "%WHO%" set /p WHOLINE=<"%WHO%"
if exist "%WHO%" del /f /q "%WHO%" >nul 2>nul
if not defined WHOLINE goto :who_ok
echo   [X] This window runs as another account than the person signed in.
echo       Signed in, then this window: %WHOLINE%
echo       The application installs for one person, in that person's profile.
echo       Sign in as the person who will use it, with administrator rights
echo       ^(ask IT to grant them for the installation^), and run it again.
goto :fail
:who_ok

REM --- The target must be another folder, outside this one and not above it --
if /i "%TARGET%"=="%SRC%" (
  echo   [X] The target is this very folder. setup.bat installs INTO a folder of
  echo       its own and then deletes the unzipped package; to install in place,
  echo       use install.bat.
  goto :fail
)
call set "PROBE=%%TARGET:%SRC%\=%%"
if /i not "%PROBE%"=="%TARGET%" (
  echo   [X] The target is inside the unzipped package, which is deleted at the
  echo       end. Choose a folder outside it.
  goto :fail
)
call set "PROBE=%%SRC:%TARGET%\=%%"
if /i not "%PROBE%"=="%SRC%" (
  echo   [X] The unzipped package is inside the target folder. Unzip it
  echo       somewhere else ^(the Downloads folder is fine^) and run again.
  goto :fail
)
echo %TARGET% | findstr /i "OneDrive Dropbox" >nul
if not errorlevel 1 (
  echo   [*] The target is inside OneDrive or Dropbox. They sync files under a
  echo       running program, and the database needs file locks they do not
  echo       provide. The default target is never synced.
  echo.
)

REM --- New installation, or one already there to replace? --------------------
set "MODE=install"
if exist "%TARGET%\.python\python.exe" set "MODE=update"
if exist "%TARGET%\.venv\Scripts\python.exe" set "MODE=update"
if exist "%TARGET%\data\ner.sqlite3" set "MODE=update"

echo   Package:  %SRC%
echo   Target:   %TARGET%   ^(%MODE%^)
if defined SERVICES (echo   Services: sign-in task + watchdog, server started now) else (echo   Services: none - --no-services)
echo.

set "HAD_TASK="
set "HAD_WD="
set "MOVED="
if "%MODE%"=="update" goto :update
echo   [1/6] New installation.
goto :copy

:update
set "OLDVER=unknown"
if exist "%TARGET%\VERSION" set /p OLDVER=<"%TARGET%\VERSION"
echo   [1/6] Replacing version %OLDVER% - its data is kept.
REM The scheduled tasks would start the OLD runtime while it is being replaced;
REM hold them until the new one is in place (autostart.bat re-creates them).
schtasks /query /tn "%TASKNAME%" >nul 2>nul && set "HAD_TASK=1"
schtasks /query /tn "%WATCHDOG%" >nul 2>nul && set "HAD_WD=1"
if defined HAD_WD schtasks /change /tn "%WATCHDOG%" /disable >nul 2>nul
if defined HAD_TASK schtasks /change /tn "%TASKNAME%" /disable >nul 2>nul
if not exist "%TARGET%\data\ner.sqlite3" goto :update_stop
echo         Backup of the database first ^(backup.bat^)...
call :in_target backup.bat
if errorlevel 1 (
  echo   [X] The backup failed; nothing was changed. See the message above.
  goto :fail_reenable
)
:update_stop
echo         Stopping the server ^(stop.bat^)...
call :in_target stop.bat
ping -n 3 127.0.0.1 >nul

REM The old installation is moved aside whole - never deleted - so that no
REM file of the old version survives into the new one, and so that it can be
REM put back if the new one fails to install. Only the copy kept by the update
REM before this one is removed.
if not exist "%PREV%" goto :move_old
echo         Removing the copy kept by the previous update ^(%PREV%^)...
rmdir /s /q "%PREV%" >nul 2>nul
if exist "%PREV%" (
  echo   [X] %PREV% could not be removed: a file in it is open in another
  echo       program. Close it, or delete that folder by hand, and run again.
  echo       Nothing was changed.
  goto :fail_reenable
)
:move_old
echo         Moving the old installation aside to %PREV%...
set /a MOVES=0
:move_again
move "%TARGET%" "%PREV%" >nul 2>nul
if not exist "%TARGET%" goto :moved
set /a MOVES+=1
if %MOVES% geq 10 goto :move_failed
ping -n 4 127.0.0.1 >nul
goto :move_again
:move_failed
echo   [X] The old installation could not be moved: something still has a file
echo       or the folder itself open - the server, an Explorer window, an editor.
echo       Close it and run setup again. Nothing was changed.
goto :fail_reenable
:moved
set "MOVED=1"
mkdir "%TARGET%" >nul 2>nul
if not exist "%PREV%\data" goto :copy
move "%PREV%\data" "%TARGET%\data" >nul 2>nul
if exist "%TARGET%\data" goto :copy
echo   [X] The data folder could not be moved into the new installation.
goto :rollback

REM --- Copy the package into the target ---------------------------------------
:copy
echo   [2/6] Copying the package into the target folder...
if not exist "%TARGET%" mkdir "%TARGET%"
if not exist "%TARGET%" (
  echo   [X] Could not create %TARGET%
  goto :rollback
)
robocopy "%SRC%" "%TARGET%" /E /NFL /NDL /NJH /NJS /NP /R:2 /W:2 /XF setup.bat setup-noadmin.bat /XD data .python .venv node_modules >nul
if errorlevel 8 (
  echo   [X] The copy failed. Is the disk full, or a file in the target folder
  echo       open in another program? Nothing in the package was deleted.
  goto :rollback
)
if not exist "%TARGET%\data" mkdir "%TARGET%\data"
REM Files unzipped from a download carry the "came from the internet" mark,
REM which makes Windows ask before running each script. The installed copy is
REM ours: drop the mark there.
"%PS%" -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath $env:TARGET -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue" >nul 2>nul

REM --- install.bat in the target ----------------------------------------------
echo   [3/6] Installing ^(install.bat in the target^)...
echo.
call :in_target install.bat
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
  echo   [X] install.bat failed ^(see above^). The unzipped package was NOT deleted,
  echo       so it can be run again after the cause is fixed: docs\INSTALL.html,
  echo       "Common problems".
  goto :rollback
)
if not exist "%TARGET%\.python\.deps-installed" (
  echo   [X] install.bat ended without completing the runtime. Nothing was deleted.
  goto :rollback
)

REM --- Services, and the server -----------------------------------------------
if defined SERVICES goto :services
echo   [4/6] No scheduled task and no server: --no-services.
echo         Start it by hand with start.bat in the target folder.
if defined HAD_WD schtasks /change /tn "%WATCHDOG%" /enable >nul 2>nul
if defined HAD_TASK schtasks /change /tn "%TASKNAME%" /enable >nul 2>nul
goto :cleanup

:services
echo   [4/6] Registering the sign-in task and the watchdog ^(autostart.bat^)...
call :in_target autostart.bat
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo   [*] autostart.bat reported a problem ^(above^). The application is
  echo       installed; start it with start.bat and run autostart.bat again later.
  if defined HAD_WD schtasks /change /tn "%WATCHDOG%" /enable >nul 2>nul
  if defined HAD_TASK schtasks /change /tn "%TASKNAME%" /enable >nul 2>nul
  goto :cleanup
)
echo   [5/6] Starting the server through the scheduled task...
call :in_target tools\server-start.cmd
set /a TRIES=0
:wait
set /a TRIES+=1
"%PS%" -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing '%URL%/healthz' -TimeoutSec 5; if ($r.StatusCode -ne 200) { exit 1 } } catch { exit 1 }" >nul 2>nul
if not errorlevel 1 goto :up
if %TRIES% geq 45 goto :notup
ping -n 3 127.0.0.1 >nul
goto :wait
:notup
echo   [*] The server did not answer within 90 s. It may still be starting
echo       ^(a cold start takes 20-40 s; the watchdog retries every 2 minutes^).
echo       Log: %TARGET%\data\server.log
goto :shortcut
:up
set /a SECS=TRIES*2
echo         Answering at %URL% after about %SECS% s.
REM Through explorer.exe, so the browser opens as the person signed in and
REM not with this window's administrator rights.
start "" explorer.exe "%URL%/"
:shortcut
REM A desktop shortcut that opens the application in the default browser.
"%PS%" -NoProfile -ExecutionPolicy Bypass -Command "$d = [Environment]::GetFolderPath('Desktop'); if ($d) { Set-Content -LiteralPath (Join-Path $d 'NER Analyzer.url') -Value @('[InternetShortcut]', ('URL=' + $env:URL + '/')) -Encoding ASCII }" >nul 2>nul
echo         Desktop shortcut: NER Analyzer

REM --- Clean up: vendor\ in the target, then the package and the zip ----------
:cleanup
echo   [6/6] Removing the installation files...
if exist "%TARGET%\vendor" (
  rmdir /s /q "%TARGET%\vendor" >nul 2>nul
  echo         vendor\ removed from the target ^(the runtime is built; it is not needed^).
)
set "CLEAN="
if defined KEEP (
  echo         --keep-installer: the unzipped package and the zip are kept.
  goto :done
)
REM The unzipped package is deleted file by file from MANIFEST.txt - whose
REM paths are written with forward slashes, which "del" refuses, so :kill
REM turns each one back into backslashes - and never with a
REM blind "rmdir /s" of a folder somebody may have unzipped into Downloads
REM itself. Folders are removed only once empty. It runs after this window
REM closes, from a script in %TEMP%, because a folder cannot be removed while
REM a program still has it as its working directory - and it retries the
REM removal for about 45 s, because "this window" is not the only thing that
REM may be standing in that folder: setup.bat called from another script
REM gives the caller its directory back on exit, and an open Explorer window
REM holds it too. The files go on the first pass either way; it is the empty
REM folder that has to wait.
set "CLEAN=%TEMP%\ner-setup-cleanup-%RANDOM%%RANDOM%.cmd"
> "%CLEAN%" (
  echo @echo off
  echo goto :main
  echo :kill
  echo set "F=%%~1"
  echo set "F=%%F:/=\%%"
  echo if exist "%SRC%\%%F%%" del /f /q "%SRC%\%%F%%" ^>nul 2^>nul
  echo exit /b 0
  echo :main
  echo ping -n 4 127.0.0.1 ^>nul
  echo cd /d "%%TEMP%%"
  echo for /f "usebackq tokens=1,* delims= " %%%%A in ("%SRC%\MANIFEST.txt"^) do call :kill "%%%%B"
  echo if exist "%SRC%\vendor" rmdir /s /q "%SRC%\vendor" ^>nul 2^>nul
  echo for %%%%F in ^(PACKAGE.txt MANIFEST.txt setup.bat data\.keep^) do if exist "%SRC%\%%%%F" del /f /q "%SRC%\%%%%F" ^>nul 2^>nul
  echo set N=0
  echo :retry
  echo for /f "delims=" %%%%D in ^('dir /ad /b /s "%SRC%" 2^^^>nul ^^^| sort /r'^) do rd "%%%%D" ^>nul 2^>nul
  echo rd "%SRC%" ^>nul 2^>nul
  echo if not exist "%SRC%" goto :gone
  echo set /a N+=1
  echo if %%N%% lss 10 ping -n 5 127.0.0.1 ^>nul ^&^& goto :retry
  echo :gone
  echo rd "%SRC%\.." ^>nul 2^>nul
  echo for %%%%D in ^("%SRC%" "%SRC%\.." "%SRC%\..\.." "%%USERPROFILE%%\Downloads"^) do ^(
  echo   if exist "%%%%~D\ner-analyzer-%VER%*windows*.zip" del /f /q "%%%%~D\ner-analyzer-%VER%*windows*.zip" ^>nul 2^>nul
  echo   if exist "%%%%~D\ner-analyzer-%VER%*windows*.zip.sha256" del /f /q "%%%%~D\ner-analyzer-%VER%*windows*.zip.sha256" ^>nul 2^>nul
  echo ^)
  echo rd "%SRC%\.." ^>nul 2^>nul
  echo del /f /q "%%~f0"
)
echo         The unzipped package and ner-analyzer-%VER%-windows.zip are deleted
echo         as soon as this window closes.

:done
REM One line per redirection: a "(1)" in a path - Windows numbers duplicate
REM downloads that way - would end a parenthesised block early.
set "LOG=%TARGET%\data\setup.log"
>  "%LOG%" echo NER Spatial Coverage Analyzer %VER% - setup %DATE% %TIME%
>> "%LOG%" echo mode      %MODE%
>> "%LOG%" echo package   "%SRC%"
>> "%LOG%" echo target    "%TARGET%"
if defined MOVED (>> "%LOG%" echo previous  version %OLDVER% moved to "%PREV%"; database backup under data\)
if defined SERVICES (>> "%LOG%" echo services  sign-in task + watchdog) else (>> "%LOG%" echo services  none - --no-services)
if defined CLEAN (>> "%LOG%" echo removed   vendor\ in the target; the unzipped package and the zip once setup closed) else (>> "%LOG%" echo removed   vendor\ in the target)
echo.
echo   ===========================================================
echo    Installed - version %VER%
echo.
echo    Folder:   %TARGET%
if defined SERVICES (
  echo    Open:     %URL%   ^(or the "NER Analyzer" desktop shortcut^)
  echo              The server runs with no window, starts by itself at
  echo              sign-in, and the watchdog restarts it if it ever stops.
) else (
  echo    Start:    start.bat in that folder, then open %URL%
)
echo.
if "%MODE%"=="update" goto :summary_update
echo    The first person to open it creates the administrator
echo    account. There is no default password.
goto :summary_end
:summary_update
echo    Replaced version %OLDVER%. The data is where it was, with a
echo    backup under data\. The old version is kept in:
echo      %PREV%
echo    Delete that folder once this version works. In the browser,
echo    press Ctrl+Shift+R once.
:summary_end
echo.
echo    Browsers: Chrome, Edge or Firefox.
echo    Manuals:  %TARGET%\docs\MANUAL.html  and  INSTALL.html
echo   ===========================================================
echo.
if not defined USER_NOPAUSE pause
cd /d "%TEMP%"
if defined CLEAN start "" /min cmd /c "%CLEAN%"
exit /b 0

REM --- Run one of the package's scripts inside the target folder -------------
:in_target
pushd "%TARGET%"
set "NER_NOPAUSE=1"
set "NER_FROM_SETUP=1"
call %1
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%

:usage
echo   setup.bat [target-folder] [--no-services] [--keep-installer] [--no-admin]
echo.
echo     target-folder     where to install ^(default %LOCALAPPDATA%\Programs\ner-analyzer^)
echo     --no-services     install only: no scheduled task, no watchdog, nothing started
echo     --keep-installer  keep the unzipped package and the zip after installing
echo     --no-admin        do not ask for administrator rights: install for this
echo                       account only ^(setup-noadmin.bat does the same^)
echo.
if not defined USER_NOPAUSE pause
exit /b 0

REM --- Something failed after the old installation was moved aside: put it
REM     back. The data folder goes back first; the half-built new folder is
REM     removed only once the data is out of it.
:rollback
if not defined MOVED goto :fail_reenable
echo.
echo   Putting the previous installation back...
if exist "%TARGET%\data" if not exist "%PREV%\data" move "%TARGET%\data" "%PREV%\data" >nul 2>nul
if not exist "%TARGET%\data" goto :rollback_data_out
echo   [X] The data folder could not be moved back. It is safe, with its backup, in
echo         %TARGET%\data
echo       and the old version is in
echo         %PREV%
echo       Nothing was deleted. Send this window to support.
goto :fail_reenable
:rollback_data_out
rmdir /s /q "%TARGET%" >nul 2>nul
move "%PREV%" "%TARGET%" >nul 2>nul
if not exist "%PREV%" goto :rollback_done
echo   [X] The old version could not be moved back. It is, with its data, in
echo         %PREV%
goto :fail_reenable
:rollback_done
echo         Version %OLDVER% is back in %TARGET%, with its data.
if defined HAD_TASK call :in_target tools\server-start.cmd
:fail_reenable
if defined HAD_WD schtasks /change /tn "%WATCHDOG%" /enable >nul 2>nul
if defined HAD_TASK schtasks /change /tn "%TASKNAME%" /enable >nul 2>nul
:fail
echo.
if not defined USER_NOPAUSE pause
exit /b 1
