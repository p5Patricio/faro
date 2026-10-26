<#
.SYNOPSIS
    Builds the transfer bundle for moving Faro to another computer: a fresh
    database dump with its verification manifest, the trained models, your
    private documents and the Engram memory, plus a checksum list.

.EXAMPLE
    .\ops\prepare_transfer.ps1 -Destination 'D:\Traslado\Faro'
    .\ops\prepare_transfer.ps1 -Destination 'D:\Traslado\Faro' -PgDump 'C:\Program Files\PostgreSQL\18\bin\pg_dump.exe'

.DESCRIPTION
    Writes into -Destination (outside the repository, on a local folder that
    is NOT synced to any cloud; you carry it by hand):

      db\               pg_dump + JSON export (ops.backup_db; only the newest dump is kept,
                        because the manifest below matches that one)
      db\manifest.json  row counts and md5 per table, taken right after the
                        dump (verify on the new machine with ops.transfer)
      models\ artifacts\ reports\ private\   copied from the repository
      engram-faro.json  Engram memory of project faro (if engram is installed)
      SHA256SUMS.txt    HASH  relative\path for every file in the bundle
      LEEME.md          docs\MIGRACION-NUEVA-PC.md, when it exists

    Safe to re-run: copies are additive and the old dump is replaced. The .env
    file is NEVER copied (it holds secrets): carry it by hand. Nothing is
    uploaded anywhere. The database password reaches pg_dump through
    PGPASSWORD (see ops/backup_db.py), never the command line.
#>
param(
    [Parameter(Mandatory)][string]$Destination,
    [string]$PgDump
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
# Resolve against the caller's location before moving to the repo root.
$Bundle = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Destination).TrimEnd('\')
Set-Location -LiteralPath $RepoRoot

$repoPrefix = $RepoRoot.TrimEnd('\') + '\'
$bundlePrefix = $Bundle + '\'
$overlaps = $bundlePrefix.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase) -or
    $repoPrefix.StartsWith($bundlePrefix, [System.StringComparison]::OrdinalIgnoreCase)
if ($overlaps) {
    throw "The bundle holds private data and must be a separate folder outside the repository ($RepoRoot). Choose another -Destination."
}
New-Item -ItemType Directory -Force -Path $Bundle | Out-Null

function Invoke-Step {
    param([string]$Name, [scriptblock]$Command)
    & $Command | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "$Name failed (exit code $LASTEXITCODE)." }
}

# 1. Database: dump first, manifest immediately after.
$arguments = @('-m', 'ops.backup_db', '--dest', (Join-Path $Bundle 'db'), '--keep', 1)
if ($PgDump) { $arguments += @('--pg-dump', $PgDump) }
Invoke-Step 'Database backup' { py -3.14 @arguments }
$manifest = Join-Path $Bundle 'db\manifest.json'
Invoke-Step 'Manifest' { py -3.14 -m ops.transfer manifest --out $manifest }

# 2. Folders that live outside git. robocopy: exit codes 0-7 are success.
foreach ($folder in 'models', 'artifacts', 'reports', 'private') {
    $source = Join-Path $RepoRoot $folder
    if (-not (Test-Path -LiteralPath $source -PathType Container)) {
        Write-Warning "Skipping $folder\ (not found in the repository)."
        continue
    }
    Write-Host "Copying $folder\ ..."
    robocopy $source (Join-Path $Bundle $folder) /E /R:2 /W:2 /NFL /NDL /NJH /NJS /NP /XF .env | Out-Host
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed for $folder (exit code $LASTEXITCODE)." }
}

# 3. Agent memory.
if (Get-Command engram -ErrorAction SilentlyContinue) {
    Invoke-Step 'Engram export' { engram export (Join-Path $Bundle 'engram-faro.json') --project faro }
} else {
    Write-Warning 'engram is not installed: the agent memory is NOT in the bundle.'
}

# 4. Hand-over notes.
$guide = Join-Path $RepoRoot 'docs\MIGRACION-NUEVA-PC.md'
if (Test-Path -LiteralPath $guide) { Copy-Item -LiteralPath $guide -Destination (Join-Path $Bundle 'LEEME.md') -Force }

# 5. Checksums last, so they cover everything above (format: HASH  relative\path).
Write-Host 'Computing SHA256 checksums ...'
$files = Get-ChildItem -LiteralPath $Bundle -Recurse -File -Force | Where-Object { $_.FullName -ne (Join-Path $Bundle 'SHA256SUMS.txt') }
$lines = foreach ($file in $files) {
    $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    '{0}  {1}' -f $hash, $file.FullName.Substring($Bundle.Length + 1)
}
[System.IO.File]::WriteAllLines((Join-Path $Bundle 'SHA256SUMS.txt'), [string[]]@($lines), (New-Object System.Text.UTF8Encoding $false))

# 6. Summary.
Write-Host ''
Write-Host "Bundle ready: $Bundle"
foreach ($item in Get-ChildItem -LiteralPath $Bundle -Force) {
    if ($item.PSIsContainer) {
        $size = (Get-ChildItem -LiteralPath $item.FullName -Recurse -File -Force | Measure-Object Length -Sum).Sum
    } else {
        $size = $item.Length
    }
    Write-Host ('  {0,-22} {1,10:N1} MB' -f $item.Name, ([double]$size / 1MB))
}
Write-Host ''
Write-Host 'IMPORTANT: .env is NOT in the bundle (it holds your secrets).' -ForegroundColor Yellow
Write-Host 'Carry it by hand to the new computer; docs\env.template lists the keys.' -ForegroundColor Yellow
