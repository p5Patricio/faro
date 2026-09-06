<#
.SYNOPSIS
    Register a Windows Task Scheduler task that starts the Faro API and
    frontend dev servers at every logon.

.DESCRIPTION
    Creates:
      - "Faro\LocalAppServers"  -- trigger: ONLOGON, action:
        ops/run_local_app.ps1 (API on 127.0.0.1:47318, frontend on
        127.0.0.1:47319, both logging under logs/). run_local_app.ps1
        no-ops any server that is already up, so a manual start earlier in
        the day is not disturbed.

    Companion to ops/register_local_jobs.ps1 (the daily/weekly operational
    cron). Same rules: this only registers the schtask. It sets NO secrets
    and hardcodes NO password -- LOCAL_DATABASE_URL etc. must already be in
    your environment or the root .env before the task runs. schtasks /Query
    /V and the Task Scheduler UI show the full command line in clear text,
    so never add credentials to the /TR string.

.NOTES
    Run this yourself, once, from a normal PowerShell prompt. Nothing in the
    repo or CI invokes it. The task runs as the current user, LIMITED (no
    elevation), hidden window.

    Before the frontend can reach the API, set this in the root .env:
        VITE_API_BASE_URL=http://localhost:47318/api
#>

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Script   = Join-Path $RepoRoot 'ops\run_local_app.ps1'

if (-not (Test-Path $Script)) {
    throw "Cannot find $Script - run this from the repo's ops/ folder."
}

Write-Host "Registering Faro\LocalAppServers (repo root: $RepoRoot)"

# ONLOGON trigger, current user, non-elevated, hidden. Overwrites (/F) an
# existing task of the same name so re-running this is idempotent.
schtasks /Create `
    /TN "Faro\LocalAppServers" `
    /SC ONLOGON `
    /RL LIMITED `
    /F `
    /TR "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`""

Write-Host ""
Write-Host "Registered. It fires at your next logon. Commands:"
Write-Host "  Start now   : schtasks /Run /TN `"Faro\LocalAppServers`""
Write-Host "  Inspect     : schtasks /Query /TN `"Faro\LocalAppServers`" /V /FO LIST"
Write-Host "  Unregister  : schtasks /Delete /TN `"Faro\LocalAppServers`" /F"
Write-Host ""
Write-Host "  App status  : powershell -NoProfile -File `"$Script`" -Status"
Write-Host "  Stop app    : powershell -NoProfile -File `"$Script`" -Stop"
Write-Host ""
Write-Host "Dashboard once it is up: http://127.0.0.1:47319"
Write-Host ""
Write-Host "STILL TO DO BY YOU: set  VITE_API_BASE_URL=http://localhost:47318/api  in the root .env,"
Write-Host "otherwise the frontend loads but shows no data."
Write-Host ""
Write-Host "The task runs only while you are logged in (/RL LIMITED, no stored password)." `
    "To keep it running while logged off, re-create it with an added" `
    "'/RU `"%USERNAME%`" /RP *' (prompts for your Windows password; never store it here)."
