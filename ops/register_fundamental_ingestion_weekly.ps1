<#
.SYNOPSIS
    Register the Windows Task Scheduler task for the weekly SEC
    fundamental-facts ingestion.

.DESCRIPTION
    Creates:
      - "FaroFundamentalIngestionWeekly" -- weekly, Monday 05:40, action:
        ops/run_fundamental_ingestion_weekly.ps1 (collector.run_fundamental_
        ingestion, logging to logs/fundamental_ingestion_weekly.log). Runs
        ahead of Faro\WeeklyRetrainingCycle's Sunday 06:40 chain by design
        (Monday, not Sunday) -- see that task's own docstring for why the
        ingestion needs a head start before materialization runs.

    This task already existed (registered by hand at some point, not by a
    checked-in script) with a raw `cmd /c ... >> log 2>&1` action that had
    no way to suppress its own console window -- this script re-registers
    it through ops/run_hidden.vbs instead, and gives it a home in version
    control. It sets NO secrets and hardcodes NO password.

.NOTES
    Run this yourself, interactively, from a normal PowerShell prompt. It
    is not invoked automatically by anything in this repository or by CI.
    The task runs as the current user, LIMITED (no elevation), truly
    hidden window (see ops/run_hidden.vbs's own header comment for why a
    plain `powershell -WindowStyle Hidden` action is not enough).
#>

$ErrorActionPreference = 'Stop'

$RepoRoot  = Split-Path -Parent $PSScriptRoot
$Script    = Join-Path $RepoRoot 'ops\run_fundamental_ingestion_weekly.ps1'
$HiddenVbs = Join-Path $RepoRoot 'ops\run_hidden.vbs'

if (-not (Test-Path $Script)) {
    throw "Cannot find $Script - run this from the repo's ops/ folder."
}

Write-Host "Registering FaroFundamentalIngestionWeekly for $env:USERNAME (repo root: $RepoRoot)"

# /RL LIMITED (no elevation at run time), /F overwrites an existing task so
# re-running this script is idempotent. schtasks is an external exe -- its
# failures do NOT throw -- so $LASTEXITCODE is checked explicitly below.
schtasks /Create `
    /TN "FaroFundamentalIngestionWeekly" `
    /SC WEEKLY `
    /D MON `
    /ST 05:40 `
    /RL LIMITED `
    /F `
    /TR "wscript.exe `"$HiddenVbs`" `"$Script`""

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "schtasks failed (exit $LASTEXITCODE) - the task was NOT registered." -ForegroundColor Red
    Write-Host "If it said 'Access is denied', re-run this script from an elevated PowerShell."
    exit 1
}

Write-Host ""
Write-Host "Registered. Verify with:"
Write-Host "  schtasks /Query /TN `"FaroFundamentalIngestionWeekly`" /V /FO LIST"
Write-Host ""
Write-Host "Smoke-test a run on demand with:"
Write-Host "  schtasks /Run /TN `"FaroFundamentalIngestionWeekly`""
Write-Host ""
Write-Host "Remove with:"
Write-Host "  schtasks /Delete /TN `"FaroFundamentalIngestionWeekly`" /F"
