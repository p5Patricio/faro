<#
.SYNOPSIS
    Local backup of the Faro database: pg_dump plus a JSON export of your
    personal tables, into a folder on this machine, keeping the newest N.

.EXAMPLE
    .\ops\backup_db.ps1 -Destination 'D:\Respaldos\Faro'
    .\ops\backup_db.ps1 -Destination 'D:\Respaldos\Faro' -Keep 30 -PgDump 'C:\Program Files\PostgreSQL\16\bin\pg_dump.exe'

.DESCRIPTION
    Thin wrapper over `py -3.14 -m ops.backup_db` (all logic and tests live
    there). Reads LOCAL_DATABASE_URL from the root .env like every other job;
    the password goes to pg_dump through PGPASSWORD, never the command line.
    Nothing is copied off the machine (decision D12). To schedule it, register
    this script with Task Scheduler the same way ops/register_local_jobs.ps1
    registers the daily cycle.
#>
param(
    [Parameter(Mandatory = $true)][string]$Destination,
    [int]$Keep = 14,
    [string]$PgDump = 'pg_dump'
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $RepoRoot

py -3.14 -m ops.backup_db --dest $Destination --keep $Keep --pg-dump $PgDump
exit $LASTEXITCODE
