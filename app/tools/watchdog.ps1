# Bring the analyzer back if it is not answering -- and record why it went.
#
# Why this exists
# ---------------
# On 2 Sep 2026 the server disappeared mid-session. data\server.log ends on a
# served request: no traceback, no "===== stopped =====" line, no Windows crash
# report, no antivirus event. That is the signature of a process killed from
# outside, and it is the *same* signature as 28 Aug 2026, when the Windows
# memory manager killed it at 97% commit charge during a solver run. A process
# killed for memory never gets to write anything.
#
# Two jobs, in this order:
#   1. record the machine's state at the moment the server is found down --
#      memory, the biggest processes, and (since 2.6.1) the standby / power
#      events of the previous half hour, because on 22 Sep 2026 three of the
#      eight deaths on record followed the laptop leaving Modern Standby;
#   2. start it again.
#
# It never restarts a server that is answering, and -- the 2.6.1 lesson -- it
# never kills one that is merely *starting* or *slow*. On 22 Sep 2026 the
# laptop was at 75% CPU with 1 GB free; the server took over a minute to import
# its libraries, the next watchdog run found the port not answering yet, killed
# it mid-import and started another, whose bind then failed with error 10048.
# Four restarts in three minutes, "restart FAILED" three times, and from the
# chair: "the app is slow and opening a project does not work". So now:
#
#   * one run at a time (a lock file; the .vbs wrapper also waits, so the task
#     scheduler's IgnoreNew policy applies at last);
#   * "not answering" is split into *refused* (nothing listening: dead, restart
#     at once) and *slow* (listening, but no answer inside the timeout: leave
#     it alone -- restart only after three consecutive slow runs, six minutes);
#   * a server whose process is younger than three minutes is starting, not
#     dead, whatever the probe says;
#   * after a restart the health check is polled for up to 150 seconds instead
#     of asked once after 45.
$ErrorActionPreference = 'SilentlyContinue'
$root  = Split-Path -Parent $PSScriptRoot
$data  = Join-Path $root 'data'
$log   = Join-Path $data 'watchdog.log'
$lock  = Join-Path $data 'watchdog.lock'
$state = Join-Path $data 'watchdog-slow.txt'
$url   = 'http://127.0.0.1:8000/api/auth/state'
$port  = 8000

function Note([string]$m) {
  "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m | Add-Content -Path $log
}

# --- one run at a time --------------------------------------------------------
# A run can last three minutes when the server has to be restarted; the task
# fires every two. A second run probing while the first is still waiting for
# the new server to come up is exactly what killed it on 22 Sep 2026.
if (Test-Path $lock) {
  $age = (Get-Date) - (Get-Item $lock).LastWriteTime
  if ($age.TotalMinutes -lt 5) { exit 0 }      # a live run holds it
  Remove-Item $lock -Force                      # a stale one from a crash
}
"{0}  pid {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $PID | Set-Content -Path $lock
try {

# --- the server's process, if any ---------------------------------------------
# Only this folder's server: the same match server-stop.ps1 uses.
function ServerProcess {
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object {
      $_.CommandLine -like "*$root*" -and
      ($_.CommandLine -like '*serve.py*' -or $_.CommandLine -like '*uvicorn*app.main:app*' -or $_.CommandLine -like '*run.py*')
    } | Select-Object -First 1
}
function Listening {
  $c = New-Object Net.Sockets.TcpClient
  try { $c.Connect('127.0.0.1', $port); $true } catch { $false } finally { $c.Close() }
}

# --- probe ------------------------------------------------------------------------
# Two attempts before declaring it down: a single timeout during a heavy report
# render is not a dead server, and restarting one mid-export would lose the run.
$alive = $false
foreach ($try in 1..2) {
  try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 20
    if ($r.StatusCode -eq 200) { $alive = $true; break }
  } catch { }
  if ($try -eq 1) { Start-Sleep -Seconds 15 }
}

# A heartbeat, overwritten each run (one line, it never grows). Without it the
# only proof the watchdog is alive is a failure, and a watchdog that quietly
# stopped running looks exactly like one that has had nothing to do.
"{0}  last check: {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $(if ($alive) { 'server answering' } else { 'server DOWN' }) |
  Set-Content -Path (Join-Path $data 'watchdog-heartbeat.txt')

