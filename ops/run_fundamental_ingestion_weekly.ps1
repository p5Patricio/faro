<#
.SYNOPSIS
    Hidden-window entry point for the FaroFundamentalIngestionWeekly
    scheduled task.

.DESCRIPTION
    cd + run the weekly SEC fundamental-facts ingestion, redirecting its
    own output to logs/fundamental_ingestion_weekly.log. That redirect
    used to be appended by the scheduled task's own /TR command line
    (`cmd /c ... >> log 2>&1`, which has no way to suppress its own
    console window); moving it in here lets the task's action be the
    single, quote-free `wscript.exe run_hidden.vbs <this file>` instead.
    See ops/register_fundamental_ingestion_weekly.ps1 and
    ops/run_hidden.vbs.
#>

$ErrorActionPreference = 'Continue'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $RepoRoot

py -3.14 -m collector.run_fundamental_ingestion --out artifacts/fund_coverage_weekly.json *>> logs/fundamental_ingestion_weekly.log
