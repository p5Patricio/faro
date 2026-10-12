<#
.SYNOPSIS
    Local backup of the Faro database: pg_dump plus a JSON export of your
    personal tables, into a folder on this machine, keeping the newest N.

.EXAMPLE
    .\ops\backup_db.ps1 -Destination 'D:\Respaldos\Faro'
    .\ops\backup_db.ps1 -Destination 'D:\Respaldos\Faro' -Keep 30 -PgDump 'C:\Program Files\PostgreSQL\16\bin\pg_dump.exe'
    .\ops\backup_db.ps1    # folder and pg_dump from FARO_BACKUP_DIR / PG_DUMP_PATH in .env

.DESCRIPTION
    Thin wrapper over `py -3.14 -m ops.backup_db` (all logic and tests live
    there). Reads LOCAL_DATABASE_URL from the root .env like every other job;
    the password goes to pg_dump through PGPASSWORD, never the command line.
    Nothing is copied off the machine (decision D12). Without arguments it
    is what the Faro\DailyBackup scheduled task runs (see
    ops/register_backup_task.ps1).
#>
param(
    [string]$Destination,
    [int]$Keep = 14,
    [string]$PgDump
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $RepoRoot

$arguments = @('-m', 'ops.backup_db', '--keep', $Keep)
if ($Destination) { $arguments += @('--dest', $Destination) }
if ($PgDump) { $arguments += @('--pg-dump', $PgDump) }

py -3.14 @arguments
exit $LASTEXITCODE
