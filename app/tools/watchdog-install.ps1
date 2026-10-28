# Register (or re-register) the watchdog as a scheduled task for this user.
#
# Register-ScheduledTask answers "Access is denied" on this managed machine, so
# this uses schtasks.exe, which the same user is allowed to run. No admin needed.
# ErrorActionPreference stays 'Continue': schtasks writes ordinary notices to
# stderr, and 'Stop' would turn those into failures.
#
# The task runs wscript.exe, not powershell.exe. `powershell -WindowStyle Hidden`
# still flashes a console window every time it fires -- Windows creates the
# console and the switch only hides it afterwards -- and a black box blinking on
# screen every two minutes is not something to inflict on the person working.
# The .vbs wrapper starts it with window style 0 and no console is ever made.
$ErrorActionPreference = 'Continue'
$name = 'NER Analyzer watchdog'
$vbs  = Join-Path $PSScriptRoot 'watchdog-hidden.vbs'
$cmd  = 'wscript.exe //B //Nologo "{0}"' -f $vbs

schtasks.exe /Delete /TN $name /F *>$null

# /SC MINUTE /MO 2 -> every two minutes, indefinitely, starting now.
schtasks.exe /Create /TN $name /TR $cmd /SC MINUTE /MO 2 /F *>&1 | Write-Output
if ($LASTEXITCODE -ne 0) {
  Write-Output "FAILED: schtasks exit $LASTEXITCODE"
  exit $LASTEXITCODE
}

schtasks.exe /Query /TN $name /FO LIST 2>$null | Select-String 'TaskName|Status|Next Run Time'
