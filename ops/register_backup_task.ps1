<#
.SYNOPSIS
    Register "Faro\DailyBackup": a daily local backup of the Faro database.

.DESCRIPTION
    Daily at -At (default 21:00), runs ops/backup_db.ps1 with no arguments
    through ops/run_hidden.vbs. The backup folder and the pg_dump path come
    from the root .env, so the task's command line carries no path or secret:
        FARO_BACKUP_DIR=C:\Respaldos\Faro
        PG_DUMP_PATH=C:\Program Files\PostgreSQL\18\bin\pg_dump.exe
    Then applies ops/harden_scheduled_tasks.ps1, so a run missed while the
    machine was off, asleep or on battery happens as soon as possible.

.NOTES
    Run it yourself from a normal PowerShell prompt; /F makes it idempotent.
    Check the result of the last run with:
        schtasks /Query /TN "Faro\DailyBackup" /V /FO LIST
#>
param(
    [string]$At = '21:00'
)

$ErrorActionPreference = 'Stop'

$RepoRoot  = Split-Path -Parent $PSScriptRoot
$HiddenVbs = Join-Path $RepoRoot 'ops\run_hidden.vbs'
$Script    = Join-Path $RepoRoot 'ops\backup_db.ps1'

schtasks /Create `
    /TN "Faro\DailyBackup" `
    /SC DAILY `
    /ST $At `
    /RL LIMITED `
    /F `
    /TR "wscript.exe `"$HiddenVbs`" `"$Script`""

if ($LASTEXITCODE -ne 0) {
    Write-Host "schtasks failed (exit $LASTEXITCODE) - the task was NOT registered." -ForegroundColor Red
    exit 1
}

& (Join-Path $PSScriptRoot 'harden_scheduled_tasks.ps1') -TaskName 'DailyBackup'

Write-Host ""
Write-Host "Registered Faro\DailyBackup at $At. Make sure FARO_BACKUP_DIR (and PG_DUMP_PATH"
Write-Host "if pg_dump is not on the PATH) are set in the root .env."
Write-Host "  Run now    : schtasks /Run /TN `"Faro\DailyBackup`""
Write-Host "  Unregister : schtasks /Delete /TN `"Faro\DailyBackup`" /F"
