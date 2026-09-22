<#
.SYNOPSIS
    Hidden-window entry point for the Faro\DailyOperationalCycle
    scheduled task.

.DESCRIPTION
    cd + run the daily market-data -> inference -> paper-trading cycle.
    Replaces a raw `cmd /c cd /d ... && py ...` action (no way to
    suppress its own console window) so the task's action can be the
    single, quote-free `wscript.exe run_hidden.vbs <this file>` instead.
    See ops/register_local_jobs.ps1 and ops/run_hidden.vbs.
#>

$ErrorActionPreference = 'Continue'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $RepoRoot

py -3.14 -m ops.run_local_scheduler --job full
