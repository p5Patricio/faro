<#
.SYNOPSIS
    Hidden-window entry point for the Faro\WeeklyRetrainingCycle
    scheduled task.

.DESCRIPTION
    Runs ops/weekly_retrain_all.ps1, redirecting its output to
    logs/weekly_retrain_all.log. That redirect used to be appended by
    the scheduled task's own /TR command line; moving it in here lets
    the task's action be the single, quote-free
    `wscript.exe run_hidden.vbs <this file>` instead of
    `powershell -WindowStyle Hidden -File ... >> log 2>&1` (which still
    briefly flashes a console before hiding it -- a known conhost quirk,
    confirmed live against Faro\FinanceBotSync). See
    ops/register_local_jobs.ps1 and ops/run_hidden.vbs.
#>

$ErrorActionPreference = 'Continue'
$RepoRoot = Split-Path -Parent $PSScriptRoot

& (Join-Path $RepoRoot 'ops\weekly_retrain_all.ps1') *>> (Join-Path $RepoRoot 'logs\weekly_retrain_all.log')
