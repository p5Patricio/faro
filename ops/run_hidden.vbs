' Generic hidden launcher for Faro's Windows Task Scheduler actions.
'
' WScript.Shell.Run with window style 0 hides the target process from
' CreateProcess time onward -- unlike a raw `cmd /c ...` action (no
' window control at all) or `powershell -WindowStyle Hidden` (still
' briefly flashes a console before hiding it, a known conhost quirk on
' Windows 10/11, confirmed live against Faro\FinanceBotSync before this
' generic launcher existed), this never creates a visible window at all.
'
' Takes ONE argument: the path to a .ps1 script to run via
' `powershell -File`. Every ops/register_*.ps1 in this repo points its
' scheduled task's action at
'   wscript.exe "<repo>\ops\run_hidden.vbs" "<repo>\ops\<script>.ps1"
' instead of hand-building a `cmd /c` or `powershell -Command` line --
' passing a raw command string through schtasks.exe's own /TR parsing
' breaks once it contains a second level of nested quotes (e.g. a
' Set-Location path in single quotes inside a -Command double-quoted
' string), so each task gets its own small, self-contained .ps1 that
' needs no arguments, and this launcher only ever needs ONE quoted path.
Dim shell, ps1Path

ps1Path = WScript.Arguments(0)

Set shell = CreateObject("WScript.Shell")
shell.Run "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1Path & """", 0, False
