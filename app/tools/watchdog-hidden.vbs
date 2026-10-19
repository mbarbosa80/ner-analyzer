' Launch watchdog.ps1 with no window at all.
'
' Why this wrapper exists: powershell.exe -WindowStyle Hidden does NOT prevent
' the console window. Windows creates the console first and the switch only
' hides it afterwards, so the Task Scheduler firing it every two minutes made a
' black box flash on screen every two minutes. WScript.Shell .Run with intWindow
' style 0 never creates one.
'
' bWaitOnReturn is True (2.6.1). With False this script returned at once, so
' the scheduled task was "finished" the moment it fired and its IgnoreNew
' policy -- do not start a new instance while one runs -- had nothing to
' apply to: every two minutes a fresh watchdog.ps1 started whether or not the
' previous one was still restarting the server. On 22 Sep 2026 that second
' run killed a server the first had just started. Waiting keeps the task
' instance alive for as long as the script runs, which is what the policy
' needs. watchdog.ps1 holds a lock file as well, in case the task is ever
' registered without the policy.
Dim sh, here
Set sh = CreateObject("WScript.Shell")
here = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.Run "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & here & "\watchdog.ps1""", 0, True
