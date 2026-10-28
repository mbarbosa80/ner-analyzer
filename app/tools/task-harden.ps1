# Make a scheduled task of this application survive a laptop's day.
#
# Why this exists
# ---------------
# schtasks.exe /create has no switch for a task's *conditions*, so every task it
# makes carries the Task Scheduler defaults:
#
#   DisallowStartIfOnBatteries = true    the task does not start on battery
#   StopIfGoingOnBatteries     = true    a RUNNING task is ended when the
#                                        charger is unplugged
#   ExecutionTimeLimit         = PT72H   a running task is ended after 3 days
#
# For the sign-in task that is a server killed from outside with nothing in
# data\server.log -- no traceback, no "===== stopped =====" line -- the moment
# the laptop leaves its dock, or on the fourth day of an uptime. For the
# watchdog it is a watchdog that silently stops watching on battery, which is
# exactly when it is needed. On 17 Sep 2026 the heartbeat file showed the
# watchdog had not fired for forty-five minutes while the server was down.
#
# What it does: exports the task's XML, changes those settings and nothing
# else, and registers the same task again from the XML. schtasks.exe is used
# both ways because Register-ScheduledTask / Set-ScheduledTask answer "Access is
# denied" on a managed machine where schtasks.exe is allowed. No admin needed.
#
# It never leaves the machine worse off: if anything here fails, the task that
# was there before is still there, and the script says so.
param([Parameter(Mandatory = $true)][string]$Name)

$ErrorActionPreference = 'Continue'

$raw = schtasks.exe /Query /TN $Name /XML 2>$null
if ($LASTEXITCODE -ne 0 -or -not $raw) {
  Write-Output "  [*] '$Name': task not found -- nothing to harden"
  exit 1
}

try {
  $xml = [xml](($raw | Out-String).Trim())
  $ns  = $xml.DocumentElement.NamespaceURI
  $settings = $xml.DocumentElement.Settings
  if (-not $settings) { throw "the task XML has no <Settings>" }

  $want = [ordered]@{
    DisallowStartIfOnBatteries = 'false'
    StopIfGoingOnBatteries     = 'false'
    ExecutionTimeLimit         = 'PT0S'        # no limit
    MultipleInstancesPolicy    = 'IgnoreNew'
    StartWhenAvailable         = 'true'
  }
  foreach ($key in $want.Keys) {
    $node = $settings.ChildNodes | Where-Object { $_.LocalName -eq $key } | Select-Object -First 1
    if (-not $node) {
      $node = $xml.CreateElement($key, $ns)
      [void]$settings.AppendChild($node)
    }
    $node.InnerText = $want[$key]
  }

  $tmp = Join-Path $env:TEMP ("ner-task-{0}.xml" -f ([guid]::NewGuid().ToString('N')))
  [IO.File]::WriteAllText($tmp, $xml.OuterXml, [Text.Encoding]::Unicode)
  schtasks.exe /Create /TN $Name /XML $tmp /F *>&1 | Out-Null
  $code = $LASTEXITCODE
  Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  if ($code -ne 0) { throw "schtasks /Create /XML answered $code" }
  Write-Output "  [ok] '$Name': runs on battery, is not stopped on battery, has no time limit"
  exit 0
} catch {
  Write-Output "  [*] '$Name': could not change the power settings ($($_.Exception.Message))."
  Write-Output "      The task is unchanged and still works on mains power. In Task Scheduler,"
  Write-Output "      open it and untick the two battery boxes under Conditions, and"
  Write-Output "      'Stop the task if it runs longer than' under Settings."
  exit 2
}