if ($alive) {
  if (Test-Path $state) { Remove-Item $state -Force }
  exit 0
}

# --- not answering: which kind? ------------------------------------------------
$proc = ServerProcess
if ($proc) {
  $age = (Get-Date) - $proc.CreationDate
  if ($age.TotalMinutes -lt 3) {
    Note ("server process {0} is {1:N0} s old -- still starting, left alone" -f $proc.ProcessId, $age.TotalSeconds)
    exit 0
  }
  if (Listening) {
    # Listening but not answering inside 20 s, twice. A machine at 75% CPU with
    # a gigabyte free does this to a healthy server; a hung one does it too.
    # Three runs in a row (six minutes) is the line between them.
    $n = 1
    if (Test-Path $state) { $n = [int](Get-Content $state) + 1 }
    Set-Content -Path $state -Value $n
    if ($n -lt 3) {
      Note ("server process {0} is listening but slow ({1} of 3) -- left alone" -f $proc.ProcessId, $n)
      exit 0
    }
    Note ("server process {0} listening but not answering for three runs -- restarting" -f $proc.ProcessId)
  } else {
    Note ("server process {0} alive but nothing listening on {1} -- restarting" -f $proc.ProcessId, $port)
  }
} else {
  Note "not answering, no server process -- restarting"
}
if (Test-Path $state) { Remove-Item $state -Force }

# --- the evidence, before anything is restarted -------------------------------
$os = Get-CimInstance Win32_OperatingSystem
Note ("  memory: physical free {0} MB of {1} MB | commit used {2}% ({3} MB free of {4} MB)" -f `
  [int]($os.FreePhysicalMemory/1kb), [int]($os.TotalVisibleMemorySize/1kb),
  [math]::Round(100*(1-($os.FreeVirtualMemory/$os.TotalVirtualMemorySize)),1),
  [int]($os.FreeVirtualMemory/1kb), [int]($os.TotalVirtualMemorySize/1kb))

Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 5 |
  ForEach-Object { Note ("  top mem: {0,-24} {1} MB" -f $_.ProcessName, [int]($_.WorkingSet64/1mb)) }

# Standby and power events of the last half hour: 506 enter / 507 exit Modern
# Standby, 42 sleep, 107 resume, 105 power source change.
$power = Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power';
                                         Id=506,507,42,107,105; StartTime=(Get-Date).AddMinutes(-30)} |
  Sort-Object TimeCreated | ForEach-Object {
    $k = switch ($_.Id) { 506 {'enter standby'} 507 {'exit standby'} 42 {'sleep'} 107 {'resume'} 105 {'power source change'} }
    "{0:HH:mm:ss} {1}" -f $_.TimeCreated, $k }
Note ("  power events, last 30 min: {0}" -f $(if ($power) { $power -join ', ' } else { 'none' }))

$tail = Get-Content (Join-Path $data 'server.log') -Tail 1
Note ("  server.log ended on: {0}" -f $tail)
if ($tail -notmatch 'stopped =====') {
  Note "  no shutdown line -- it was killed, it did not exit"
}

# --- and now bring it back ----------------------------------------------------
# The interpreter is the private runtime install.bat built: .python\ (the
# bundled Python of an installation package) or .venv\ (a development checkout).
$pyw = Join-Path $root '.python\pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = Join-Path $root '.venv\Scripts\pythonw.exe' }
if (-not (Test-Path $pyw)) { Note "  no runtime found (.python or .venv) -- run install.bat"; exit 1 }
& (Join-Path $PSScriptRoot 'server-stop.ps1') | Out-Null
Start-Sleep -Seconds 2
Start-Process -FilePath $pyw `
              -ArgumentList (Join-Path $PSScriptRoot 'serve.py') `
              -WorkingDirectory $root -WindowStyle Hidden

# Poll rather than wait a fixed 45 s: on a loaded machine the imports alone
# take longer than that, and "restart FAILED" on a server that came up ten
# seconds later is a false alarm that invites the next run to kill it.
$deadline = (Get-Date).AddSeconds(150)
$up = $false
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 10
  try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 20
    if ($r.StatusCode -eq 200) { $up = $true; break }
  } catch { }
}
if ($up) { Note ("  restarted, health 200") }
else     { Note "  restart FAILED after 150 s -- see data\server.log" }

} finally {
  Remove-Item $lock -Force
}
