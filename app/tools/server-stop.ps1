# Stop the analyzer -- and only the analyzer.
#
# This used to be `taskkill /IM pythonw.exe /F`, which kills EVERY windowless
# Python on the machine. There is normally more than one (a helper, another
# tool, an installer), so that command was a blunt instrument aimed at whatever
# happened to be running. It matches on the command line instead: the
# windowless server (tools\serve.py) and the console one (run.py -> uvicorn),
# and only when the command line names THIS folder.
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$found = 0
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
  Where-Object {
    $_.CommandLine -like "*$root*" -and
    ($_.CommandLine -like '*serve.py*' -or $_.CommandLine -like '*uvicorn*app.main:app*' -or $_.CommandLine -like '*run.py*')
  } |
  ForEach-Object {
    Write-Output ("stopping pid {0}" -f $_.ProcessId)
    Stop-Process -Id $_.ProcessId -Force
    $found++
  }
if ($found -eq 0) { Write-Output "not running." } else { Write-Output "Server stopped." }
