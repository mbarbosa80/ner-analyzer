# Register (or re-register) the sign-in task for the person signed in.
#
# Why this exists
# ---------------
# Until 2.16.0 autostart.bat made this task with
#
#     schtasks /create /tn "..." /sc onlogon /rl limited /f /tr "..."
#
# A trigger written that way fires at the sign-in of ANY user of the computer,
# and Windows lets only an administrator create one: without elevated rights
# the answer is "ERROR: Access is denied." That went unnoticed while every
# installation was made from an elevated window. On 2 Oct 2026 the first
# installation made without the rights -- the whole point of setup-noadmin.bat --
# came out with no sign-in task, and, because autostart.bat stopped at that
# error, with no watchdog either.
#
# A trigger for ONE user -- the person signed in -- needs no rights at all, and
# it is also the correct trigger: the application lives in that person's
# profile and nobody else's sign-in should start it. schtasks.exe has no switch
# for a per-user trigger, so the task is written as XML and registered with
# schtasks.exe /Create /XML (Register-ScheduledTask answers "Access is denied"
# on a managed machine where schtasks.exe is allowed).
#
# The user is written as a SID, not a name: a name such as AzureAD\First Last
# does not always resolve on a machine joined to a cloud directory; a SID
# always does.
#
# The settings are the ones task-harden.ps1 would set afterwards (runs on
# battery, is not stopped on battery, no 72-hour limit), written here from the
# start so the task is never left for a moment with the scheduler's defaults.
param(
  [Parameter(Mandatory = $true)][string]$Name,
  [Parameter(Mandatory = $true)][string]$Pythonw,
  [Parameter(Mandatory = $true)][string]$Script
)

$ErrorActionPreference = 'Continue'

$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
function Esc([string]$s) { [Security.SecurityElement]::Escape($s) }

$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>NER Spatial Coverage Analyzer - starts the server at sign-in, with no window (log in data\server.log)</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>$sid</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$sid</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>"$(Esc $Pythonw)"</Command>
      <Arguments>"$(Esc $Script)"</Arguments>
    </Exec>
  </Actions>
</Task>
"@

$tmp = Join-Path $env:TEMP ("ner-task-{0}.xml" -f ([guid]::NewGuid().ToString('N')))
[IO.File]::WriteAllText($tmp, $xml, [Text.Encoding]::Unicode)
schtasks.exe /Create /TN $Name /XML $tmp /F *>&1 | Write-Output
$code = $LASTEXITCODE
Remove-Item $tmp -Force -ErrorAction SilentlyContinue
if ($code -ne 0) {
  Write-Output "FAILED: schtasks exit $code"
  exit $code
}

schtasks.exe /Query /TN $Name /FO LIST 2>$null | Select-String 'TaskName|Status'
exit 0
