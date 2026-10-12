<#
.SYNOPSIS
    Make Faro's scheduled tasks catch up after a missed run and run on battery.

.DESCRIPTION
    `schtasks /Create` (used by every ops/register_*.ps1) cannot set these
    options, and its defaults silently drop runs on a laptop:
      - "Start only on AC power": a trigger that fires on battery is refused
        with 0x800710E0 ("the operator or administrator has refused the
        request") and is NOT retried later.
      - No "run as soon as possible after a missed start": a trigger that
        fires while the machine is off or asleep is skipped for the day
        (audit finding O-1).
    This script flips both on every task under the \Faro\ folder (or only
    -TaskName), keeping its triggers, actions and principal. Idempotent: run
    it as often as you like. Every register_*.ps1 calls it right after
    `schtasks /Create`, so re-registering a task keeps the settings.

.EXAMPLE
    .\ops\harden_scheduled_tasks.ps1                       # every \Faro\ task
    .\ops\harden_scheduled_tasks.ps1 -TaskName DailyBackup  # one task
#>
param(
    [string]$TaskPath = '\Faro\',
    [string]$TaskName = '*'
)

$ErrorActionPreference = 'Stop'

$tasks = @(Get-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue)
if ($tasks.Count -eq 0) {
    Write-Host "No scheduled task matches $TaskPath$TaskName - nothing to change."
    exit 0
}

$denied = @()
foreach ($task in $tasks) {
    $settings = $task.Settings
    $settings.StartWhenAvailable = $true
    $settings.DisallowStartIfOnBatteries = $false
    $settings.StopIfGoingOnBatteries = $false
    try {
        Set-ScheduledTask -TaskPath $task.TaskPath -TaskName $task.TaskName -Settings $settings -ErrorAction Stop | Out-Null
        Write-Host ("{0}{1}: run if missed = on, run on battery = on" -f $task.TaskPath, $task.TaskName)
    } catch [Microsoft.Management.Infrastructure.CimException] {
        # A task registered from an elevated prompt can only be changed from one.
        $denied += "$($task.TaskPath)$($task.TaskName)"
        Write-Host ("{0}{1}: access denied - run this script from an elevated PowerShell" -f $task.TaskPath, $task.TaskName) -ForegroundColor Yellow
    }
}
if ($denied.Count -gt 0) { exit 2 }
