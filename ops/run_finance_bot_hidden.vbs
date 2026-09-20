' Truly hidden launcher for the Faro\FinanceBotSync scheduled task.
'
' powershell.exe's own -WindowStyle Hidden (ops/run_finance_bot.ps1's first
' fix attempt) still briefly flashes a console window before hiding it --
' a known conhost quirk on Windows 10/11. WScript.Shell.Run with window
' style 0 never creates a visible window at all: it hides at CreateProcess
' time via COM, not after the fact. See ops/register_finance_bot.ps1.
Dim fso, scriptDir, ps1Path, shell

Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
ps1Path = fso.BuildPath(scriptDir, "run_finance_bot.ps1")

Set shell = CreateObject("WScript.Shell")
shell.Run "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1Path & """", 0, False
