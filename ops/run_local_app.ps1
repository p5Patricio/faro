<#
.SYNOPSIS
    Start (or stop / check) the Faro API and frontend dev servers locally.

.DESCRIPTION
    Runs two long-lived processes, each appending to a file under logs/:
      - API      : uvicorn api.main:app on 127.0.0.1:47318  -> logs/app_api.log
      - Frontend : vite dev server      on 127.0.0.1:47319  -> logs/app_ui.log

    Ports 47318 / 47319 are chosen ON PURPOSE outside the common dev range
    (3000, 4200, 5173, 8000, 8080, 9000, ...) so this app does not fight for
    ports with other projects on the same machine. They are still below the
    Windows ephemeral range (49152+), so the OS will not grab them either.

    If you change the ports here you MUST also update the root .env:
        VITE_API_BASE_URL=http://localhost:47318/api
    Vite reads that at startup (ui/vite.config.ts has envDir: '..'); without
    it the frontend loads but cannot reach the API.

    A server already listening on its port is left untouched, so this script
    is safe to run repeatedly -- including from the "at log on" Task
    Scheduler trigger registered by ops/register_local_app.ps1.

.PARAMETER Stop
    Stop the servers this script started (matched by their listening port),
    instead of starting them.

.PARAMETER Status
    Print whether each port is currently listening, then exit. Changes
    nothing.

.NOTES
    Sets no secrets. LOCAL_DATABASE_URL, TELEGRAM_* etc. must already be in
    your user environment or the root .env (python-dotenv and Vite load it).
    Runs uvicorn without --reload on purpose: this is a monitoring server,
    not a dev-edit loop. After changing backend code, -Stop then re-run.
#>
[CmdletBinding(DefaultParameterSetName = 'Start')]
param(
    [Parameter(ParameterSetName = 'Stop')]   [switch]$Stop,
    [Parameter(ParameterSetName = 'Status')] [switch]$Status
)

$ErrorActionPreference = 'Stop'

$ApiPort  = 47318
$UiPort   = 47319
$RepoRoot = Split-Path -Parent $PSScriptRoot
$LogDir   = Join-Path $RepoRoot 'logs'

function Get-Listener([int]$Port) {
    Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

$targets = @(
    [pscustomobject]@{ Name = 'API';      Port = $ApiPort },
    [pscustomobject]@{ Name = 'Frontend'; Port = $UiPort }
)

if ($Status) {
    foreach ($t in $targets) {
        $l = Get-Listener $t.Port
        if ($l) { '{0,-9} 127.0.0.1:{1}  LISTENING (pid {2})' -f $t.Name, $t.Port, $l.OwningProcess }
        else    { '{0,-9} 127.0.0.1:{1}  down' -f $t.Name, $t.Port }
    }
    return
}

if ($Stop) {
    foreach ($t in $targets) {
        $l = Get-Listener $t.Port
        if (-not $l) { '{0}: nothing on {1}' -f $t.Name, $t.Port; continue }
        # /T also ends the child tree (npm -> node, py launcher -> python).
        taskkill /PID $l.OwningProcess /T /F | Out-Null
        '{0}: stopped pid {1} on {2}' -f $t.Name, $l.OwningProcess, $t.Port
    }
    return
}

# ---- Start ----
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

if (Get-Listener $ApiPort) {
    "API already listening on $ApiPort - left as is"
}
else {
    $apiLog = Join-Path $LogDir 'app_api.log'
    "--- $(Get-Date -Format o) start API 127.0.0.1:$ApiPort ---" | Out-File -Append -Encoding utf8 $apiLog
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/c', "py -3.14 -m uvicorn api.main:app --host 127.0.0.1 --port $ApiPort >> `"$apiLog`" 2>&1" `
        -WorkingDirectory $RepoRoot -WindowStyle Hidden
    "API      starting -> http://127.0.0.1:$ApiPort   (log: $apiLog)"
}

if (Get-Listener $UiPort) {
    "Frontend already listening on $UiPort - left as is"
}
else {
    $uiLog = Join-Path $LogDir 'app_ui.log'
    "--- $(Get-Date -Format o) start frontend 127.0.0.1:$UiPort ---" | Out-File -Append -Encoding utf8 $uiLog
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/c', "npm run dev -- --host 127.0.0.1 --port $UiPort --strictPort >> `"$uiLog`" 2>&1" `
        -WorkingDirectory (Join-Path $RepoRoot 'ui') -WindowStyle Hidden
    "Frontend starting -> http://127.0.0.1:$UiPort   (log: $uiLog)"
}

''
"Dashboard : http://127.0.0.1:$UiPort"
"Status    : powershell -NoProfile -File `"$PSCommandPath`" -Status"
"Stop      : powershell -NoProfile -File `"$PSCommandPath`" -Stop"
